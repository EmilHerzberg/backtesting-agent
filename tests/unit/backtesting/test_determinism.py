"""ATS-2004 — Tests for the Two-Tier backtest determinism hash.

The ``@pytest.mark.determinism`` tests are gated behind ``pytest -m
determinism`` because they require the frozen yfinance snapshot to be
present at ``data/golden/yfinance_snapshot_2026-05-21.parquet``.

The unmarked tests are unit-level and run in the default suite — they
exercise the hash helpers and the determinism-mode toggle without needing
the snapshot.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from src.backend.backtesting.determinism import (
    GOLDEN_SNAPSHOT_PATH,
    RunFingerprint,
    apply_determinism_env,
    canonical_serialize_config,
    compute_h_loose,
    compute_h_strict,
    compute_run_fingerprint,
    is_determinism_mode,
)


@pytest.fixture(autouse=True)
def _isolate_determinism_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """ATS-2004: scope determinism env vars to this module only.

    The marker tests need BACKTEST_DETERMINISM_MODE=true so the engine picks
    the frozen snapshot, but the unit tests that don't need it (and other
    test files that explicitly test the live path) must not see it.  Using
    monkeypatch ensures cleanup on teardown.
    """
    monkeypatch.setenv("BACKTEST_DETERMINISM_MODE", "true")
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.setenv("MKL_NUM_THREADS", "1")
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "1")
    monkeypatch.setenv("PYTHONHASHSEED", "0")

_REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_HASHES_PATH = _REPO_ROOT / "tests" / "golden" / "backtest_hashes.json"


# ---------------------------------------------------------------------------
# Unit tests (no snapshot needed) — always run
# ---------------------------------------------------------------------------


class _FakeTrade:
    """Minimal stand-in for backtesting.engine.metrics.TradeDetail."""

    def __init__(
        self,
        entry_time: str,
        exit_time: str,
        side: str,
        entry_price: float,
        exit_price: float,
        size: float,
    ) -> None:
        self.entry_time = entry_time
        self.exit_time = exit_time
        self.side = side
        self.entry_price = entry_price
        self.exit_price = exit_price
        self.size = size


def test_h_strict_is_order_invariant() -> None:
    """ATS-2004 — Swapping trade order must not change h_strict."""
    a = _FakeTrade("2020-01-01", "2020-02-01", "long", 100.0, 110.0, 1.0)
    b = _FakeTrade("2020-03-01", "2020-04-01", "long", 120.0, 115.0, 2.0)
    assert compute_h_strict([a, b]) == compute_h_strict([b, a])


def test_h_strict_changes_on_trade_difference() -> None:
    a = _FakeTrade("2020-01-01", "2020-02-01", "long", 100.0, 110.0, 1.0)
    b = _FakeTrade("2020-03-01", "2020-04-01", "long", 120.0, 115.0, 2.0)
    c = _FakeTrade("2020-05-01", "2020-06-01", "long", 130.0, 125.0, 2.0)
    assert compute_h_strict([a, b]) != compute_h_strict([a, c])


def test_h_loose_tolerates_below_threshold() -> None:
    """Equity curves differing by < 1e-9 must hash the same."""
    eq1 = [100.0, 101.0, 102.5]
    eq2 = [100.0, 101.0 + 1e-12, 102.5 - 1e-12]
    metrics = {"sharpe": 1.234567, "drawdown": -0.123456}
    assert compute_h_loose(eq1, metrics) == compute_h_loose(eq2, metrics)


def test_h_loose_distinguishes_above_threshold() -> None:
    """A 1e-3 jitter must produce a different h_loose."""
    eq1 = [100.0, 101.0, 102.5]
    eq2 = [100.0, 101.001, 102.5]
    metrics = {"sharpe": 1.234567}
    assert compute_h_loose(eq1, metrics) != compute_h_loose(eq2, metrics)


def test_canonical_serialize_strips_dynamic_class_suffix() -> None:
    """The ``_<id>`` suffix from create_with_params must be stripped."""
    class FooStrat:
        fast_period = 10
        slow_period = 30

    cls1 = type("FooStrat_123456", (FooStrat,), {})
    cls2 = type("FooStrat_999999", (FooStrat,), {})

    class Cfg:
        symbol = "AAPL"
        cash = 10_000.0

    cfg1 = Cfg()
    cfg2 = Cfg()
    cfg1.strategy_class = cls1
    cfg2.strategy_class = cls2

    assert canonical_serialize_config(cfg1) == canonical_serialize_config(cfg2)


def test_is_determinism_mode_truthy_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for val in ("1", "true", "TRUE", "yes", "On"):
        monkeypatch.setenv("BACKTEST_DETERMINISM_MODE", val)
        assert is_determinism_mode(), f"value {val!r} should be truthy"


def test_is_determinism_mode_falsy_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for val in ("", "0", "false", "no", "off"):
        monkeypatch.setenv("BACKTEST_DETERMINISM_MODE", val)
        assert not is_determinism_mode(), f"value {val!r} should be falsy"


def test_apply_determinism_env_sets_all_keys() -> None:
    applied = apply_determinism_env()
    for key in (
        "BACKTEST_DETERMINISM_MODE",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "PYTHONHASHSEED",
    ):
        assert key in applied


def test_compute_run_fingerprint_returns_three_hashes() -> None:
    """Smoke test: fingerprint contains all three required hashes."""
    class FakeResult:
        trades: list = []
        equity_curve = [100.0, 101.0, 102.0]
        total_return = 0.02
        sharpe_ratio = 1.5
        max_drawdown = 0.05
        sortino_ratio = 1.2
        win_rate = 0.6
        trade_count = 0
        profit_factor = 1.4
        calmar_ratio = 0.8
        buy_hold_return = 0.03
        exposure_time = 0.5

    class FakeConfig:
        symbol = "AAPL"
        cash = 10_000.0
        commission = 0.001

    fp = compute_run_fingerprint(FakeResult(), FakeConfig())
    assert isinstance(fp, RunFingerprint)
    assert len(fp.h_strict) == 128  # blake2b default = 64 bytes = 128 hex chars
    assert len(fp.h_loose) == 128
    assert len(fp.h_config) == 128


def test_determinism_mode_disables_yfinance(monkeypatch: pytest.MonkeyPatch) -> None:
    """ATS-2004 — In determinism mode, yfinance.download must NOT be called."""
    monkeypatch.setenv("BACKTEST_DETERMINISM_MODE", "true")

    # Make sure the snapshot file exists for the FrozenSnapshotProvider —
    # this test only verifies routing, not the data itself.  If the snapshot
    # is absent (CI cold-start), we skip rather than fail.
    if not GOLDEN_SNAPSHOT_PATH.exists():
        pytest.skip(f"Golden snapshot missing at {GOLDEN_SNAPSHOT_PATH}")

    import yfinance as yf
    yf_calls: list[tuple] = []
    monkeypatch.setattr(
        yf, "download",
        lambda *a, **kw: yf_calls.append((a, kw)),
        raising=False,
    )
    # Also patch yf.Ticker so accidental usage is caught
    def _ticker_guard(*a, **kw):  # pragma: no cover — only fires on bug
        yf_calls.append(("Ticker", a, kw))
        raise AssertionError("yfinance.Ticker should not be called in determinism mode")
    monkeypatch.setattr(yf, "Ticker", _ticker_guard, raising=False)

    from src.backend.marketdata.provider import YahooProvider
    from src.backend.shared.types import BarInterval

    provider = YahooProvider()
    df = provider.fetch_ohlcv(
        "AAPL",
        BarInterval.ONE_DAY,
        start=datetime(2020, 1, 1),
        end=datetime(2020, 12, 31),
    )
    assert not df.empty, "FrozenSnapshotProvider should have returned AAPL bars"
    assert len(yf_calls) == 0, f"yfinance was invoked: {yf_calls}"


# ---------------------------------------------------------------------------
# Determinism-marker tests (require the frozen snapshot)
# ---------------------------------------------------------------------------


def _import_golden_runner():
    """Lazy-import the determinism-check helpers from the script."""
    scripts_dir = _REPO_ROOT / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        import check_backtest_determinism as mod  # type: ignore[import-not-found]
    finally:
        try:
            sys.path.remove(str(scripts_dir))
        except ValueError:
            pass
    return mod


def _require_snapshot() -> None:
    if not GOLDEN_SNAPSHOT_PATH.exists():
        pytest.skip(
            f"Golden snapshot missing at {GOLDEN_SNAPSHOT_PATH} — "
            "run `python scripts/freeze_yfinance_snapshot.py` first."
        )


@pytest.mark.determinism
def test_run_twice_produces_same_h_strict() -> None:
    _require_snapshot()
    runner = _import_golden_runner()
    fp1, _ = runner.run_once()
    fp2, _ = runner.run_once()
    assert fp1.h_strict == fp2.h_strict


@pytest.mark.determinism
def test_run_twice_produces_same_h_loose_and_h_config() -> None:
    _require_snapshot()
    runner = _import_golden_runner()
    fp1, _ = runner.run_once()
    fp2, _ = runner.run_once()
    assert fp1.h_loose == fp2.h_loose
    assert fp1.h_config == fp2.h_config


@pytest.mark.determinism
def test_run_twice_equity_curves_allclose() -> None:
    _require_snapshot()
    runner = _import_golden_runner()
    _, eq1 = runner.run_once()
    _, eq2 = runner.run_once()
    assert len(eq1) == len(eq2)
    if eq1:
        np.testing.assert_allclose(eq1, eq2, atol=1e-9, rtol=1e-9)


@pytest.mark.determinism
def test_matches_golden_hash() -> None:
    _require_snapshot()
    if not GOLDEN_HASHES_PATH.exists():
        pytest.skip(
            f"Golden hashes missing at {GOLDEN_HASHES_PATH} — "
            "run `python scripts/check_backtest_determinism.py --write-golden` first."
        )
    runner = _import_golden_runner()
    fp, _ = runner.run_once()
    golden = json.loads(GOLDEN_HASHES_PATH.read_text(encoding="utf-8"))
    assert fp.h_strict == golden["h_strict"], (
        f"h_strict drift — stored {golden['h_strict'][:16]}..., "
        f"got {fp.h_strict[:16]}..."
    )
    assert fp.h_config == golden["h_config"], (
        f"h_config drift — stored {golden['h_config'][:16]}..., "
        f"got {fp.h_config[:16]}..."
    )
