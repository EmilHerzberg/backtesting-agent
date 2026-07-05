"""Tests for ATS-1723/1724/1725 — GatePipeline + Gate ABC."""

import numpy as np
import pytest

from src.backend.backtesting.gates.pipeline import (
    Gate,
    GateContext,
    GatePipeline,
    GateResult,
    GateSeverity,
    GateStatus,
)


def _make_ctx(**overrides):
    defaults = dict(
        metrics={"n_trades": 100, "sharpe_annual": 1.0, "total_return": 0.2,
                 "max_drawdown": -0.15, "exposure_time": 0.5, "commission": 0.001},
        trades=[],
        returns=np.random.default_rng(42).standard_normal(252) * 0.01,
        equity_curve=[10000 + i * 10 for i in range(252)],
        strategy_hash="a" * 64,
        template_id="sma_crossover",
    )
    defaults.update(overrides)
    return GateContext(**defaults)


class _PassGate(Gate):
    gate_id = "always_pass"
    cost_rank = 1

    def check(self, ctx):
        return self._pass(value=1.0)


class _FailHardGate(Gate):
    gate_id = "always_fail_hard"
    cost_rank = 2
    severity = GateSeverity.HARD

    def check(self, ctx):
        return self._fail(value=0.0, threshold=1.0, reason="forced fail")


class _FailSoftGate(Gate):
    gate_id = "always_fail_soft"
    cost_rank = 3
    severity = GateSeverity.SOFT

    def check(self, ctx):
        return self._fail(value=0.0, threshold=1.0)


class _ExpensiveGate(Gate):
    gate_id = "expensive"
    cost_rank = 99

    def check(self, ctx):
        return self._pass(value=99.0)


class TestGatePipeline:
    def test_empty_pipeline_passes(self):
        pipeline = GatePipeline([])
        report = pipeline.evaluate(_make_ctx())
        assert report.passed is True
        assert report.results == []

    def test_single_hard_gate_pass(self):
        pipeline = GatePipeline([_PassGate()])
        report = pipeline.evaluate(_make_ctx())
        assert report.passed is True
        assert len(report.results) == 1
        assert report.results[0].status == GateStatus.PASS

    def test_single_hard_gate_fail(self):
        pipeline = GatePipeline([_FailHardGate()])
        report = pipeline.evaluate(_make_ctx())
        assert report.passed is False
        assert report.first_failed_gate == "always_fail_hard"

    def test_hard_fail_short_circuits(self):
        pipeline = GatePipeline([_PassGate(), _FailHardGate(), _ExpensiveGate()])
        report = pipeline.evaluate(_make_ctx())
        assert report.passed is False
        assert report.results[0].status == GateStatus.PASS
        assert report.results[1].status == GateStatus.FAIL
        assert report.results[2].status == GateStatus.NOT_EVALUATED

    def test_soft_fail_does_not_short_circuit(self):
        pipeline = GatePipeline([_PassGate(), _FailSoftGate(), _ExpensiveGate()])
        report = pipeline.evaluate(_make_ctx())
        assert report.passed is True  # soft fail doesn't block
        assert report.results[1].status == GateStatus.FAIL
        assert report.results[2].status == GateStatus.PASS  # expensive ran

    def test_gate_order_by_cost_rank(self):
        gates = [_ExpensiveGate(), _PassGate(), _FailSoftGate()]
        pipeline = GatePipeline(gates)
        report = pipeline.evaluate(_make_ctx())
        ranks = [r.cost_rank for r in report.results]
        assert ranks == sorted(ranks)

    def test_all_results_recorded_including_not_evaluated(self):
        pipeline = GatePipeline([_FailHardGate(), _PassGate(), _ExpensiveGate()])
        report = pipeline.evaluate(_make_ctx())
        assert len(report.results) == 3
        statuses = [r.status for r in report.results]
        assert GateStatus.NOT_EVALUATED in statuses

    def test_gate_report_first_failed_gate(self):
        pipeline = GatePipeline([_PassGate(), _FailHardGate()])
        report = pipeline.evaluate(_make_ctx())
        assert report.first_failed_gate == "always_fail_hard"

    def test_exception_in_gate_produces_error(self):
        class _BrokenGate(Gate):
            gate_id = "broken"
            cost_rank = 1
            def check(self, ctx):
                raise RuntimeError("boom")

        pipeline = GatePipeline([_BrokenGate()])
        report = pipeline.evaluate(_make_ctx())
        assert report.results[0].status == GateStatus.ERROR
        assert "boom" in report.results[0].details.get("error", "")


class _FailSoftEarlyGate(Gate):
    gate_id = "soft_early"
    cost_rank = 1
    severity = GateSeverity.SOFT

    def check(self, ctx):
        return self._fail(reason="soft weakness")


class _ErrorHardGate(Gate):
    gate_id = "error_hard"
    cost_rank = 1
    severity = GateSeverity.HARD

    def check(self, ctx):
        raise RuntimeError("could not evaluate")


class TestKillCauseAttribution:
    """M21 — the kill cause is the HARD fail, soft weaknesses are not blamed, hard ERROR is terminal."""

    @pytest.mark.finding("M21")
    def test_soft_fail_before_hard_fail_is_not_the_kill_cause(self):
        # soft weakness (cost_rank 1) runs before the hard kill (cost_rank 2): the cause is the HARD
        # gate, not the first soft weakness (which the pre-fix code misattributed).
        report = GatePipeline([_FailSoftEarlyGate(), _FailHardGate()]).evaluate(_make_ctx())
        assert report.first_failed_gate == "always_fail_hard"
        assert report.passed is False

    @pytest.mark.finding("M21")
    def test_soft_fail_alone_has_no_kill_cause(self):
        report = GatePipeline([_FailSoftEarlyGate(), _PassGate()]).evaluate(_make_ctx())
        assert report.first_failed_gate is None      # a soft weakness is not a kill cause
        assert report.passed is True

    @pytest.mark.finding("M21")
    def test_hard_gate_error_is_terminal_with_distinct_field(self):
        report = GatePipeline([_ErrorHardGate(), _ExpensiveGate()]).evaluate(_make_ctx())
        assert report.errored_gate == "error_hard"   # a hard gate that raised couldn't evaluate a blocker
        assert report.first_failed_gate is None       # it's an ERROR, distinct from a FAIL
        assert report.passed is False
        downstream = next(r for r in report.results if r.gate_id == "expensive")
        assert downstream.status == GateStatus.NOT_EVALUATED  # short-circuited
