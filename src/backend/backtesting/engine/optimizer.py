"""Optuna-based hyperparameter optimization for backtesting strategies."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import optuna
import pandas as pd

from src.backend.backtesting.engine.exceptions import (
    BacktestError,
    InvalidParameterError,
    OptimizationError,
)
from src.backend.backtesting.engine.runner import (
    BacktestConfig,
    BacktestResult,
    run_backtest,
)
from src.backend.backtesting.indicators.base import suggest_params

logger = logging.getLogger(__name__)


def _determinism_mode_active() -> bool:
    """Return True when BACKTEST_DETERMINISM_MODE env var is truthy (ATS-2004)."""
    return os.environ.get("BACKTEST_DETERMINISM_MODE", "").strip().lower() in {
        "1", "true", "yes", "on",
    }

# Default composite weights used when none are supplied.
# M4: max_drawdown is a FRACTION (F-013), so the old -0.4 weight made a 50% drawdown contribute only
# -0.2 vs +0.6 per Sharpe unit — the composite silently degenerated to Sharpe maximization. Rescaled
# for fraction units so a bad drawdown meaningfully offsets Sharpe (a 50% DD ≈ -0.75).
_DEFAULT_COMPOSITE_WEIGHTS: dict[str, float] = {
    "sharpe": 0.6,
    "max_drawdown": -1.5,
}


@dataclass
class OptimizationConfig:
    """Configuration for an Optuna optimization run.

    Attributes:
        strategy_class: A :class:`StrategyBase` subclass that implements
            ``parameter_space()`` and ``create_with_params()``.
        data: OHLCV DataFrame to optimise against.
        n_trials: Maximum number of Optuna trials.
        sampler: Optuna sampler name -- ``"tpe"``, ``"random"``, or ``"cmaes"``.
        pruner: Optuna pruner name -- ``"median"``, ``"hyperband"``, or ``"none"``.
        direction: ``"maximize"`` or ``"minimize"``.
        objective_metric: Metric to optimise: ``"sharpe"``, ``"return"``,
            ``"sortino"``, or ``"composite"``.
        composite_weights: Weights for the composite objective.  Keys are
            metric names (``sharpe``, ``max_drawdown``, ``return``, ``sortino``);
            values are weights (negative for metrics that should be minimised).
        cash: Starting cash for each trial.
        commission: Per-trade commission fraction.
        timeout_seconds: Soft wall-clock budget for the whole study. ``None``
            disables the timeout. (ATS-181)
        pruner_warmup_trials: Number of initial trials that are exempt from
            pruning — only used when ``pruner=="median"``. (ATS-181)
        n_jobs: Parallel workers for ``study.optimize``. ``1`` = serial.
            Strategies and data must be picklable when ``> 1``. (ATS-181)
        early_stop_patience: Stop the study after N consecutive trials show
            no improvement of the best value. ``None`` disables. (ATS-181)
    """

    strategy_class: type
    data: pd.DataFrame
    n_trials: int = 100
    sampler: str = "tpe"
    pruner: str = "median"
    direction: str = "maximize"
    objective_metric: str = "composite"
    composite_weights: dict[str, float] | None = None
    cash: float = 10_000.0
    commission: float = 0.001
    # ATS-181 / E3-S3-T3 — Search-space knobs
    timeout_seconds: int | None = None
    pruner_warmup_trials: int = 10
    n_jobs: int = 1
    early_stop_patience: int | None = None
    # ATS-2004 — Determinism: seed propagates to TPESampler / RandomSampler.
    # In determinism mode, n_jobs is force-clamped to 1.
    seed: int | None = None


@dataclass
class OptimizationResult:
    """Result of an Optuna optimization run.

    Attributes:
        best_params: Best parameter combination found.
        best_value: Objective value of the best trial.
        best_result: Full :class:`BacktestResult` for the best parameters.
        n_trials: Total number of trials executed.
        study_name: Name of the Optuna study.
        all_trials: Summary dicts for every trial (params + value + state).
    """

    best_params: dict[str, Any]
    best_value: float
    best_result: BacktestResult
    n_trials: int
    study_name: str
    all_trials: list[dict[str, Any]] = field(default_factory=list)


def optimize(
    config: OptimizationConfig,
    callbacks: list[Any] | None = None,
) -> OptimizationResult:
    """Run Optuna hyperparameter optimization over a strategy.

    Args:
        config: Optimization configuration.

    Returns:
        An :class:`OptimizationResult` with the best parameters and metrics.

    Raises:
        OptimizationError: If no valid trial completes successfully.
    """
    sampler = _create_sampler(config.sampler, seed=config.seed)
    pruner = _create_pruner(config.pruner, warmup_trials=config.pruner_warmup_trials)

    # ATS-2004: clamp n_jobs to 1 in determinism mode — parallel Optuna
    # workers can't be guaranteed to evaluate trials in a stable order, and
    # the TPESampler internal state diverges from the reference single-thread
    # run otherwise.
    effective_n_jobs = config.n_jobs
    if _determinism_mode_active() and effective_n_jobs != 1:
        logger.warning(
            "ATS-2004: determinism mode — clamping Optuna n_jobs from %d to 1.",
            effective_n_jobs,
        )
        effective_n_jobs = 1

    study = optuna.create_study(
        direction=config.direction,
        sampler=sampler,
        pruner=pruner,
    )

    # Suppress Optuna's verbose trial logging
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial: optuna.Trial) -> float:
        # Retrieve the parameter space from the strategy class
        try:
            space = config.strategy_class.parameter_space()
        except NotImplementedError:
            raise OptimizationError(
                f"{config.strategy_class.__name__} does not define parameter_space().",
                n_trials=0,
            )

        params = suggest_params(trial, space)

        # F-016..F-020 fix: gracefully reject invalid parameter combinations.
        # Optuna prunes the trial via TrialPruned so it doesn't pollute the
        # study; -inf would also work but pruning is the idiomatic Optuna way.
        try:
            strategy_cls = config.strategy_class.create_with_params(**params)
        except InvalidParameterError:
            import optuna
            raise optuna.TrialPruned("Invalid parameter combination")

        bt_config = BacktestConfig(
            symbol="OPT",
            strategy_class=strategy_cls,
            data=config.data,
            cash=config.cash,
            commission=config.commission,
        )

        try:
            result = run_backtest(bt_config)
        except BacktestError:
            return float("-inf")
        except Exception:
            return float("-inf")

        return _calculate_objective(result, config)

    # ATS-181: assemble callbacks (early-stop) + pass timeout / n_jobs
    all_callbacks = list(callbacks) if callbacks else []
    if config.early_stop_patience is not None and config.early_stop_patience > 0:
        all_callbacks.append(_make_early_stop_callback(config.early_stop_patience))

    study.optimize(
        objective,
        n_trials=config.n_trials,
        timeout=config.timeout_seconds,
        n_jobs=effective_n_jobs,
        show_progress_bar=False,
        callbacks=all_callbacks,
    )

    return _build_optimization_result(study, config)


# ---------------------------------------------------------------------- #
# Internal helpers
# ---------------------------------------------------------------------- #


def _create_sampler(
    name: str,
    *,
    seed: int | None = None,
) -> optuna.samplers.BaseSampler:
    """Instantiate an Optuna sampler by name.

    Args:
        name: ``"tpe"``, ``"random"``, or ``"cmaes"``.
        seed: ATS-2004 — passed through to the sampler constructor so identical
            seeds produce identical trial sequences.
    """
    name_lower = name.lower().strip()
    if name_lower == "tpe":
        return optuna.samplers.TPESampler(seed=seed)
    elif name_lower == "random":
        return optuna.samplers.RandomSampler(seed=seed)
    elif name_lower == "cmaes":
        return optuna.samplers.CmaEsSampler(seed=seed)
    else:
        logger.warning("Unknown sampler '%s', falling back to TPE.", name)
        return optuna.samplers.TPESampler(seed=seed)


def _create_pruner(name: str, *, warmup_trials: int = 10) -> optuna.pruners.BasePruner:
    """Instantiate an Optuna pruner by name.

    Args:
        name: ``"median"``, ``"hyperband"``, or ``"none"``.
        warmup_trials: Number of initial trials exempt from pruning. Only
            applied when ``name=="median"`` (ATS-181).
    """
    name_lower = name.lower().strip()
    if name_lower == "median":
        return optuna.pruners.MedianPruner(n_startup_trials=warmup_trials)
    elif name_lower == "hyperband":
        return optuna.pruners.HyperbandPruner()
    elif name_lower == "none":
        return optuna.pruners.NopPruner()
    else:
        logger.warning("Unknown pruner '%s', falling back to MedianPruner.", name)
        return optuna.pruners.MedianPruner(n_startup_trials=warmup_trials)


def _make_early_stop_callback(patience: int):
    """Return a callback that stops the study if best_value stagnates.

    A trial counts as 'no improvement' when its value is not strictly better
    than the best-seen so far (direction-aware via Optuna's internal study).
    After *patience* consecutive non-improving trials, the callback calls
    ``study.stop()``. (ATS-181)
    """
    state = {"best": None, "stale": 0}

    def _callback(study: optuna.Study, trial: optuna.trial.FrozenTrial) -> None:
        value = trial.value
        if value is None:
            return  # pruned / failed trial — don't count
        if state["best"] is None:
            state["best"] = value
            return
        # Direction-aware "improved" check via the study's best_value
        improved = value == study.best_value and value != state["best"]
        if improved:
            state["best"] = value
            state["stale"] = 0
        else:
            state["stale"] += 1
            if state["stale"] >= patience:
                logger.info(
                    "Early-stop: no improvement in %d consecutive trials — stopping study.",
                    patience,
                )
                study.stop()

    return _callback


def _calculate_objective(
    result: BacktestResult,
    config: OptimizationConfig,
) -> float:
    """Compute the scalar objective value from a backtest result.

    Args:
        result: Completed backtest result.
        config: Optimization config (contains metric selection / weights).

    Returns:
        Scalar value to be maximised (or minimised, depending on study direction).
    """
    metric = config.objective_metric.lower().strip()

    if metric == "sharpe":
        return result.sharpe_ratio
    elif metric == "return":
        return result.total_return
    elif metric == "sortino":
        return result.sortino_ratio
    elif metric == "composite":
        weights = config.composite_weights or _DEFAULT_COMPOSITE_WEIGHTS
        metric_map: dict[str, float] = {
            "sharpe": result.sharpe_ratio,
            "max_drawdown": result.max_drawdown,
            "return": result.total_return,
            "sortino": result.sortino_ratio,
            "win_rate": result.win_rate,
            "profit_factor": result.profit_factor,
            "calmar": result.calmar_ratio,
        }
        score = 0.0
        for key, weight in weights.items():
            value = metric_map.get(key, 0.0)
            score += weight * value
        return score
    else:
        logger.warning(
            "Unknown objective metric '%s', using Sharpe ratio.", metric
        )
        return result.sharpe_ratio


def _build_optimization_result(
    study: optuna.Study,
    config: OptimizationConfig,
) -> OptimizationResult:
    """Build an :class:`OptimizationResult` from a completed Optuna study.

    Raises:
        OptimizationError: If the study contains no completed trials.
    """
    completed = [
        t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE
    ]
    if not completed:
        raise OptimizationError(
            "Optimization produced no completed trials.",
            n_trials=len(study.trials),
        )

    best_trial = study.best_trial
    best_params = best_trial.params

    # Re-run the best params to get the full BacktestResult
    strategy_cls = config.strategy_class.create_with_params(**best_params)
    bt_config = BacktestConfig(
        symbol="OPT_BEST",
        strategy_class=strategy_cls,
        data=config.data,
        cash=config.cash,
        commission=config.commission,
    )
    best_result = run_backtest(bt_config)

    # Summarise all trials
    all_trials: list[dict[str, Any]] = []
    for t in study.trials:
        all_trials.append(
            {
                "number": t.number,
                "params": dict(t.params),
                "value": t.value,
                "state": t.state.name,
            }
        )

    return OptimizationResult(
        best_params=best_params,
        best_value=best_trial.value if best_trial.value is not None else 0.0,
        best_result=best_result,
        n_trials=len(study.trials),
        study_name=study.study_name,
        all_trials=all_trials,
    )
