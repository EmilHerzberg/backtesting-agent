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


@pytest.mark.finding("M17")
def test_generate_strategy_survives_multiple_optuna_trials():
    import optuna

    from src.backend.backtesting.strategies.generator import generate_strategy

    def objective(trial):
        generate_strategy(trial, max_indicators=3)   # builds the dynamic multi-indicator space
        return 0.0

    study = optuna.create_study()
    study.optimize(objective, n_trials=5)            # pre-fix: trial 2 raised "dynamic value space"
    assert len(study.trials) == 5


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
