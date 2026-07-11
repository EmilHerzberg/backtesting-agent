"""ATS-1750/1751 — ResearchState and supporting models.

Central state object that flows through the research loop. Persisted
to DB between ticks so no state is lost on process restart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class ResearchPhase(StrEnum):
    """Current phase of the research loop (per AGENT-WORKFLOW-DESIGN.md Part 3)."""

    IDLE = "idle"
    GOAL_RECEIVED = "goal_received"
    PROPOSING = "proposing"           # STRATEGIST_THINKS
    DATA_PREPARING = "data_preparing"  # DATA_PREPARED
    EXECUTING = "executing"            # BACKTEST_RUN
    GATING = "gating"                  # GATES_EVALUATED
    CRITIQUING = "critiquing"          # CRITIC_REVIEW
    OOS_EVALUATING = "oos_evaluating"  # OOS_LOCKBOX
    DECIDING = "deciding"             # ORCHESTRATOR_DECIDES
    REPORTING = "reporting"            # REPORT
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass
class GoalBrief:
    """What the user wants to achieve."""

    goal_text: str
    asset_pool: list[str] = field(default_factory=list)
    strategy_families: list[str] = field(default_factory=list)
    max_runs: int = 200
    max_eur: float = 50.0
    max_seconds: int = 3600
    target_candidates: int = 3
    # C3/M50 — structured numeric criteria parsed from goal_text at run start. Empty = no parsed
    # criteria (fall back to a raw candidate count, e.g. tests that build GoalBrief directly).
    criteria: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Budget:
    """Research budget tracking."""

    max_runs: int = 200
    max_eur: float = 50.0
    max_seconds: int = 3600
    used_runs: int = 0
    used_eur: float = 0.0
    # M44: False once any LLM call used a model with UNKNOWN pricing. Then used_eur is a LOWER BOUND (the
    # unpriced calls contributed no €), so the HUD/report must show "cost unknown" rather than presenting
    # €0.0000 as if it were a genuinely-free run — and the € cap cannot be trusted to bind.
    cost_known: bool = True
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def remaining_runs(self) -> int:
        return max(0, self.max_runs - self.used_runs)

    def elapsed_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.started_at).total_seconds()

    def has_remaining(self) -> bool:
        if self.used_runs >= self.max_runs:
            return False
        if self.elapsed_seconds() >= self.max_seconds:
            return False
        return True

    def consume_run(self, cost_eur: float = 0.0) -> None:
        self.used_runs += 1
        self.used_eur += cost_eur


@dataclass
class Hypothesis:
    """A strategy hypothesis with economic rationale."""

    hypothesis_id: str
    author: str
    economic_rationale: str
    claimed_mechanism: str
    falsifiable_prediction: str
    proposed_template_id: str
    proposed_param_ranges: dict[str, Any] = field(default_factory=dict)
    prior_strength: str = "low"
    linked_specs: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DataSnapshot:
    """Content-addressed data snapshot for reproducibility (per spec Part 4)."""

    security_id: str
    window_start: str
    window_end: str
    provider: str = "yfinance"
    content_hash: str = ""
    n_bars: int = 0
    bias_flags: dict[str, Any] = field(default_factory=dict)
    data: Any = None  # The actual DataFrame — not serialized

    def __post_init__(self):
        if self.data is not None and not self.content_hash:
            import hashlib
            import pandas as pd
            if isinstance(self.data, pd.DataFrame) and not self.data.empty:
                raw = self.data.to_csv(None).encode("utf-8")
                self.content_hash = hashlib.sha256(raw).hexdigest()
                self.n_bars = len(self.data)


@dataclass
class RunArtifacts:
    """Executor output — typed container (per spec Part 4)."""

    run_id: str
    strategy_hash: str
    template_id: str
    params: dict[str, Any]
    security_id: str
    metrics: dict[str, Any] = field(default_factory=dict)
    returns: Any = None        # numpy array of per-bar returns
    equity_curve: list = field(default_factory=list)
    benchmark: dict[str, Any] = field(default_factory=dict)
    regime_analysis: dict[str, Any] = field(default_factory=dict)


@dataclass
class OOSResult:
    """OOS lockbox result. ``outcome`` is the control verdict (PASS/FAIL/UNEVALUATED). The confidence
    tier + Sharpe CI ride alongside as DISPLAY evidence (valconf spec §5.6, symmetric with the regime
    hold-out); they are empty/``None`` on the recover path where no fresh assessment is available."""

    strategy_hash: str
    lineage_id: str
    outcome: str  # "PASS" | "FAIL" | "UNEVALUATED"
    evaluated_at: str = ""
    confidence_tier: str = ""
    basis: str = ""            # "per_trade" | "per_bar" | "none" — how the OOS verdict was assessed
    ci_low: float | None = None
    ci_high: float | None = None
    ci_level: float | None = None


@dataclass
class FailureContext:
    """What went wrong in a previous attempt — fed back to Strategist."""

    strategy_hash: str
    template_id: str
    params: dict[str, Any]
    security_id: str
    failed_gate: str | None = None
    gate_details: dict[str, Any] = field(default_factory=dict)
    critic_notes: str | None = None
    failure_reason: str = ""
    hypothesis_id: str = ""   # -> research_hypotheses (Phase 1b)


@dataclass
class Candidate:
    """A strategy that survived gates + critic."""

    strategy_hash: str
    run_id: str
    template_id: str
    params: dict[str, Any]
    security_id: str
    sharpe_annual: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    n_trades: int = 0
    win_rate: float = 0.0       # P1-09 — so win-rate goals can be enforced (not silently skipped)
    profit_factor: float = 0.0  # P1-09 — so profit-factor goals can be enforced
    gate_report_summary: dict[str, Any] = field(default_factory=dict)
    critic_confidence: str = "low"
    critique: dict[str, Any] = field(default_factory=dict)  # full CriticReport (weaknesses/recommendation/reasoning)
    # ATSX-27: evidence drill-downs surfaced in the Candidate Dossier.
    regime_analysis: dict[str, Any] = field(default_factory=dict)
    benchmark: dict[str, Any] = field(default_factory=dict)
    equity_curve: list = field(default_factory=list)
    hypothesis_id: str = ""
    lineage_id: str = ""          # M47: the lineage at CREATION time (not the flush-time current lineage)
    # P1 Chunk C — regime firewall (empty for robustness runs).
    validation_status: str = ""   # "unvalidated" for regime at P1 (no within-regime hold-out until P2)
    confidence: str = ""          # F-13 unified confidence (weaker of sample-tier + overfit-validation)
    decay: dict[str, Any] = field(default_factory=dict)   # out-of-regime decay characterization (Chunk C2)
    weaknesses: list = field(default_factory=list)        # idea-surfacing — soft-failed quality gates (regime)
    holdout: dict[str, Any] = field(default_factory=dict)  # P2 — within-regime forward-slice hold-out result


def _candidate_metrics(c: "Candidate") -> dict[str, Any]:
    """A candidate's metrics as a dict keyed the way ``parse_criteria`` emits (C3/H30)."""
    return {
        "sharpe_annual": c.sharpe_annual,
        "total_return": c.total_return,
        "max_drawdown": c.max_drawdown,
        "n_trades": c.n_trades,
        "win_rate": c.win_rate,
        "profit_factor": c.profit_factor,
    }


