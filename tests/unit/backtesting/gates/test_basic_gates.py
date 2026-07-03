"""Tests for ATS-1727-1734 — basic gates + benchmark-relative gate."""

import numpy as np
import pytest

from src.backend.backtesting.gates.basic_gates import (
    BenchmarkRelativeGate,
    DataIntegrityGate,
    MinimumActivityGate,
    PerformanceFloorGate,
    ProviderCapabilityGate,
    SpecValidationGate,
)
from src.backend.backtesting.gates.pipeline import GateContext, GateStatus


def _ctx(**overrides):
    defaults = dict(
        metrics={"n_trades": 100, "sharpe_annual": 1.0, "total_return": 0.2,
                 "max_drawdown": -0.15, "exposure_time": 0.5, "commission": 0.001},
        trades=[],
        returns=np.random.default_rng(42).standard_normal(252) * 0.01,
        equity_curve=[],
        strategy_hash="a" * 64,
        template_id="sma_crossover",
    )
    defaults.update(overrides)
    return GateContext(**defaults)


class TestSpecValidationGate:
    def test_valid_spec_passes(self):
        r = SpecValidationGate().check(_ctx())
        assert r.status == GateStatus.PASS

    def test_empty_strategy_hash_fails(self):
        r = SpecValidationGate().check(_ctx(strategy_hash=""))
        assert r.status == GateStatus.FAIL

    def test_empty_template_id_fails(self):
        r = SpecValidationGate().check(_ctx(template_id=""))
        assert r.status == GateStatus.FAIL


class TestProviderCapabilityGate:
    def test_no_bias_flags_passes(self):
        r = ProviderCapabilityGate().check(_ctx(bias_flags={}))
        assert r.status == GateStatus.PASS

    def test_yfinance_fails(self):
        r = ProviderCapabilityGate().check(_ctx(
            bias_flags={"survivorship_bias": True, "research_conclusion_allowed": False}
        ))
        assert r.status == GateStatus.FAIL

    def test_eodhd_passes(self):
        r = ProviderCapabilityGate().check(_ctx(
            bias_flags={"survivorship_bias": False, "research_conclusion_allowed": True}
        ))
        assert r.status == GateStatus.PASS


class TestDataIntegrityGate:
    def test_valid_data_passes(self):
        r = DataIntegrityGate().check(_ctx())
        assert r.status == GateStatus.PASS

    def test_huge_return_jump_fails(self):
        returns = np.zeros(100)
        returns[50] = 0.8  # 80% single-bar jump
        r = DataIntegrityGate().check(_ctx(returns=returns))
        assert r.status == GateStatus.FAIL


class TestMinimumActivityGate:
    def test_50_trades_passes(self):
        r = MinimumActivityGate().check(_ctx(metrics={"n_trades": 50, "exposure_time": 0.5}))
        assert r.status == GateStatus.PASS

    def test_49_trades_fails(self):
        r = MinimumActivityGate().check(_ctx(metrics={"n_trades": 49, "exposure_time": 0.5}))
        assert r.status == GateStatus.FAIL

    def test_zero_exposure_fails(self):
        r = MinimumActivityGate().check(_ctx(metrics={"n_trades": 100, "exposure_time": 0.0}))
        assert r.status == GateStatus.FAIL

    def test_full_exposure_fails(self):
        r = MinimumActivityGate().check(_ctx(metrics={"n_trades": 100, "exposure_time": 0.99}))
        assert r.status == GateStatus.FAIL


def _smart_gate(min_trades=5, activity_t=1.65, mode="kill"):
    g = MinimumActivityGate()
    g.MIN_TRADES = min_trades
    g.ACTIVITY_T = activity_t
    g.adaptive_mode = mode
    return g


def test_sibling_gate_details_are_flat():
    # M1: sibling gates spread details (flat), not nested under a "details" key.
    r = SpecValidationGate().check(_ctx(strategy_hash=""))
    assert r.details.get("reason") == "strategy_hash is empty"
    assert "details" not in r.details


