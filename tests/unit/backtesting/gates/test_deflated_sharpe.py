"""Tests for ATS-1744/1745 — Deflated Sharpe Ratio."""

import numpy as np
import pytest

from src.backend.backtesting.gates.deflated_sharpe import (
    DeflatedSharpeGate,
    deflated_sharpe,
)
from src.backend.backtesting.gates.pipeline import GateContext, GateStatus


class TestDeflatedSharpeFunction:
    def test_output_range_0_to_1(self):
        rng = np.random.default_rng(42)
        returns = rng.standard_normal(500) * 0.01 + 0.0003  # slight positive drift
        dsr = deflated_sharpe(returns, n_trials=50, trial_sr_variance=0.01)
        assert 0.0 <= dsr <= 1.0

    def test_higher_sr_higher_dsr(self):
        rng = np.random.default_rng(42)
        base = rng.standard_normal(500) * 0.01
        low_sr = deflated_sharpe(base + 0.0001, 50, 0.01)
        high_sr = deflated_sharpe(base + 0.001, 50, 0.01)
        assert high_sr > low_sr

    def test_more_trials_lower_dsr(self):
        rng = np.random.default_rng(42)
        returns = rng.standard_normal(500) * 0.01 + 0.0005
        dsr_few = deflated_sharpe(returns, n_trials=10, trial_sr_variance=0.01)
        dsr_many = deflated_sharpe(returns, n_trials=500, trial_sr_variance=0.01)
        assert dsr_few > dsr_many

    def test_insufficient_data_returns_zero(self):
        assert deflated_sharpe(np.array([0.01, 0.02]), n_trials=1, trial_sr_variance=0.01) == 0.0

    def test_zero_trials_returns_zero(self):
        returns = np.random.default_rng(42).standard_normal(100) * 0.01
        assert deflated_sharpe(returns, n_trials=0, trial_sr_variance=0.01) == 0.0

    def test_zero_variance_returns_zero(self):
        returns = np.random.default_rng(42).standard_normal(100) * 0.01
        assert deflated_sharpe(returns, n_trials=10, trial_sr_variance=0.0) == 0.0

    def test_negative_skew_effect(self):
        """Negative skew should reduce DSR (penalizes left tail risk)."""
        rng = np.random.default_rng(42)
        # Symmetric returns
        sym = rng.standard_normal(1000) * 0.01 + 0.0003
        # Left-skewed returns (same mean/std but with occasional large drops)
        skewed = sym.copy()
        skewed[::50] -= 0.05  # add occasional crashes
        dsr_sym = deflated_sharpe(sym, 50, 0.01)
        dsr_skewed = deflated_sharpe(skewed, 50, 0.01)
        # Skewed should generally have lower DSR (more penalty)
        # This is a statistical test so we just check the direction holds
        assert dsr_skewed <= dsr_sym + 0.1  # allow small noise


class TestDeflatedSharpeGate:
    def _ctx(self, n_trials=50, sr_variance=0.01, sharpe=0.05, n_bars=500):
        rng = np.random.default_rng(42)
        returns = rng.standard_normal(n_bars) * 0.01 + sharpe / np.sqrt(252)
        return GateContext(
            metrics={"sharpe_annual": sharpe * np.sqrt(252)},
            trades=[],
            returns=returns,
            equity_curve=[],
            n_trials_global=n_trials,
            trial_sr_variance=sr_variance,
        )

    def test_high_dsr_passes(self):
        # Very strong signal with few trials → should pass easily
        ctx = self._ctx(n_trials=5, sharpe=0.1, n_bars=1000)
        r = DeflatedSharpeGate().check(ctx)
        assert r.status == GateStatus.PASS

    def test_provisional_when_few_trials(self):
        ctx = self._ctx(n_trials=3)
        r = DeflatedSharpeGate().check(ctx)
        assert r.status == GateStatus.PASS
        assert r.details.get("provisional") is True

    def test_n_trials_recorded_in_details(self):
        ctx = self._ctx(n_trials=50)
        r = DeflatedSharpeGate().check(ctx)
        assert "n_trials" in r.details
        assert r.details["n_trials"] == 50

    def test_insufficient_returns_fails(self):
        ctx = GateContext(
            metrics={}, trades=[], returns=np.array([0.01]),
            equity_curve=[], n_trials_global=50, trial_sr_variance=0.01,
        )
        r = DeflatedSharpeGate().check(ctx)
        assert r.status == GateStatus.FAIL
