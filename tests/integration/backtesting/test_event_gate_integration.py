"""ATS-2080 — Integration tests for backtest event-gate consumption.

Each test seeds a tiny ``event_gate_decisions`` set in-memory (or hand-
constructs the resulting pandas DataFrame and injects it via
``gates_df=`` on :func:`run_backtest`) and runs SMACrossover on a
synthetic OHLCV series. The synthetic series is engineered so the SMA
fires a single, known entry signal at a predictable bar — that lets us
assert blocked / reduced counts deterministically.

Coverage (DoD ≥5):

* ``test_backtest_without_event_gate_unchanged`` — no gate config → no
  gate fields populated; behaviour bit-identical to pre-2080.
* ``test_backtest_with_block_gate_reduces_trade_count`` — BLOCK gate
  on the entry bar suppresses the trade.
* ``test_backtest_gate_respects_available_at`` — gate whose
  ``available_at`` is AFTER the entry bar must NOT suppress (look-ahead).
* ``test_backtest_reduce_action_halves_size`` — REDUCE gate sets the
  size multiplier to ``0.5``; the recorded ``reduced_log`` carries it.
* ``test_backtest_blocked_trades_logged`` — log carries event_id +
  reason text per suppression.
* ``test_backtest_disabled_gate_passes_through`` — ``EventGateConfig
  (enabled=False)`` is treated as "no gate".
* ``test_backtest_gate_severity_filter`` — gate below
  ``min_asset_severity`` is ignored.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.backend.backtesting.config.schema import EventGateConfig
from src.backend.backtesting.engine.runner import (
    BacktestConfig,
    run_backtest,
)
from src.backend.backtesting.event_gate import _empty_gates_df
from src.backend.backtesting.strategies import SMACrossover


# --------------------------------------------------------------------------- #
# Test fixtures — synthetic data tailored to fire one SMA crossover.
# --------------------------------------------------------------------------- #

# A 120-bar daily series that walks flat, dips, then climbs.  fast_period=5 /
# slow_period=20 fires a long entry around bar 60.  We compute the bar dates
# so seeded gates can target the entry bar precisely.
_START = date(2024, 1, 1)


def _build_ohlc_with_entry_around_bar60() -> pd.DataFrame:
    """Return a deterministic OHLCV frame engineered for SMA buy + sell cycles.

    We assemble TWO V-shaped wedges so SMA(5)/SMA(20) fires a buy at the
    rebound and a sell at the next decline:

    * Bars 0..30  : flat 100 (warm-up so SMAs converge)
    * Bars 30..60 : V-shape — decline to 80, climb back to 110 → buy ≈ 55
    * Bars 60..90 : inverted-V — climb to 130, decline to 95 → sell ≈ 85
    * Bars 90..120: V-shape — decline to 75, climb to 115 → buy ≈ 115

    The result: ≥ 2 closed entries with ungated SMA, but every entry lies
    in the bar 50..115 range so a single wide gate can suppress them.
    """
    n = 180
    idx = pd.date_range(_START, periods=n, freq="B")
    closes = []
    for i in range(n):
        if i < 30:
            closes.append(100.0)
        elif i < 45:
            closes.append(100.0 - (i - 30) * (20.0 / 15.0))  # 100 → 80
        elif i < 60:
            closes.append(80.0 + (i - 45) * (30.0 / 15.0))   # 80 → 110
        elif i < 75:
            closes.append(110.0 + (i - 60) * (20.0 / 15.0))  # 110 → 130
        elif i < 105:
            closes.append(130.0 - (i - 75) * (35.0 / 30.0))  # 130 → 95
        elif i < 120:
            closes.append(95.0 - (i - 105) * (20.0 / 15.0))  # 95 → 75
        elif i < 150:
            closes.append(75.0 + (i - 120) * (40.0 / 30.0))  # 75 → 115
        else:
            closes.append(115.0 - (i - 150) * (25.0 / 30.0))  # 115 → 90 (forces sell)
    close_arr = pd.Series(closes, index=idx)
    return pd.DataFrame(
        {
            "Open": close_arr,
            "High": close_arr * 1.005,
            "Low": close_arr * 0.995,
            "Close": close_arr,
            "Volume": 1_000_000,
        }
    )


def _gates_df(rows: list[dict]) -> pd.DataFrame:
    """Convert hand-crafted dicts into the schema produced by ``load_gates_for_backtest``."""
    df = _empty_gates_df()
    if not rows:
        return df
    return pd.DataFrame.from_records(rows)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


class TestEventGateIntegration:
    """End-to-end checks that the runner + strategy honor an active gate."""

    def test_backtest_without_event_gate_unchanged(self) -> None:
        """No event_gate config → counters stay zero, logs empty."""
        data = _build_ohlc_with_entry_around_bar60()
        cfg = BacktestConfig(
            symbol="TEST",
            strategy_class=SMACrossover,
            data=data,
            cash=10_000,
        )
        result = run_backtest(cfg)
        assert result.blocked_trades_count == 0
        assert result.reduced_trades_count == 0
        assert result.blocked_trades_log == []
        assert result.reduced_trades_log == []
        # And at least one trade should have fired — confirms the
        # synthetic data does what the gated tests expect.
        assert result.trade_count >= 1

    def test_backtest_disabled_gate_passes_through(self) -> None:
        """An EventGateConfig with enabled=False is a no-op."""
        data = _build_ohlc_with_entry_around_bar60()
        cfg = BacktestConfig(
            symbol="TEST",
            strategy_class=SMACrossover,
            data=data,
            cash=10_000,
            event_gate=EventGateConfig(enabled=False),
        )
        # Even with a "scary" gate sitting in the df, enabled=False
        # bypasses the apply path entirely.
        gates = _gates_df(
            [
                {
                    "event_id": "evt-block",
                    "event_date": data.index[60].date(),
                    "available_at_date": data.index[58].date(),
                    "gate_action": "BLOCK_NEW_ENTRIES",
                    "multiplier": 0.0,
                    "window_before_days": 5,
                    "window_after_days": 5,
                    "risk_severity": 3.0,
                    "reason_text": "scary",
                    "event_importance": 1.0,
                }
            ]
        )
        result = run_backtest(cfg, gates_df=gates)
        assert result.blocked_trades_count == 0
        assert result.reduced_trades_count == 0
        assert result.trade_count >= 1

    def test_backtest_with_block_gate_reduces_trade_count(self) -> None:
        """BLOCK gate spanning every entry bar → fewer trades than ungated."""
        data = _build_ohlc_with_entry_around_bar60()
        # Ungated baseline.
        ungated = run_backtest(
            BacktestConfig(
                symbol="TEST",
                strategy_class=SMACrossover,
                data=data,
                cash=10_000,
            )
        )

        # Build a BLOCK gate that covers the entire climb phase (bars 55..120)
        # so any SMA buy signal in that range is suppressed.
        climb_mid_date = data.index[58].date()
        gates = _gates_df(
            [
                {
                    "event_id": "evt-block",
                    "event_date": climb_mid_date,
                    "available_at_date": data.index[0].date(),
                    "gate_action": "BLOCK_NEW_ENTRIES",
                    "multiplier": 0.0,
                    "window_before_days": 30,
                    "window_after_days": 30,
                    "risk_severity": 2.5,
                    "reason_text": "synthetic block for test",
                    "event_importance": 1.0,
                }
            ]
        )
        gated = run_backtest(
            BacktestConfig(
                symbol="TEST",
                strategy_class=SMACrossover,
                data=data,
                cash=10_000,
                event_gate=EventGateConfig(
                    enabled=True,
                    min_event_importance=0.5,
                    min_asset_severity=0.4,
                ),
            ),
            gates_df=gates,
        )
        assert gated.blocked_trades_count >= 1
        assert gated.trade_count < ungated.trade_count, (
            f"gated trade_count={gated.trade_count} should be < "
            f"ungated={ungated.trade_count}"
        )
        # Each blocked log entry should carry the event id and reason.
        for entry in gated.blocked_trades_log:
            assert entry["event_id"] == "evt-block"
            assert "synthetic block for test" in entry["reason"]
            assert entry["gate_action"] == "BLOCK_NEW_ENTRIES"

    def test_backtest_gate_respects_available_at(self) -> None:
        """Gate whose ``available_at`` is AFTER the entry bar must NOT fire.

        The strategy enters somewhere in the bar 60..70 range. We set the
        event date there but ``available_at`` two months later — the
        market did not yet know about the event when the trade fired, so
        the gate cannot suppress it.
        """
        data = _build_ohlc_with_entry_around_bar60()
        entry_window = data.index[60].date()
        gates = _gates_df(
            [
                {
                    "event_id": "evt-future-known",
                    "event_date": entry_window,
                    "available_at_date": data.index[100].date(),
                    "gate_action": "BLOCK_NEW_ENTRIES",
                    "multiplier": 0.0,
                    "window_before_days": 60,
                    "window_after_days": 60,
                    "risk_severity": 3.0,
                    "reason_text": "would block if known earlier",
                    "event_importance": 1.0,
                }
            ]
        )
        result = run_backtest(
            BacktestConfig(
                symbol="TEST",
                strategy_class=SMACrossover,
                data=data,
                cash=10_000,
                event_gate=EventGateConfig(enabled=True),
            ),
            gates_df=gates,
        )
        # Gate cannot apply pre-available_at → trade goes through.
        # available_at = bar 100; entry is around bar 60-70; so on entry
        # bar the gate is not yet active.
        assert result.blocked_trades_count == 0
        assert result.trade_count >= 1

    def test_backtest_reduce_action_halves_size(self) -> None:
        """REDUCE gate → reduced_log entry with multiplier 0.5 recorded."""
        data = _build_ohlc_with_entry_around_bar60()
        climb_mid_date = data.index[58].date()
        gates = _gates_df(
            [
                {
                    "event_id": "evt-reduce",
                    "event_date": climb_mid_date,
                    "available_at_date": data.index[0].date(),
                    "gate_action": "REDUCE_POSITION_SIZE",
                    "multiplier": 0.5,
                    "window_before_days": 30,
                    "window_after_days": 30,
                    "risk_severity": 1.5,
                    "reason_text": "half size",
                    "event_importance": 1.0,
                }
            ]
        )
        result = run_backtest(
            BacktestConfig(
                symbol="TEST",
                strategy_class=SMACrossover,
                data=data,
                cash=10_000,
                event_gate=EventGateConfig(
                    enabled=True,
                    allowed_actions=["REDUCE_POSITION_SIZE"],
                    min_event_importance=0.5,
                    min_asset_severity=0.4,
                ),
            ),
            gates_df=gates,
        )
        assert result.reduced_trades_count >= 1
        # Each reduced entry carries the multiplier.
        for entry in result.reduced_trades_log:
            assert entry["multiplier"] == pytest.approx(0.5)
            assert entry["gate_action"] == "REDUCE_POSITION_SIZE"
        # No BLOCK gate was supplied, so blocked_trades_count must be 0.
        assert result.blocked_trades_count == 0

    def test_backtest_blocked_trades_logged(self) -> None:
        """blocked_trades_log holds event_id + reason per suppression."""
        data = _build_ohlc_with_entry_around_bar60()
        gates = _gates_df(
            [
                {
                    "event_id": "evt-foo-bar-baz",
                    "event_date": data.index[58].date(),
                    "available_at_date": data.index[0].date(),
                    "gate_action": "BLOCK_NEW_ENTRIES",
                    "multiplier": 0.0,
                    "window_before_days": 30,
                    "window_after_days": 30,
                    "risk_severity": 2.5,
                    "reason_text": "important block reason here",
                    "event_importance": 1.0,
                }
            ]
        )
        result = run_backtest(
            BacktestConfig(
                symbol="TEST",
                strategy_class=SMACrossover,
                data=data,
                cash=10_000,
                event_gate=EventGateConfig(enabled=True),
            ),
            gates_df=gates,
        )
        assert result.blocked_trades_count >= 1
        assert len(result.blocked_trades_log) == result.blocked_trades_count
        # Per-entry shape contract.
        for entry in result.blocked_trades_log:
            assert "event_id" in entry
            assert entry["event_id"] == "evt-foo-bar-baz"
            assert "reason" in entry
            assert "important block reason here" in entry["reason"]
            assert "decision_date" in entry
            assert "risk_severity" in entry

    def test_backtest_gate_severity_filter(self) -> None:
        """Gate below ``min_asset_severity`` is ignored — trade goes through."""
        data = _build_ohlc_with_entry_around_bar60()
        gates = _gates_df(
            [
                {
                    "event_id": "evt-weak",
                    "event_date": data.index[58].date(),
                    "available_at_date": data.index[0].date(),
                    "gate_action": "BLOCK_NEW_ENTRIES",
                    "multiplier": 0.0,
                    "window_before_days": 30,
                    "window_after_days": 30,
                    "risk_severity": 0.1,   # too weak
                    "reason_text": "noise",
                    "event_importance": 1.0,
                }
            ]
        )
        result = run_backtest(
            BacktestConfig(
                symbol="TEST",
                strategy_class=SMACrossover,
                data=data,
                cash=10_000,
                event_gate=EventGateConfig(
                    enabled=True,
                    min_asset_severity=0.5,  # gate severity 0.1 < 0.5 → ignored
                ),
            ),
            gates_df=gates,
        )
        assert result.blocked_trades_count == 0
        assert result.trade_count >= 1
