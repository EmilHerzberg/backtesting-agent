"""Tests for ATS-1736/1737 — Synthetic OHLCV generation."""

import numpy as np
import pandas as pd

from src.backend.backtesting.gates.synthetic import (
    generate_block_bootstrap_ohlcv,
    generate_random_walk_ohlcv,
)


def _real_ohlcv(n=252, seed=42):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    close = 100 + np.cumsum(rng.standard_normal(n) * 0.5)
    close = np.maximum(close, 10)  # no negatives
    return pd.DataFrame({
        "Open": close + rng.uniform(-0.5, 0.5, n),
        "High": close + np.abs(rng.standard_normal(n)),
        "Low": close - np.abs(rng.standard_normal(n)),
        "Close": close,
        "Volume": rng.integers(10000, 500000, n),
    }, index=idx)


class TestRandomWalkOHLCV:
    def test_output_count(self):
        paths = generate_random_walk_ohlcv(_real_ohlcv(), n_paths=10)
        assert len(paths) == 10

    def test_output_shape_matches_input(self):
        real = _real_ohlcv(100)
        paths = generate_random_walk_ohlcv(real, n_paths=5)
        for p in paths:
            assert p.shape == real.shape
            assert list(p.columns) == ["Open", "High", "Low", "Close", "Volume"]

    def test_ohlcv_structural_validity(self):
        paths = generate_random_walk_ohlcv(_real_ohlcv(), n_paths=20)
        for p in paths:
            assert (p["High"] >= p["Close"]).all()
            assert (p["High"] >= p["Open"]).all()
            assert (p["Low"] <= p["Close"]).all()
            assert (p["Low"] <= p["Open"]).all()
            assert (p["Low"] > 0).all()
            assert (p["Volume"] >= 0).all()

    def test_zero_drift(self):
        """Mean return across many paths should be near zero."""
        paths = generate_random_walk_ohlcv(_real_ohlcv(500), n_paths=200, seed=123)
        mean_returns = []
        for p in paths:
            rets = p["Close"].pct_change().dropna()
            mean_returns.append(rets.mean())
        assert abs(np.mean(mean_returns)) < 0.002  # close to zero

    def test_vol_approximately_matches(self):
        real = _real_ohlcv(500)
        real_vol = real["Close"].pct_change().dropna().std()
        paths = generate_random_walk_ohlcv(real, n_paths=50)
        path_vols = [p["Close"].pct_change().dropna().std() for p in paths]
        mean_path_vol = np.mean(path_vols)
        assert abs(mean_path_vol - real_vol) / real_vol < 0.3  # within 30%

    def test_calendar_alignment(self):
        real = _real_ohlcv()
        paths = generate_random_walk_ohlcv(real, n_paths=3)
        for p in paths:
            assert (p.index == real.index).all()


class TestBlockBootstrapOHLCV:
    def test_output_count(self):
        paths = generate_block_bootstrap_ohlcv(_real_ohlcv(), n_paths=10, block_len=20)
        assert len(paths) == 10

    def test_ohlcv_structural_validity(self):
        paths = generate_block_bootstrap_ohlcv(_real_ohlcv(), n_paths=20, block_len=20)
        for p in paths:
            assert (p["High"] >= p["Close"]).all()
            assert (p["High"] >= p["Open"]).all()
            assert (p["Low"] <= p["Close"]).all()
            assert (p["Low"] <= p["Open"]).all()

    def test_different_block_len(self):
        real = _real_ohlcv(500)
        p10 = generate_block_bootstrap_ohlcv(real, n_paths=5, block_len=10)
        p50 = generate_block_bootstrap_ohlcv(real, n_paths=5, block_len=50)
        assert len(p10) == 5
        assert len(p50) == 5