@dataclass
class ResearchState:
    """Full state of an autonomous research session.

    Persisted between ticks. The research_loop reads and updates this.
    """

    goal: GoalBrief
    budget: Budget
    phase: ResearchPhase = ResearchPhase.IDLE
    current_asset: str = ""
    current_lineage_id: str = ""
    asset_queue: list[str] = field(default_factory=list)
    failure_context: list[FailureContext] = field(default_factory=list)
    all_failures: list[FailureContext] = field(default_factory=list)  # append-only full record (persistence); never cleared
    candidates: list[Candidate] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    consecutive_failures: int = 0
    consecutive_errors: int = 0                       # Director: strategist/data/exec exception streak
    consecutive_skips: int = 0                        # M48: Director skip-breaker — persistent-skip streak
    attempts_on_current_asset: int = 0                # Director: per-asset trial counter
    best_sharpe_on_asset: list[float] = field(default_factory=list)  # Director: running max Sharpe per trial
    total_iterations: int = 0
    error_message: str = ""
    stop_reason: str = ""                             # Director: final reason at loop exit (for the report, D-4)
    agent_mode: str = "rule_based"                    # W0: effective mode the run executed
    provider_type: str = ""                           # P2: effective LLM provider type (for the leakage marker)
    model_id: str = ""                                # H31: the MODEL that actually ran (leakage is per-model)
    mode: str = "robustness"                          # P1: robustness | regime
    window_start: str = ""                            # P1: effective backtest window (regime = user's; FULL window)
    window_end: str = ""
    train_end: str = ""                               # P2: regime select-on-train split ("" = no split / robustness)
    oos_results: list[OOSResult] = field(default_factory=list)
    lineage_nodes: list = field(default_factory=list)  # ATSX-26: serialized lineage tree
    holdout_eval_counts: dict[str, int] = field(default_factory=dict)  # H18: reuses of each (asset,slice) hold-out

    def _criteria_satisfying(self) -> list["Candidate"]:
        """Candidates that satisfy the user's parsed numeric criteria (C3). When no criteria were
        parsed (``goal.criteria`` empty), every candidate counts — preserving the old raw-count
        behaviour for callers that build a GoalBrief directly."""
        # M28: a regime idea that FAILED its within-regime hold-out must NOT count toward goal_met /
        # validated_count (regime mode force-disables OOS, so nothing else excluded it — three
        # regime_failed ideas would hit "goal_met" and stop the search). regime_validated / unvalidated
        # still count; only a hard regime_failed is dropped. In robustness mode validation_status is ""
        # so nothing is excluded.
        cands = [c for c in self.candidates if getattr(c, "validation_status", "") != "regime_failed"]
        crit = getattr(self.goal, "criteria", None) or []
        if not crit:
            return list(cands)
        from src.backend.ai.goals.criteria import candidate_meets_criteria

        return [c for c in cands if candidate_meets_criteria(_candidate_metrics(c), crit)]

    def goal_met(self) -> bool:
        """Whether enough candidates meet the user's criteria (C3 — not a raw candidate count)."""
        return len(self._criteria_satisfying()) >= self.goal.target_candidates

    def validated_count(self, oos_enabled: bool) -> int:
        """Candidates that count toward the goal: they must satisfy the user's criteria (C3) and,
        when OOS is on, have an OOS PASS."""
        satisfying = self._criteria_satisfying()
        if not oos_enabled:
            return len(satisfying)
        passed = {r.strategy_hash for r in self.oos_results if r.outcome == "PASS"}
        return sum(1 for c in satisfying if c.strategy_hash in passed)

    def advance_asset(self) -> bool:
        """Move to next asset in queue. Returns False if exhausted."""
        if not self.asset_queue:
            return False
        self.current_asset = self.asset_queue.pop(0)
        self.current_lineage_id = ""
        self.failure_context.clear()
        self.consecutive_failures = 0
        self.consecutive_errors = 0
        self.consecutive_skips = 0
        self.attempts_on_current_asset = 0
        self.best_sharpe_on_asset.clear()
        return True
