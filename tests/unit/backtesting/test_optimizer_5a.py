"""Phase 5 / cluster 5A — optimizer & walk-forward correctness (M8, M9, M11, M12).

- M9: the composite objective silently ignored unknown weight keys (a typo → weight applied to nothing).
- M11: walk-forward overfitting_score exploded on near-zero train Sharpe (0.001 floor) and the mean was
  meaningless; non-measurable windows are now NaN-excluded and the aggregate is the median.
- M12: determinism mode never seeded the sampler; a seeded run is now reproducible.
- M8: failed trials became COMPLETE -inf trials; they are pruned so an all-failed study raises.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from src.backend.backtesting.engine.exceptions import OptimizationError
from src.backend.backtesting.engine.optimizer import OptimizationConfig, optimize
from src.backend.backtesting.engine.walk_forward import WalkForwardWindow, _build_wf_result
from src.backend.backtesting.strategies.sma_crossover import SMACrossover
from tests.support.frozen_data import make_ohlcv


@pytest.mark.finding("M9")
def test_composite_rejects_unknown_weight_key():
    cfg = OptimizationConfig(
        strategy_class=SMACrossover, data=make_ohlcv(days=120, seed=1), n_trials=2,
        objective_metric="composite", composite_weights={"drawdown": -0.4},   # typo of max_drawdown
    )
    with pytest.raises(OptimizationError, match="Unknown composite weight key"):
        optimize(cfg)


def _win(overfit):
    return WalkForwardWindow(
        window_index=0, train_start="", train_end="", test_start="", test_end="",
        best_params={}, train_result=SimpleNamespace(sharpe_ratio=1.0),
        test_result=SimpleNamespace(sharpe_ratio=0.4), overfitting_score=overfit, is_valid=True,
    )


@pytest.mark.finding("M11")
def test_overfitting_aggregate_excludes_nonmeasurable_and_takes_median():
    # A near-zero-train window is NaN (non-measurable); it must not corrupt the aggregate, and the
    # aggregate is the MEDIAN of the measurable windows (0.5, 1.0, 1.5 → 1.0), not a mean skewed by
    # the old 300-style outliers.
    res = _build_wf_result([_win(0.5), _win(1.0), _win(1.5), _win(float("nan"))], [])
    assert res.avg_overfitting_score == pytest.approx(1.0)


@pytest.mark.finding("M11")
def test_all_nonmeasurable_overfitting_is_zero_not_crash():
    res = _build_wf_result([_win(float("nan")), _win(float("nan"))], [])
    assert res.avg_overfitting_score == 0.0


@pytest.mark.finding("M12")
def test_seeded_optimization_is_reproducible():
    data = make_ohlcv(days=180, seed=2)
    a = optimize(OptimizationConfig(strategy_class=SMACrossover, data=data, n_trials=5, seed=7))
    b = optimize(OptimizationConfig(strategy_class=SMACrossover, data=data, n_trials=5, seed=7))
    assert a.best_params == b.best_params            # same seed → same sampler sequence → same best


@pytest.mark.finding("M12")
def test_determinism_mode_autoseeds_when_no_explicit_seed(monkeypatch):
    # TI-1: the explicit-seed test above ALSO passed on the pre-fix code (explicit-seed plumbing predates
    # M12). The behaviour M12 actually added is auto-injecting a fixed seed when BACKTEST_DETERMINISM_MODE
    # is on and NO seed was supplied — exercise THAT path (seed=None), which was non-reproducible pre-fix.
    monkeypatch.setenv("BACKTEST_DETERMINISM_MODE", "1")
    data = make_ohlcv(days=180, seed=4)
    a = optimize(OptimizationConfig(strategy_class=SMACrossover, data=data, n_trials=5))   # seed=None
    b = optimize(OptimizationConfig(strategy_class=SMACrossover, data=data, n_trials=5))   # seed=None
    assert a.best_params == b.best_params            # determinism mode injects a fixed seed → reproducible


@pytest.mark.finding("M17")
def test_generate_strategy_survives_multiple_optuna_trials():
    import optuna

    from src.backend.backtesting.strategies.generator import generate_strategy

    def objective(trial):
        generate_strategy(trial, max_indicators=3)   # builds the dynamic multi-indicator space
        return 0.0

    # M17-TEST-NONDET: seed the sampler so the multi-indicator trials (which triggered the pre-fix
    # "CategoricalDistribution does not support dynamic value space" crash) are drawn deterministically —
    # the gate no longer depends on the RNG happening to produce >=2 differing picks.
    study = optuna.create_study(sampler=optuna.samplers.TPESampler(seed=0))
    study.optimize(objective, n_trials=8)            # pre-fix: a later trial raised "dynamic value space"
    assert len(study.trials) == 8


@pytest.mark.finding("M17")
def test_generate_strategy_prunes_when_dedup_drops_below_min_indicators():
    # M17-EDGE: if the post-hoc dedup/conflict pruning leaves fewer than min_indicators, the trial must be
    # PRUNED (not silently return an under-sized strategy). Force both slots to pick the SAME indicator.
    import optuna

    from src.backend.backtesting.strategies.generator import SearchSpaceConfig, generate_strategy

    class _DupTrial:
        number = 0

        def suggest_int(self, name, low, high, **_kw):
            return 2 if name == "n_indicators" else low

        def suggest_categorical(self, name, choices, **_kw):
            return choices[0]                     # every slot picks the first indicator → duplicates

        def suggest_float(self, name, low, high, **_kw):
            return (low + high) / 2

    cfg = SearchSpaceConfig(min_indicators=2, max_indicators=3)
    with pytest.raises(optuna.TrialPruned):        # 2 slots, both dedup to 1 < min 2 → pruned
        generate_strategy(_DupTrial(), config=cfg)


@pytest.mark.finding("M8")
def test_all_failing_trials_raise_not_negative_inf_best(monkeypatch):
    import src.backend.backtesting.engine.optimizer as opt
    from src.backend.backtesting.engine.exceptions import BacktestError

    # Force every backtest to fail → every trial pruned → no COMPLETE trial → OptimizationError
    # (pre-fix: each failure was a COMPLETE -inf trial, so a -inf "best" was picked and re-run).
    def _boom(cfg):
        raise BacktestError("boom")

    monkeypatch.setattr(opt, "run_backtest", _boom)
    with pytest.raises(OptimizationError):
        optimize(OptimizationConfig(strategy_class=SMACrossover, data=make_ohlcv(days=120, seed=3), n_trials=4))
