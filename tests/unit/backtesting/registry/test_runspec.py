"""Tests for ATS-1708 RunSpec + ATS-1709 data_snapshot_hash."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.backend.backtesting.registry.runspec import EvaluationRole, RunSpec
from src.backend.backtesting.registry.snapshot import compute_data_snapshot_hash


# ── helpers ──────────────────────────────────────────────────────────

def _make_runspec(**overrides):
    defaults = dict(
        strategy_hash="a" * 64,
        evaluation_role=EvaluationRole.IS,
        window_start=date(2010, 1, 1),
        window_end=date(2020, 12, 31),
        data_snapshot_hash="b" * 64,
    )
    defaults.update(overrides)
    return RunSpec(**defaults)


def _make_ohlcv(rows=100, seed=42):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=rows, freq="B")
    close = 100 + np.cumsum(rng.standard_normal(rows))
    return pd.DataFrame(
        {
            "Open": close + rng.uniform(-1, 1, rows),
            "High": close + abs(rng.standard_normal(rows)),
            "Low": close - abs(rng.standard_normal(rows)),
            "Close": close,
            "Volume": rng.integers(1000, 100000, rows),
        },
        index=idx,
    )


# ── RunSpec ──────────────────────────────────────────────────────────

class TestRunSpec:
    def test_hash_determinism(self):
        hashes = {_make_runspec().run_spec_hash for _ in range(100)}
        assert len(hashes) == 1

    def test_different_windows_different_hash(self):
        r1 = _make_runspec(window_end=date(2020, 12, 31))
        r2 = _make_runspec(window_end=date(2019, 12, 31))
        assert r1.run_spec_hash != r2.run_spec_hash

    def test_different_evaluation_role_different_hash(self):
        r1 = _make_runspec(evaluation_role=EvaluationRole.IS)
        r2 = _make_runspec(evaluation_role=EvaluationRole.VALIDATION)
        assert r1.run_spec_hash != r2.run_spec_hash

    def test_different_strategy_hash_different_spec_hash(self):
        r1 = _make_runspec(strategy_hash="a" * 64)
        r2 = _make_runspec(strategy_hash="c" * 64)
        assert r1.run_spec_hash != r2.run_spec_hash

    def test_hash_is_sha256_hex(self):
        h = _make_runspec().run_spec_hash
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_evaluation_role_enum_values(self):
        assert EvaluationRole.IS == "IS"
        assert EvaluationRole.VALIDATION == "VALIDATION"
        assert EvaluationRole.OOS_INTERNAL == "OOS_INTERNAL"

    def test_requires_strategy_hash(self):
        with pytest.raises(ValueError, match="strategy_hash must not be empty"):
            _make_runspec(strategy_hash="")

    def test_window_end_must_be_after_start(self):
        with pytest.raises(ValueError, match="window_end.*must be after"):
            _make_runspec(
                window_start=date(2020, 1, 1),
                window_end=date(2019, 1, 1),
            )

    def test_same_day_window_rejected(self):
        with pytest.raises(ValueError, match="window_end.*must be after"):
            _make_runspec(
                window_start=date(2020, 1, 1),
                window_end=date(2020, 1, 1),
            )


# ── data_snapshot_hash ───────────────────────────────────────────────

class TestDataSnapshotHash:
    def test_same_data_same_hash(self):
        df = _make_ohlcv()
        h1 = compute_data_snapshot_hash(df)
        h2 = compute_data_snapshot_hash(df.copy())
        assert h1 == h2

    def test_different_data_different_hash(self):
        df1 = _make_ohlcv()
        df2 = _make_ohlcv()
        df2.iloc[50, df2.columns.get_loc("Close")] += 0.01
        assert compute_data_snapshot_hash(df1) != compute_data_snapshot_hash(df2)

    def test_hash_independent_of_row_order(self):
        df = _make_ohlcv()
        shuffled = df.sample(frac=1)  # random row order
        assert compute_data_snapshot_hash(df) == compute_data_snapshot_hash(shuffled)

    def test_hash_is_sha256_hex(self):
        h = compute_data_snapshot_hash(_make_ohlcv())
        assert len(h) == 64

    def test_nan_handling(self):
        df = _make_ohlcv()
        df.iloc[10, 0] = np.nan
        # Should not crash, and should be deterministic.
        h1 = compute_data_snapshot_hash(df)
        h2 = compute_data_snapshot_hash(df.copy())
        assert h1 == h2
