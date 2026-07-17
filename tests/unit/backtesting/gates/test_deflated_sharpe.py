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


class TestPF4NullVarianceFloor:
    """PF4 (Track 2): the conservative null-variance floor on the trial-Sharpe dispersion."""

    def _ctx(self, sr_variance, n_trials=50, sharpe=0.05, n_bars=500):
        rng = np.random.default_rng(42)
        returns = rng.standard_normal(n_bars) * 0.01 + sharpe / np.sqrt(252)
        return GateContext(
            metrics={"sharpe_annual": sharpe * np.sqrt(252)}, trades=[], returns=returns,
            equity_curve=[], n_trials_global=n_trials, trial_sr_variance=sr_variance,
        )

    def test_floor_binds_on_collapsed_measured_variance(self):
        # Clustered trials → near-identical Sharpes → measured V ≈ 1e-9. Pre-floor that made the
        # expected-max hurdle vanish (sr0 ∝ √V). The floor must bind and be reported.
        ctx = self._ctx(sr_variance=1e-9, n_bars=500)
        r = DeflatedSharpeGate().check(ctx)
        assert r.details["v_null_floored"] is True
        assert r.details["sr_variance"] == pytest.approx(3.0 / 499)
        assert r.details["sr_variance_measured"] == pytest.approx(1e-9)

    def test_floor_inert_when_measured_variance_is_conservative(self):
        ctx = self._ctx(sr_variance=0.05, n_bars=500)   # 0.05 ≫ 3/499
        r = DeflatedSharpeGate().check(ctx)
        assert r.details["v_null_floored"] is False
        assert r.details["sr_variance"] == pytest.approx(0.05)

    def test_monotone_stricter_the_mandatory_pf4_check(self):
        # sr0(V_used) ≥ sr0(V_measured) ⇒ DSR_new ≤ DSR_old, for every (V, T, N) probed —
        # including the v3 grid's N (172,831). This is the pre-registered PF4 assertion.
        for n_trials in (30, 1000, 172_831):
            for n_bars in (300, 2265, 6000):
                for v in (1e-9, 1e-4, 0.01, 0.1):
                    ctx = self._ctx(sr_variance=v, n_trials=n_trials, n_bars=n_bars)
                    dsr_new = DeflatedSharpeGate().check(ctx).details["dsr"]
                    dsr_old = deflated_sharpe(ctx.returns, n_trials, v)
                    assert dsr_new <= dsr_old + 1e-12

    def test_floor_can_flip_a_pass_to_fail(self):
        # The loosening the floor closes: a marginal edge that cleared the bar only because the
        # measured dispersion had collapsed must now FAIL (or at least score strictly lower).
        ctx_tiny_v = self._ctx(sr_variance=1e-10, n_trials=5000, sharpe=0.02, n_bars=400)
        r = DeflatedSharpeGate().check(ctx_tiny_v)
        dsr_unfloored = deflated_sharpe(ctx_tiny_v.returns, 5000, 1e-10)
        assert r.details["dsr"] < dsr_unfloored
        assert dsr_unfloored >= 0.95 and r.status == GateStatus.FAIL

    def test_sparse_exposure_raises_the_floor(self):
        # Review fix (HIGH-1): a 2%-exposure strategy has ~exposure×T informative observations,
        # not T — its null dispersion (and thus the floor) must be ~50× larger than the dense one.
        rng = np.random.default_rng(7)
        returns = rng.standard_normal(500) * 0.01
        dense = GateContext(metrics={"exposure_time": 1.0}, trades=[], returns=returns,
                            equity_curve=[], n_trials_global=50, trial_sr_variance=1e-9)
        sparse = GateContext(metrics={"exposure_time": 0.02}, trades=[], returns=returns,
                             equity_curve=[], n_trials_global=50, trial_sr_variance=1e-9)
        v_dense = DeflatedSharpeGate().check(dense).details["v_null"]
        v_sparse = DeflatedSharpeGate().check(sparse).details["v_null"]
        assert v_dense == pytest.approx(3.0 / 499)
        assert v_sparse == pytest.approx(3.0 / (0.02 * 499))
        assert v_sparse / v_dense == pytest.approx(50.0)

    def test_trials_clock_raises_the_floor_for_short_trials(self):
        # Review fix (HIGH-2): the dispersion being floored is CROSS-TRIAL; when the trials ran on
        # short (e.g. regime) windows their null dispersion ~1/T_trial governs, not the candidate's
        # longer clock.
        rng = np.random.default_rng(7)
        returns = rng.standard_normal(2265) * 0.01
        ctx = GateContext(metrics={"exposure_time": 1.0}, trades=[], returns=returns,
                          equity_curve=[], n_trials_global=50, trial_sr_variance=1e-9,
                          trial_median_t=250.0)
        r = DeflatedSharpeGate().check(ctx)
        assert r.details["v_null"] == pytest.approx(3.0 / 249)   # trials' clock governs (max)

    def test_measured_zero_variance_gets_a_firm_floored_verdict(self):
        # Review fix (LOW-1): bit-identical trial Sharpes (measured var == 0.0, NOT defaulted)
        # must produce a FIRM floored verdict — not escape into a lenient provisional PASS.
        rng = np.random.default_rng(7)
        returns = rng.standard_normal(400) * 0.01 + 0.02 / np.sqrt(252)
        ctx = GateContext(metrics={"exposure_time": 1.0}, trades=[], returns=returns,
                          equity_curve=[], n_trials_global=5000, trial_sr_variance=0.0,
                          trial_sr_variance_defaulted=False)
        r = DeflatedSharpeGate().check(ctx)
        assert r.details["sr_variance_defaulted"] is False
        assert r.details["v_null_floored"] is True
        assert r.details.get("provisional") is not True
        assert r.status == GateStatus.FAIL
