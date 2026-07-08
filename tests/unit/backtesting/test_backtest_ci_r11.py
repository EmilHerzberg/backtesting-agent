"""Track A / A2 — R11: opt-in Sharpe confidence interval on a single backtest (valconf spec §5.8)."""
from __future__ import annotations

import pytest

from src.backend.backtesting.engine.optimizer import OptimizationConfig, optimize
from src.backend.backtesting.engine.runner import BacktestConfig, run_backtest
from src.backend.backtesting.strategies.sma_crossover import SMACrossover
from tests.support.frozen_data import make_ohlcv


def _strat():
    return SMACrossover.create_with_params(fast_period=10, slow_period=30)


@pytest.mark.finding("R11")
def test_sharpe_ci_is_opt_in_and_deterministic():
    data = make_ohlcv(days=400, seed=3)
    strat = _strat()

    off = run_backtest(BacktestConfig(symbol="T", strategy_class=strat, data=data, seed=1))
    assert off.sharpe_ci_low is None and off.sharpe_ci_high is None          # off by default

    on1 = run_backtest(BacktestConfig(symbol="T", strategy_class=strat, data=data, seed=1,
                                      compute_confidence_interval=True))
    on2 = run_backtest(BacktestConfig(symbol="T", strategy_class=strat, data=data, seed=1,
                                      compute_confidence_interval=True))
    assert on1.sharpe_ci_low is not None and on1.sharpe_ci_low <= on1.sharpe_ci_high
    # seeded → identical CI across runs (M12 determinism preserved)
    assert (on1.sharpe_ci_low, on1.sharpe_ci_high) == (on2.sharpe_ci_low, on2.sharpe_ci_high)


@pytest.mark.finding("R11")
def test_optimizer_headline_result_carries_a_ci():
    # the CLI's headline (optimizer best-result rerun) attaches a Sharpe CI (sampling precision).
    # SEEDED so the trial sequence — and thus the best result — is deterministic: an unseeded run
    # occasionally lands on a no-trade best strategy (flat equity → CI legitimately None), which made
    # this test flaky. A fixed seed pins a trading best result with a real CI.
    cfg = dict(strategy_class=SMACrossover, data=make_ohlcv(days=400, seed=4), n_trials=8, seed=42)
    res = optimize(OptimizationConfig(**cfg))
    assert res.best_result.sharpe_ci_low is not None
    assert res.best_result.sharpe_ci_low <= res.best_result.sharpe_ci_high
    # deterministic: same seed → identical headline CI (M12)
    res2 = optimize(OptimizationConfig(**cfg))
    assert (res.best_result.sharpe_ci_low, res.best_result.sharpe_ci_high) == \
           (res2.best_result.sharpe_ci_low, res2.best_result.sharpe_ci_high)
