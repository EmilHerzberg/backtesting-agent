"""ATS-1724 — Gate ABC + GatePipeline with ordered evaluation and short-circuit.

Gates are ordered cheap → expensive by cost_rank. Hard failures short-circuit
the pipeline; soft failures are recorded but evaluation continues.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class GateSeverity(StrEnum):
    HARD = "hard"
    SOFT = "soft"


class GateStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUATED = "NOT_EVALUATED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class GateResult:
    """Result of evaluating a single gate."""

    gate_id: str
    gate_version: int
    cost_rank: int
    severity: GateSeverity
    status: GateStatus
    value: float | None = None
    threshold: float | None = None
    details: dict[str, Any] = field(default_factory=dict)
    evaluated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def passed(self) -> bool:
        return self.status == GateStatus.PASS

    @property
    def is_hard_fail(self) -> bool:
        return self.status == GateStatus.FAIL and self.severity == GateSeverity.HARD


@dataclass
class GateContext:
    """All data a gate needs to evaluate a run."""

    metrics: dict[str, Any]
    trades: list[dict[str, Any]]
    returns: Any  # np.ndarray of per-bar returns
    equity_curve: list[float]
    strategy_hash: str = ""
    template_id: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    security_id: str = ""
    bar_size: str = "1d"
    cost_profile_id: str = ""
    data_snapshot_hash: str = ""
    bias_flags: dict[str, bool] = field(default_factory=dict)
    benchmark: dict[str, Any] = field(default_factory=dict)
    n_trials_global: int = 0
    trial_sr_variance: float = 0.0
    trial_sr_variance_defaulted: bool = False  # M24: variance is a floored default, not a measurement
    run_strategy_fn: Any = None                # M22: re-run the candidate spec on arbitrary OHLCV (leakage canary)


class Gate(ABC):
    """Abstract base for a quality gate."""

    gate_id: str
    gate_version: int = 1
    cost_rank: int = 0
    severity: GateSeverity = GateSeverity.HARD

    @abstractmethod
    def check(self, ctx: GateContext) -> GateResult:
        """Evaluate this gate. Must return a GateResult."""
        ...

    def _pass(self, value: float | None = None, **details) -> GateResult:
        return GateResult(
            gate_id=self.gate_id,
            gate_version=self.gate_version,
            cost_rank=self.cost_rank,
            severity=self.severity,
            status=GateStatus.PASS,
            value=value,
            details=details,
        )

    def _fail(self, value: float | None = None, threshold: float | None = None, **details) -> GateResult:
        return GateResult(
            gate_id=self.gate_id,
            gate_version=self.gate_version,
            cost_rank=self.cost_rank,
            severity=self.severity,
            status=GateStatus.FAIL,
            value=value,
            threshold=threshold,
            details=details,
        )

    def _not_evaluated(self) -> GateResult:
        return GateResult(
            gate_id=self.gate_id,
            gate_version=self.gate_version,
            cost_rank=self.cost_rank,
            severity=self.severity,
            status=GateStatus.NOT_EVALUATED,
        )

    def _error(self, msg: str) -> GateResult:
        return GateResult(
            gate_id=self.gate_id,
            gate_version=self.gate_version,
            cost_rank=self.cost_rank,
            severity=self.severity,
            status=GateStatus.ERROR,
            details={"error": msg},
        )


@dataclass
class GateReport:
    """Aggregate result of running the full gate pipeline."""

    results: list[GateResult]
    passed: bool
    first_failed_gate: str | None = None   # M21: the first HARD FAIL only — the actual kill cause
    errored_gate: str | None = None        # M21: a HARD gate that raised (could not evaluate a blocker)

    @property
    def failed_hard(self) -> bool:
        return any(r.is_hard_fail for r in self.results)


class GatePipeline:
    """Ordered gate pipeline with short-circuit on hard failure."""

    def __init__(self, gates: list[Gate]) -> None:
        self.gates = sorted(gates, key=lambda g: g.cost_rank)

    def evaluate(self, ctx: GateContext) -> GateReport:
        """Run all gates in order. Short-circuit on hard fail."""
        results: list[GateResult] = []
        short_circuited = False
        first_failed: str | None = None
        errored_gate: str | None = None

        for gate in self.gates:
            if short_circuited:
                results.append(gate._not_evaluated())
                continue

            try:
                result = gate.check(ctx)
            except Exception as exc:
                result = gate._error(str(exc))

            results.append(result)

            # M21: only a HARD FAIL is the kill cause and short-circuits. A SOFT fail is a recorded
            # weakness — it must NOT be attributed as `first_failed_gate` (that misled the graveyard/
            # critic into blaming the first soft weakness). A HARD gate that ERRORed could not evaluate
            # a blocking check → treat as terminal (short-circuit) under a distinct `errored_gate`.
            if result.is_hard_fail:
                short_circuited = True
                if first_failed is None:
                    first_failed = result.gate_id
            elif result.status == GateStatus.ERROR and result.severity == GateSeverity.HARD:
                short_circuited = True
                if errored_gate is None:
                    errored_gate = result.gate_id

        passed = all(
            r.status in (GateStatus.PASS, GateStatus.NOT_EVALUATED)
            or r.severity == GateSeverity.SOFT
            for r in results
        )

        return GateReport(
            results=results,
            passed=passed,
            first_failed_gate=first_failed,
            errored_gate=errored_gate,
        )
