"""Phase 5 / 5B-review — the event gate is actually WIRED through the live entrypoints (F1) and the
gate is honoured for EVERY strategy family, not just SMACrossover (F2/TI-4).

The 5B review found that H13 fixed the strategy side (every template enters via ``_gated_buy``) but the
gate config was never threaded from the CLI/optimizer/walk-forward into the runner, so a YAML-configured
gate stayed inert in production. These tests exercise the wiring end-to-end.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.backend.backtesting.config.schema import EventGateConfig
from src.backend.backtesting.engine.runner import BacktestConfig, run_backtest
from src.backend.backtesting.event_gate import _empty_gates_df
from src.backend.backtesting.strategies.bollinger_breakout import BollingerBreakout
from src.backend.backtesting.strategies.macd_cross import MACDSignalCross
from src.backend.backtesting.strategies.multi_indicator import MultiIndicator
from src.backend.backtesting.strategies.rsi_reversion import RSIMeanReversion
from src.backend.backtesting.strategies.sma_crossover import SMACrossover

_START = pd.Timestamp("2020-01-01")


def _oscillating_ohlc(n: int = 320) -> pd.DataFrame:
    """A deterministic oscillating series (mild uptrend + sine swings) engineered so that mean-reversion
    (RSI, Bollinger) AND trend (SMA, MACD) families all open several positions across the window."""
    idx = pd.date_range(_START, periods=n, freq="B")
    i = np.arange(n)
    close = 100.0 + 0.05 * i + 12.0 * np.sin(i / 7.0) + 4.0 * np.sin(i / 2.3)
    close = pd.Series(close, index=idx)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close * 1.004,
            "Low": close * 0.996,
            "Close": close,
            "Volume": 1_000_000,
        }
    )


def _span_block_gate(data: pd.DataFrame) -> pd.DataFrame:
    """A single BLOCK gate whose window spans the entire series → every entry signal is suppressed."""
    return pd.DataFrame.from_records(
        [
            {
                "event_id": "evt-span-block",
                "event_date": data.index[len(data) // 2].date(),
                "available_at_date": data.index[0].date(),
                "gate_action": "BLOCK_NEW_ENTRIES",
                "multiplier": 0.0,
                "window_before_days": len(data) + 10,
                "window_after_days": len(data) + 10,
                "risk_severity": 2.5,
                "reason_text": "span block for wiring test",
                "event_importance": 1.0,
            }
        ]
    )


_ENABLED_GATE = EventGateConfig(enabled=True, min_event_importance=0.5, min_asset_severity=0.4)


# --------------------------------------------------------------------------- #
# F2 / TI-4 — behavioral gate coverage for EVERY family (not just SMACrossover)
# --------------------------------------------------------------------------- #


@pytest.mark.finding("H13")
@pytest.mark.parametrize(
    "strategy_cls",
    [SMACrossover, MACDSignalCross, RSIMeanReversion, BollingerBreakout, MultiIndicator],
)
def test_block_gate_suppresses_entries_for_every_family(strategy_cls):
    data = _oscillating_ohlc()
    ungated = run_backtest(
        BacktestConfig(symbol="TEST", strategy_class=strategy_cls, data=data, cash=10_000)
    )
    if ungated.trade_count == 0:
        pytest.skip(f"{strategy_cls.__name__} did not trade on the fixture — nothing to gate")

    gated = run_backtest(
        BacktestConfig(
            symbol="TEST", strategy_class=strategy_cls, data=data, cash=10_000, event_gate=_ENABLED_GATE
        ),
        gates_df=_span_block_gate(data),
    )
    # The gate fired on the entry path (proves this family routes through _gated_buy behaviorally, not
    # just textually) and fewer trades resulted.
    assert gated.blocked_trades_count >= 1, strategy_cls.__name__
    assert gated.trade_count < ungated.trade_count, strategy_cls.__name__


def test_fixture_makes_at_least_some_families_trade():
    """Guard against the parametrized test silently all-skipping if the fixture stops producing trades."""
    data = _oscillating_ohlc()
    traded = [
        cls.__name__
        for cls in (SMACrossover, MACDSignalCross, RSIMeanReversion, BollingerBreakout, MultiIndicator)
        if run_backtest(
            BacktestConfig(symbol="TEST", strategy_class=cls, data=data, cash=10_000)
        ).trade_count
        > 0
    ]
    assert len(traded) >= 3, f"only {traded} traded — strengthen the fixture"


# --------------------------------------------------------------------------- #
# F1 — the gate config is threaded through the optimizer and walk-forward
# --------------------------------------------------------------------------- #


@pytest.mark.finding("F1")
def test_optimizer_threads_symbol_gate_and_preloaded_frame_into_run_backtest(monkeypatch):
    """A gate on OptimizationConfig must reach run_backtest: the real symbol + event_gate on the
    BacktestConfig, and the ONCE-preloaded gates frame passed as ``gates_df`` to every trial.

    Pre-fix this could not even be expressed — OptimizationConfig had no ``symbol`` / ``event_gate``
    fields and the runner always saw ``symbol="OPT"`` with ``event_gate=None``."""
    import src.backend.backtesting.engine.optimizer as opt
    import src.backend.backtesting.engine.runner as runner

    preloaded = _empty_gates_df()   # enabled gate but no rows → gate is a no-op, so trials still COMPLETE
    monkeypatch.setattr(runner, "_preload_gates_blocking", lambda symbol, data: preloaded)

    captured: dict = {}
    real_run = opt.run_backtest

    def _spy(cfg, **kwargs):
        captured["symbol"] = cfg.symbol
        captured["event_gate"] = cfg.event_gate
        captured["gates_df_is_preloaded"] = kwargs.get("gates_df") is preloaded
        return real_run(cfg, **kwargs)

    monkeypatch.setattr(opt, "run_backtest", _spy)

    opt.optimize(
        opt.OptimizationConfig(
            strategy_class=SMACrossover,
            data=_oscillating_ohlc(120),
            n_trials=2,
            symbol="TEST",
            event_gate=_ENABLED_GATE,
        )
    )
    assert captured["symbol"] == "TEST"
    assert captured["event_gate"] is not None and captured["event_gate"].enabled
    assert captured["gates_df_is_preloaded"] is True


@pytest.mark.finding("F1")
def test_walk_forward_forwards_symbol_and_gate_to_inner_configs(monkeypatch):
    """WalkForwardConfig must forward symbol + event_gate into BOTH the per-window OptimizationConfig
    and the out-of-sample test BacktestConfig."""
    import src.backend.backtesting.engine.walk_forward as wf

    seen: dict = {}

    def _fake_optimize(opt_config, callbacks=None):
        seen["opt_symbol"] = opt_config.symbol
        seen["opt_gate"] = opt_config.event_gate
        return SimpleNamespace(
            best_params={"fast_period": 5, "slow_period": 20},
            best_result=SimpleNamespace(sharpe_ratio=1.0, equity_curve=[100.0, 101.0]),
        )

    def _fake_run_backtest(cfg, **kwargs):
        seen["test_symbol"] = cfg.symbol
        seen["test_gate"] = cfg.event_gate
        return SimpleNamespace(
            sharpe_ratio=1.0, trade_count=3, equity_curve=[100.0, 101.0, 102.0],
        )

    monkeypatch.setattr(wf, "optimize", _fake_optimize)
    monkeypatch.setattr(wf, "run_backtest", _fake_run_backtest)

    data = _oscillating_ohlc(400)
    result = wf.walk_forward_validate(
        wf.WalkForwardConfig(
            strategy_class=SMACrossover,
            data=data,
            train_size="6m",
            test_size="2m",
            step="2m",
            n_trials_per_window=2,
            symbol="TEST",
            event_gate=_ENABLED_GATE,
        )
    )
    assert result.windows, "fixture produced no walk-forward windows"
    assert seen.get("opt_symbol") == "TEST"
    assert seen.get("opt_gate") is not None and seen["opt_gate"].enabled
    assert seen.get("test_symbol") == "TEST"
    assert seen.get("test_gate") is not None and seen["test_gate"].enabled