class TestSmartActivityGate:
    """SMART-ACTIVITY-GATE-SPEC: floor + per-trade edge t-stat + tier + adaptive_mode."""

    def test_floor_kills_few_but_stellar(self):
        # The overfit loophole: 3 trades all huge — still killed by the floor (SAS-2).
        r = _smart_gate().check(_ctx(metrics={"n_trades": 3, "exposure_time": 0.5,
                                              "trade_returns": [0.5, 0.4, 0.6]}))
        assert r.status == GateStatus.FAIL
        assert r.details["tier"] == "insufficient"

    def test_adaptive_pass_strong_edge(self):
        tr = [0.03, 0.02, 0.025, 0.015, 0.02, 0.03, 0.01, 0.025, 0.02, 0.015]  # consistent positive
        r = _smart_gate().check(_ctx(metrics={"n_trades": len(tr), "exposure_time": 0.5, "trade_returns": tr}))
        assert r.status == GateStatus.PASS
        assert r.details["tier"] == "adequate"

    def test_adaptive_fail_thin_edge(self):
        tr = [0.05, -0.04, 0.03, -0.05, 0.04, -0.03, 0.02, -0.04, 0.05, -0.03]  # noisy, ~0 mean
        r = _smart_gate().check(_ctx(metrics={"n_trades": len(tr), "exposure_time": 0.5, "trade_returns": tr}))
        assert r.status == GateStatus.FAIL
        assert r.details["tier"] == "thin"

    def test_research_no_trade_returns_flags_plumbing_inconsistency(self):
        # S1/SAS-5: ACTIVITY_T set (research) but no trade_returns despite n>=floor → plumbing inconsistency,
        # passes but low_confidence (NOT a clean "adequate"/floor-only). Back-compat floor-only (ACTIVITY_T=None)
        # is covered by test_default_gate_floor_only_ignores_thin_returns.
        r = _smart_gate().check(_ctx(metrics={"n_trades": 10, "exposure_time": 0.5}))
        assert r.status == GateStatus.PASS
        assert r.details.get("note") == "plumbing_inconsistency"
        assert r.details.get("low_confidence") is True

    def test_adaptive_mode_label_passes_thin_as_low_confidence(self):
        tr = [0.05, -0.04, 0.03, -0.05, 0.04, -0.03, 0.02, -0.04, 0.05, -0.03]  # thin
        r = _smart_gate(mode="label").check(_ctx(metrics={"n_trades": len(tr), "exposure_time": 0.5, "trade_returns": tr}))
        assert r.status == GateStatus.PASS
        assert r.details["tier"] == "thin"
        assert r.details["low_confidence"] is True

    def test_rigor_binds(self):
        tr = [0.02, 0.01, 0.015, -0.005, 0.02, 0.01, 0.005, 0.015, 0.01, -0.005]  # moderate edge
        ctx = _ctx(metrics={"n_trades": len(tr), "exposure_time": 0.5, "trade_returns": tr})
        assert _smart_gate(activity_t=1.0).check(ctx).status == GateStatus.PASS
        assert _smart_gate(activity_t=8.0).check(ctx).status == GateStatus.FAIL

    def test_default_gate_floor_only_ignores_thin_returns(self):
        # Non-research caller (ACTIVITY_T=None) → floor-only even with thin returns (back-compat, SAS-2).
        g = MinimumActivityGate()
        r = g.check(_ctx(metrics={"n_trades": 60, "exposure_time": 0.5,
                                  "trade_returns": [0.05, -0.04, 0.03, -0.05]}))
        assert r.status == GateStatus.PASS
        assert r.details.get("note") == "floor-only"


class TestPerformanceFloorGate:
    def test_good_sharpe_passes(self):
        r = PerformanceFloorGate().check(_ctx(metrics={"sharpe_annual": 0.6, "total_return": 0.1}))
        assert r.status == GateStatus.PASS

    def test_low_sharpe_fails(self):
        r = PerformanceFloorGate().check(_ctx(metrics={"sharpe_annual": 0.3, "total_return": 0.1}))
        assert r.status == GateStatus.FAIL

    def test_negative_return_fails(self):
        r = PerformanceFloorGate().check(_ctx(metrics={"sharpe_annual": 0.8, "total_return": -0.05}))
        assert r.status == GateStatus.FAIL

    def test_sharpe_exactly_05_passes(self):
        r = PerformanceFloorGate().check(_ctx(metrics={"sharpe_annual": 0.5, "total_return": 0.01}))
        assert r.status == GateStatus.PASS


class TestBenchmarkRelativeGate:
    def test_better_sharpe_passes(self):
        r = BenchmarkRelativeGate().check(_ctx(
            metrics={"sharpe_annual": 1.2, "total_return": 0.20, "max_drawdown": -0.15},
            benchmark={"buy_hold_sharpe": 0.8, "buy_hold_return": 0.15, "buy_hold_max_drawdown": -0.20},
        ))
        assert r.status == GateStatus.PASS

    def test_worse_on_all_dimensions_fails(self):
        r = BenchmarkRelativeGate().check(_ctx(
            metrics={"sharpe_annual": 0.4, "total_return": 0.05, "max_drawdown": -0.30},
            benchmark={"buy_hold_sharpe": 0.8, "buy_hold_return": 0.15, "buy_hold_max_drawdown": -0.10},
        ))
        assert r.status == GateStatus.FAIL

    def test_positive_excess_return_passes(self):
        r = BenchmarkRelativeGate().check(_ctx(
            metrics={"sharpe_annual": 0.6, "total_return": 0.25, "max_drawdown": -0.20},
            benchmark={"buy_hold_sharpe": 0.7, "buy_hold_return": 0.20, "buy_hold_max_drawdown": -0.15},
        ))
        assert r.status == GateStatus.PASS  # path_c: excess return > 0

    def test_no_benchmark_passes(self):
        r = BenchmarkRelativeGate().check(_ctx(benchmark={}))
        assert r.status == GateStatus.PASS
