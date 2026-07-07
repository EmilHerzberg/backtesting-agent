"""ATS-1786 — API endpoints for the autonomous research loop.

ATSX-07 (A-0): mounted at /api/research (the legacy per-stock report
router moved to /api/stock-reports).
ATSX-08 (A-1): start a run as a background task + scope preview.

Run state is held in-memory in ``_runs`` (RunRecord). ATSX-10 (A-2) will
back this with the research_* tables so it survives a restart.

Heavy engine imports (numpy/scipy/gates via run_research) are done lazily
inside the handlers so simply mounting this router can never break app boot.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from src.backend.auth.dependencies import get_current_user_id
from src.backend.ai.research import persistence
from src.backend.ai.leakage import RISK, UNVALIDATED, model_leakage, provider_leakage


def _run_leakage(provider_type: str, model_id: str = "") -> str:
    """H31: a run's leakage badge = the classification of the MODEL that actually drove selection
    (per-model), falling back to the provider summary only when the model is unknown (rule_based /
    legacy rows). Provider granularity alone was over-optimistic — a provider that ships one validated
    model badged every run on it clean, even a run that used an unvalidated sibling model.

    M56: the provider fallback itself is optimistic (``provider_leakage`` returns ``mechanism_only`` if
    ANY sibling model is validated). For a run whose actual model we DON'T know (empty ``model_id`` —
    legacy P2..H31 rows, or every such row after the ``model_id DEFAULT ''`` migration) we must never
    UPGRADE it to ``mechanism_only`` on the strength of a validated sibling it may not have used. Surface
    a known provider-level ``risk`` (conservative — don't hide risk), but downgrade an optimistic
    ``mechanism_only`` to ``unvalidated``."""
    if model_id:
        return model_leakage(model_id)
    summary = provider_leakage(provider_type)
    return summary if summary == RISK else UNVALIDATED

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/research", tags=["research"])


# ── Request models ────────────────────────────────────────────────────

class StartRunRequest(BaseModel):
    goal_text: str
    asset_pool: list[str] = []
    strategy_families: list[str] = []
    # M52: budgets are bounded up front (were unvalidated → a negative/zero cap was silently accepted and
    # coerced late). max_eur may be 0 (= "no € cap"); the rest must be positive.
    max_runs: int = Field(100, ge=1)
    max_eur: float = Field(50.0, ge=0.0)
    max_seconds: int = Field(3600, ge=1)
    target_candidates: int = Field(3, ge=1)
    # F1/F2/F6 — start-options exposed to the UI
    rigor: str = "standard"          # exploratory | standard | strict
    enable_oos: bool = True          # D9/H5: OOS on by default (a run with it off cannot be badged "strong")
    commission_pct: float = 0.001    # H29/D8: realistic transaction cost (same model as the CLI) —
    spread_bps: float = 5.0          # effective per-side = commission + half-spread + slippage
    slippage_bps: float = 2.0
    seed: int = 42
    # W0 — agent mode + LLM provider (inert until W1; rule_based = no LLM, €0)
    agent_mode: str = "rule_based"   # rule_based | ai_assisted | full_ai
    provider: str | None = None      # LLM provider name (registry)
    model: str | None = None         # model id
    # P1 — regime mode + window (robustness ignores the window, keeps the fixed default)
    mode: str = "robustness"         # robustness | regime
    window_start: str | None = None  # regime window start (YYYY-MM-DD)
    window_end: str | None = None    # regime window end

    @model_validator(mode="after")
    def _validate_regime_window(self):
        # P1 fixes M1/S1/S2: the regime window is an atomic, validated pair; robustness ignores it.
        import datetime as _dt
        # M52: reject unknown enums up front instead of silently coercing them (agent_mode was a free string
        # — any non-rule_based value resolved an LLM + set a leakage marker; rigor silently fell back to
        # standard). Fail fast with a clear message so the recorded spec matches what actually ran.
        if self.agent_mode not in ("rule_based", "ai_assisted", "full_ai"):
            raise ValueError("agent_mode must be 'rule_based', 'ai_assisted', or 'full_ai'")
        if self.rigor not in ("exploratory", "standard", "strict"):
            raise ValueError("rigor must be 'exploratory', 'standard', or 'strict'")
        if self.mode not in ("robustness", "regime"):
            raise ValueError("mode must be 'robustness' or 'regime'")
        if self.mode == "regime":
            if not (self.window_start and self.window_end):
                raise ValueError("regime mode requires both window_start and window_end (YYYY-MM-DD)")
            for d in (self.window_start, self.window_end):
                try:
                    _dt.date.fromisoformat(d)
                except ValueError:
                    raise ValueError(f"invalid date {d!r}; expected YYYY-MM-DD")
            if self.window_start >= self.window_end:
                raise ValueError("window_start must be before window_end")
        return self


# ── Response models ───────────────────────────────────────────────────

class RunCreatedResponse(BaseModel):
    goal_id: str
    status: str
    goal_text: str
    asset_pool: list[str]
    strategy_families: list[str]
    max_runs: int
    target_candidates: int


class ScopePreviewResponse(BaseModel):
    interpreted: dict[str, list[str]]
    cost: dict[str, Any]
    source_annotations: dict[str, str]
    mode: str = "rule_based"
    notes: str = ""


class ResearchStateResponse(BaseModel):
    phase: str
    goal_text: str = ""
    current_asset: str
    total_iterations: int
    candidates_count: int
    budget_used_runs: int
    budget_remaining_runs: int
    failure_count: int
    error_message: str = ""
    # A-3 (ATSX-11): run-level lifecycle + budget/time/lineage for the HUD.
    status: str = "running"
    used_eur: float = 0.0
    # M44: False when the run used any model with unknown pricing → used_eur is a lower bound, not a true
    # €0. The HUD should render "cost unknown" instead of "€0.0000" (which would read as genuinely free).
    cost_known: bool = True
    agent_mode: str = "rule_based"   # W4 (F-5): the effective mode the run executed
    mode: str = "robustness"         # P1: robustness | regime
    window_start: str = ""           # P1: effective backtest window
    window_end: str = ""
    # M31: the select-on-train split. In regime mode the candidate metrics are measured on [window_start,
    # train_end] (the train slice); the hold-out is [train_end, window_end]. Exposing it lets the UI label
    # the metrics with the slice they were actually computed on, not the full window. "" = no split.
    train_end: str = ""
    provider_type: str = ""          # P2: effective LLM provider type
    model_id: str = ""               # H31: the model that actually ran
    leakage: str = "unvalidated"     # P2 (F-11)/H31: the run's per-MODEL leakage state
    max_seconds: int = 0
    started_at: str | None = None
    current_lineage: str = ""


class CandidateResponse(BaseModel):
    strategy_hash: str
    run_id: str
    template_id: str
    security_id: str
    sharpe_annual: float
    total_return: float
    max_drawdown: float
    n_trades: int
    critic_confidence: str
    oos_outcome: str = "PENDING"  # A-6: PASS|FAIL|PENDING — the trust badge
    validation_status: str = ""   # P1 Chunk C — regime firewall ("unvalidated" for regime, "" robustness)
    confidence: str = ""          # F-13 unified confidence (regime)
    decay: dict[str, Any] = {}    # C2 — out-of-regime decay characterization (regime)
    weaknesses: list = []         # idea-surfacing — soft-failed quality gates (regime)
    holdout: dict[str, Any] = {}  # P2 — within-regime forward-slice hold-out result (regime)
    quality: dict[str, Any] = {}  # confidence-surfacing — statistical-quality summary (both modes)


class HypothesisResponse(BaseModel):
    hypothesis_id: str
    economic_rationale: str
    claimed_mechanism: str
    falsifiable_prediction: str
    prior_strength: str
    proposed_template_id: str


class CritiqueResponse(BaseModel):
    confidence: str
    recommendation: str = ""
    weaknesses: list[str] = []
    prose: str = ""  # the critic's reasoning


class OOSResponse(BaseModel):
    outcome: str  # PASS | FAIL | PENDING
    lineage_id: str = ""
    evaluated_at: str = ""


class FailureItem(BaseModel):
    strategy_hash: str
    template_id: str
    security_id: str
    failed_gate: str
    failure_reason: str
    critic_notes: str = ""
    gate_details: dict[str, Any] = {}
    hypothesis_id: str = ""              # -> the proposal (per-attempt record)
    params: dict[str, Any] = {}          # the actual chosen params


class GraveyardResponse(BaseModel):
    total: int
    by_cause: dict[str, int]  # cause of death -> count
    failures: list[FailureItem]


class ReportSectionResponse(BaseModel):
    key: str
    title: str
    numeric_fields: dict[str, Any] = {}
    narrative: str = ""


class ReportResponse(BaseModel):
    status: str
    goal_text: str = ""
    available: bool  # False while the run hasn't produced a report yet
    sections: list[ReportSectionResponse] = []


class CoverageCell(BaseModel):
    """One asset×strategy cell of the Director coverage map (ATSX-26)."""

    security_id: str
    template_id: str
    survived: int = 0
    died: int = 0
    total: int = 0


class RegistryStatsResponse(BaseModel):
    audit_trial_count: int
    valid_research_trial_count: int
    candidates_found: int
    # A-10 Director-dashboard aggregates (honest, from research_* tables):
    total_runs: int = 0
    runs_by_status: dict[str, int] = {}
    failures_recorded: int = 0
    oos_passed: int = 0
    oos_failed: int = 0
    # ATSX-26: asset×strategy coverage (which combos were explored + how they fared)
    coverage: list[CoverageCell] = []


class RunListItem(BaseModel):
    goal_id: str
    goal_text: str
    status: str
    phase: str
    used_runs: int
    max_runs: int
    candidates_count: int
    failure_count: int
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    provider_type: str = ""          # P2
    model_id: str = ""               # H31: the model that actually ran
    leakage: str = "unvalidated"     # P2 (F-11)/H31: per-MODEL leakage state


class GateResultResponse(BaseModel):
    gate_id: str
    status: str
    value: float | None = None
    threshold: float | None = None
    details: dict[str, Any] = {}


class EventResponse(BaseModel):
    id: int
    ts: str
    kind: str            # normalized wireframe taxonomy
    raw_kind: str        # original loop event kind
    phase: str = ""
    lineage_id: str = ""
    title: str = ""
    detail: dict[str, Any] = {}
    strategy_hash: str | None = None


# Map the loop's raw event kinds to the wireframe activity taxonomy
# (propose|data|execute|gate_pass|gate_fail|critique|oos|decide|report).
_EVENT_TAXONOMY = {
    "goal_received": "goal",
    "loop_started": "data",
    "proposing": "propose",
    "data_prepared": "data",
    "execute": "execute",
    "critique": "critique",
    "oos_result": "oos",
    "candidate_found": "decide",
    "orchestrator_decision": "decide",
    "reporting": "report",
    "loop_finished": "report",
}


def _normalize_kind(raw_kind: str, detail: dict[str, Any]) -> str:
    if raw_kind == "gate_result":
        return "gate_pass" if detail.get("passed") else "gate_fail"
    return _EVENT_TAXONOMY.get(raw_kind, raw_kind)


def _event_title(raw_kind: str, detail: dict[str, Any]) -> str:
    d = detail or {}
    sh = (d.get("strategy_hash") or "")[:8]
    if raw_kind == "gate_result":
        if d.get("passed"):
            return "All gates passed"
        g = d.get("failed_gate", "?")
        if d.get("value") is not None and d.get("threshold") is not None:
            return f"Gate failed: {g} (value {d['value']} vs threshold {d['threshold']})"
        return f"Gate failed: {g}"
    if raw_kind == "proposing":
        return f"Proposing strategy for {d.get('asset', '?')} (iteration {d.get('iteration', '?')})"
    if raw_kind == "data_prepared":
        return f"Data prepared for {d.get('security_id', '?')} ({d.get('n_bars', '?')} bars)"
    if raw_kind == "execute":
        return f"Backtest {sh}: Sharpe {d.get('sharpe_annual', '?')}, {d.get('n_trades', '?')} trades"
    if raw_kind == "critique":
        return f"Critic recommendation: {d.get('recommendation', '?')}"
    if raw_kind == "oos_result":
        return f"OOS {d.get('outcome', '?')} for {sh}"
    if raw_kind == "candidate_found":
        return f"Candidate found: {sh}"
    if raw_kind == "orchestrator_decision":
        return f"Director decision: {d.get('decision', '?')}"
    if raw_kind == "reporting":
        return f"Generating report ({d.get('candidates', '?')} candidates)"
    if raw_kind == "loop_started":
        return f"Started on {d.get('asset', '?')}"
    if raw_kind == "loop_finished":
        return f"Run finished ({d.get('phase', '?')})"
    if raw_kind == "goal_received":
        return f"Goal received: {d.get('goal', '?')}"
    return raw_kind


# ── In-memory run registry (ATSX-10 / A-2 will persist to DB) ─────────

@dataclass
class RunRecord:
    """One research run's live state + lifecycle status."""

    goal_id: str
    user_id: int
    goal_text: str = ""
    state: Any = None                       # ResearchState — mutated in place by the loop
    status: str = "running"                # running | paused | completed | stopped | failed | interrupted
    control: str = "run"                   # run | pause | stop | stop_report (A-9 cooperative control)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    report: Any = None
    error: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    task: Any = None                        # asyncio.Task
    persisted_events: int = 0               # cursor: how many events flushed to DB
    persisted_candidates: int = 0
    persisted_failures: int = 0
    persisted_hypotheses: int = 0
    persisted_lineage_count: int = 0


_runs: dict[str, RunRecord] = {}


def register_state(goal_id: str, state: Any, user_id: int = 0) -> None:
    """Register/replace the live state for a run (test + internal helper)."""
    rec = _runs.get(goal_id)
    if rec is None:
        _runs[goal_id] = RunRecord(goal_id=goal_id, user_id=user_id, state=state)
    else:
        rec.state = state


def unregister_state(goal_id: str) -> None:
    _runs.pop(goal_id, None)


def _owned_run(goal_id: str, user_id: int) -> RunRecord:
    """Fetch a run, enforcing per-user ownership (D5). 404 if missing or not owned."""
    rec = _runs.get(goal_id)
    if rec is None or rec.user_id != user_id:
        raise HTTPException(404, f"No research run {goal_id}")
    return rec


# ── Background run driver ─────────────────────────────────────────────

async def _run_and_track(rec: RunRecord, req: StartRunRequest) -> None:
    """Run the full pipeline as a background task, tracking lifecycle status.

    A periodic flusher (_sync_loop) mirrors the live state to the DB so the
    run survives a process restart (ATSX-10 / A-2).
    """
    # Lazy import: pulls in numpy/scipy/gates only when a run actually starts.
    from src.backend.ai.research.run import run_research

    def _on_start(state: Any) -> None:
        rec.state = state

    def _on_event(kind: str, payload: dict[str, Any]) -> None:
        rec.events.append({"kind": kind, "payload": payload})

    sync_task = asyncio.create_task(_sync_loop(rec))
    try:
        rec.report = await run_research(
            goal=req.goal_text,
            assets=req.asset_pool or None,
            max_runs=req.max_runs,
            max_eur=req.max_eur,
            max_seconds=req.max_seconds,
            target_candidates=req.target_candidates,
            strategy_families=req.strategy_families or None,
            rigor=req.rigor,
            enable_oos=req.enable_oos,
            commission_pct=req.commission_pct,
            spread_bps=req.spread_bps,
            slippage_bps=req.slippage_bps,
            seed=req.seed,
            agent_mode=req.agent_mode,
            provider=req.provider,
            model=req.model,
            mode=req.mode,
            window_start=req.window_start,
            window_end=req.window_end,
            on_start=_on_start,
            on_event=_on_event,
            control=lambda: rec.control,
        )
        # A-9: a plain Stop ends as "stopped"; natural end or Stop&report → "completed".
        rec.status = "stopped" if rec.control == "stop" else "completed"
    except asyncio.CancelledError:
        rec.status = "interrupted"
        raise
    except Exception as exc:  # noqa: BLE001 — surface any failure as run status
        rec.status = "failed"
        rec.error = str(exc)
        if rec.state is not None:
            rec.state.error_message = str(exc)
        logger.exception("Research run %s failed", rec.goal_id)
    finally:
        rec.finished_at = datetime.now(timezone.utc)
        sync_task.cancel()
        try:
            await sync_task
        except asyncio.CancelledError:
            pass
        await persistence.persist_snapshot(rec)  # final flush of terminal state


async def _sync_loop(rec: RunRecord) -> None:
    """Heartbeat: mirror the live run to the DB every couple of seconds."""
    while rec.status in ("running", "paused"):
        await persistence.persist_snapshot(rec)
        await asyncio.sleep(2.0)


# ── Endpoints ─────────────────────────────────────────────────────────

@router.post("/runs", response_model=RunCreatedResponse)
async def start_run(
    req: StartRunRequest,
    user_id: int = Depends(get_current_user_id),
) -> RunCreatedResponse:
    """Start an autonomous research run as a background task; returns its goal_id."""
    goal_id = uuid.uuid4().hex[:12]
    rec = RunRecord(goal_id=goal_id, user_id=user_id, goal_text=req.goal_text)
    _runs[goal_id] = rec
    await persistence.create_run_row(goal_id, user_id, req)
    rec.task = asyncio.create_task(_run_and_track(rec, req))
    logger.info("Started research run %s for user %s: %r", goal_id, user_id, req.goal_text)
    return RunCreatedResponse(
        goal_id=goal_id,
        status=rec.status,
        goal_text=req.goal_text,
        asset_pool=req.asset_pool,
        strategy_families=req.strategy_families,
        max_runs=req.max_runs,
        target_candidates=req.target_candidates,
    )


# ── Run lifecycle controls (A-9, ATSX-28) ────────────────────────────
# Cooperative: endpoints flip rec.control; the loop reads it each iteration.


@router.post("/runs/{goal_id}/pause")
async def pause_run(goal_id: str, user_id: int = Depends(get_current_user_id)) -> dict[str, str]:
    """Pause a live run; the loop idles at the next iteration boundary."""
    rec = _owned_run(goal_id, user_id)
    if rec.status != "running":
        raise HTTPException(409, f"Run is {rec.status}, cannot pause")
    rec.control = "pause"
    rec.status = "paused"
    return {"goal_id": goal_id, "status": rec.status}


@router.post("/runs/{goal_id}/resume")
async def resume_run(goal_id: str, user_id: int = Depends(get_current_user_id)) -> dict[str, str]:
    """Resume a paused run."""
    rec = _owned_run(goal_id, user_id)
    if rec.status != "paused":
        raise HTTPException(409, f"Run is {rec.status}, cannot resume")
    rec.control = "run"
    rec.status = "running"
    return {"goal_id": goal_id, "status": rec.status}


@router.post("/runs/{goal_id}/stop")
async def stop_run(
    goal_id: str,
    report: bool = False,
    user_id: int = Depends(get_current_user_id),
) -> dict[str, str]:
    """Stop a live run cooperatively. The loop breaks at the next iteration boundary.

    A plain stop ends as "stopped"; ?report=true forces a final report → "completed".
    (The rule-based report is generated either way; the flag sets the run-level status.)
    """
    rec = _owned_run(goal_id, user_id)
    if rec.status not in ("running", "paused"):
        raise HTTPException(409, f"Run is {rec.status}, cannot stop")
    rec.control = "stop_report" if report else "stop"
    return {"goal_id": goal_id, "status": "stopping"}


@router.post("/runs/{goal_id}/cancel")
async def cancel_run(goal_id: str, user_id: int = Depends(get_current_user_id)) -> dict[str, str]:
    """Hard-cancel a live run's background task; marks the run interrupted."""
    rec = _owned_run(goal_id, user_id)
    rec.control = "stop"  # cooperative fallback if cancellation lands between iterations
    if rec.task is not None:
        rec.task.cancel()
    return {"goal_id": goal_id, "status": "interrupting"}


@router.get("/runs", response_model=list[RunListItem])
async def list_runs(
    user_id: int = Depends(get_current_user_id),
) -> list[RunListItem]:
    """List the caller's research runs, newest first (C-6 runs history)."""
    rows = await persistence.load_runs_list(user_id)
    return [RunListItem(**r, leakage=_run_leakage(r.get("provider_type", ""), r.get("model_id", ""))) for r in rows]


@router.get("/runs/preview", response_model=ScopePreviewResponse)
async def preview_scope(
    goal_text: str,
    max_runs: int = 200,
    _user_id: int = Depends(get_current_user_id),
) -> ScopePreviewResponse:
    """Interpret a free-text goal into symbol/strategy pools + a cost estimate."""
    from src.backend.ai.goals.planner import parse_goal_scope

    scope = parse_goal_scope(goal_text)
    n_combos = max(1, len(scope.symbol_pool)) * max(1, len(scope.strategy_pool))
    # Rough upper bound: ~10 param variants per (symbol, strategy) combo, capped at max_runs.
    est_runs = min(max_runs, n_combos * 10)
    per_run_seconds = 2.0
    return ScopePreviewResponse(
        interpreted={
            "symbol_pool": scope.symbol_pool,
            "strategy_pool": scope.strategy_pool,
        },
        cost={
            "eur": 0.0,  # rule-based strategist makes no LLM calls
            "runs": est_runs,
            "duration_seconds": round(est_runs * per_run_seconds),
        },
        source_annotations=scope.source_annotations,
        mode="rule_based",
        notes="Estimate only. eur=0 in rule-based mode; LLM mode would add per-call cost.",
    )


@router.get("/runs/{goal_id}/state", response_model=ResearchStateResponse)
async def get_run_state(
    goal_id: str,
    user_id: int = Depends(get_current_user_id),
) -> ResearchStateResponse:
    """Current loop state for a run (ownership-checked).

    Prefers the live in-memory state; falls back to the DB so a run survives
    a backend restart (ATSX-10 / A-2).
    """
    rec = _runs.get(goal_id)
    if rec is not None and rec.user_id == user_id and rec.state is not None:
        state = rec.state
        return ResearchStateResponse(
            phase=str(state.phase),
            goal_text=rec.goal_text or state.goal.goal_text,
            current_asset=state.current_asset,
            total_iterations=state.total_iterations,
            candidates_count=len(state.candidates),
            budget_used_runs=state.budget.used_runs,
            budget_remaining_runs=state.budget.remaining_runs(),
            failure_count=len(state.all_failures),
            error_message=state.error_message or rec.error,
            status=rec.status,
            used_eur=float(state.budget.used_eur),
            cost_known=bool(getattr(state.budget, "cost_known", True)),   # M44
            agent_mode=getattr(state, "agent_mode", "rule_based"),   # W4 F-5
            mode=getattr(state, "mode", "robustness"),               # P1
            window_start=getattr(state, "window_start", ""),
            window_end=getattr(state, "window_end", ""),
            train_end=getattr(state, "train_end", ""),   # M31
            provider_type=getattr(state, "provider_type", ""),        # P2
            model_id=getattr(state, "model_id", ""),                  # H31
            leakage=_run_leakage(getattr(state, "provider_type", ""), getattr(state, "model_id", "")),
            max_seconds=state.budget.max_seconds,
            started_at=rec.started_at.isoformat() if rec.started_at else None,
            current_lineage=state.current_lineage_id,
        )

    row = await persistence.load_run_for_state(goal_id, user_id)
    if row is None:
        if rec is not None and rec.user_id == user_id:
            # Run just created; the loop hasn't published its state yet.
            return ResearchStateResponse(
                phase="goal_received", goal_text=rec.goal_text, current_asset="",
                total_iterations=0, candidates_count=0, budget_used_runs=0,
                budget_remaining_runs=0, failure_count=0, error_message=rec.error,
                status=rec.status,
                started_at=rec.started_at.isoformat() if rec.started_at else None,
            )
        raise HTTPException(404, f"No research run {goal_id}")
    return ResearchStateResponse(
        phase=row["phase"],
        goal_text=row["goal_text"],
        current_asset=row["current_asset"],
        total_iterations=row["used_runs"],
        candidates_count=row["candidates_count"],
        budget_used_runs=row["used_runs"],
        budget_remaining_runs=max(0, row["max_runs"] - row["used_runs"]),
        failure_count=row["failure_count"],
        error_message=row["error_message"],
        status=row["status"],
        used_eur=row["used_eur"],
        max_seconds=row["max_seconds"],
        started_at=row["started_at"],   # M53: already a UTC-marked ISO string from persistence._utc_iso
        current_lineage=row["current_lineage"],
        agent_mode=row.get("agent_mode", "rule_based"),   # D1: persisted path now surfaces these
        mode=row.get("mode", "robustness"),
        window_start=row.get("window_start", ""),
        window_end=row.get("window_end", ""),
        train_end=row.get("train_end", ""),   # M31
        provider_type=row.get("provider_type", ""),        # P2
        model_id=row.get("model_id", ""),                  # H31
        leakage=_run_leakage(row.get("provider_type", ""), row.get("model_id", "")),
    )


@router.get("/runs/{goal_id}/candidates", response_model=list[CandidateResponse])
async def get_run_candidates(
    goal_id: str,
    user_id: int = Depends(get_current_user_id),
) -> list[CandidateResponse]:
    """Validated strategy candidates for a run (ownership-checked, DB fallback)."""
    from src.backend.ai.research.quality import quality_summary

    def _qmode(validation_status: str) -> str:
        # CF-1: validation_status is "" for robustness, non-empty (>= "unvalidated") for every regime idea.
        return "regime" if validation_status else "robustness"

    _RANK = {"moderate": 2, "low": 1, "very_low": 0}

    def _cap(cands: list[CandidateResponse]) -> list[CandidateResponse]:
        # DG-3/DG-6: regime ideas (validation_status set) → rank + return top-N; robustness → all.
        if not any(c.validation_status for c in cands):
            return cands
        ranked = sorted(
            cands,
            # P2-7: regime_validated ranks above all UNVALIDATED tiers, then confidence, then fewer weaknesses.
            key=lambda c: (
                1 if c.validation_status == "regime_validated" else 0,
                _RANK.get(c.confidence, 0),
                -len(c.weaknesses or []),
                c.sharpe_annual,
            ),
            reverse=True,
        )
        n = 10
        if len(ranked) > n:
            logger.info("regime /candidates %s: %d surfaced, top %d shown", goal_id, len(ranked), n)
        return ranked[:n]

    rec = _runs.get(goal_id)
    if rec is not None and rec.user_id == user_id and rec.state is not None:
        oos_map = {o.strategy_hash: o.outcome for o in rec.state.oos_results}
        out = []
        for c in rec.state.candidates:
            _oos = oos_map.get(c.strategy_hash, "PENDING")
            _vs = getattr(c, "validation_status", "")
            _wk = getattr(c, "weaknesses", []) or []
            out.append(CandidateResponse(
                strategy_hash=c.strategy_hash,
                run_id=c.run_id,
                template_id=c.template_id,
                security_id=c.security_id,
                sharpe_annual=c.sharpe_annual,
                total_return=c.total_return,
                max_drawdown=c.max_drawdown,
                n_trades=c.n_trades,
                critic_confidence=c.critic_confidence,
                oos_outcome=_oos,
                validation_status=_vs,
                confidence=getattr(c, "confidence", ""),
                decay=getattr(c, "decay", {}) or {},
                weaknesses=_wk,
                holdout=getattr(c, "holdout", {}) or {},
                quality=quality_summary(
                    getattr(c, "gate_report_summary", {}) or {},
                    oos=_oos, mode=_qmode(_vs),
                    confidence=getattr(c, "confidence", ""),
                    validation_status=_vs, weaknesses=_wk,
                ),
            ))
        return _cap(out)
    rows = await persistence.load_candidates(goal_id, user_id)
    if rows is None:
        if rec is not None and rec.user_id == user_id:
            return []
        raise HTTPException(404, f"No research run {goal_id}")
    out = []
    for r in rows:
        gr = r.pop("gate_report", {}) or {}            # not a CandidateResponse field — pop before construct
        _vs = r.get("validation_status", "")
        r["quality"] = quality_summary(
            gr, oos=r.get("oos_outcome", ""), mode=_qmode(_vs),
            confidence=r.get("confidence", ""), validation_status=_vs,
            weaknesses=r.get("weaknesses", []) or [],
        )
        out.append(CandidateResponse(**r))
    return _cap(out)


@router.get("/runs/{goal_id}/hypothesis", response_model=HypothesisResponse)
async def get_run_hypothesis(
    goal_id: str,
    user_id: int = Depends(get_current_user_id),
) -> HypothesisResponse:
    """The run's latest hypothesis — feeds the HypothesisCard (A-5).

    Live-state preferred; falls back to the persisted ``research_hypotheses`` (Phase 2)
    so the AI's reasoning survives a restart instead of 404-ing.
    """
    rec = _runs.get(goal_id)
    if rec is not None and rec.user_id == user_id and rec.state is not None and rec.state.hypotheses:
        h = rec.state.hypotheses[-1]
        return HypothesisResponse(
            hypothesis_id=h.hypothesis_id,
            economic_rationale=h.economic_rationale,
            claimed_mechanism=h.claimed_mechanism,
            falsifiable_prediction=h.falsifiable_prediction,
            prior_strength=h.prior_strength,
            proposed_template_id=h.proposed_template_id,
        )
    # DB fallback (survives restart) — the latest persisted proposal.
    rows = await persistence.load_hypotheses(goal_id, user_id)
    if rows is None:
        raise HTTPException(404, f"No research run {goal_id}")
    if not rows:
        raise HTTPException(404, "No hypothesis yet")
    h = rows[-1]
    return HypothesisResponse(
        hypothesis_id=h["hypothesis_id"],
        economic_rationale=h["economic_rationale"],
        claimed_mechanism=h["claimed_mechanism"],
        falsifiable_prediction=h["falsifiable_prediction"],
        prior_strength=h["prior_strength"],
        proposed_template_id=h["proposed_template_id"],
    )


class LineageNodeResponse(BaseModel):
    """One node of the lineage tree (ATSX-26)."""

    lineage_id: str
    parent_lineage_id: str | None = None
    root_strategy_hash: str | None = None
    declared_by: str = ""
    created_at: str | None = None


@router.get("/runs/{goal_id}/lineage", response_model=list[LineageNodeResponse])
async def get_run_lineage(
    goal_id: str,
    user_id: int = Depends(get_current_user_id),
) -> list[LineageNodeResponse]:
    """The run's lineage tree (ATSX-26). Live-preferred; falls back to the persisted
    research_lineage (G4) so the tree survives a restart instead of 404-ing."""
    rec = _runs.get(goal_id)
    if rec is not None and rec.user_id == user_id and rec.state is not None:
        nodes = getattr(rec.state, "lineage_nodes", []) or []
        if nodes:
            return [LineageNodeResponse(**n) for n in nodes]
    rows = await persistence.load_lineage(goal_id, user_id)
    if rows is None:
        raise HTTPException(404, f"No research run {goal_id}")
    return [LineageNodeResponse(**n) for n in rows]


async def _candidate_detail_or_404(goal_id: str, strategy_hash: str, user_id: int) -> dict[str, Any]:
    """Resolve a candidate's detail (live preferred, DB fallback) or raise 404."""
    rec = _runs.get(goal_id)
    if rec is not None and rec.user_id == user_id and rec.state is not None:
        for c in rec.state.candidates:
            if c.strategy_hash == strategy_hash:
                oos_map = {o.strategy_hash: o for o in rec.state.oos_results}
                o = oos_map.get(strategy_hash)
                return {
                    "strategy_hash": c.strategy_hash,
                    "critique": c.critique,
                    "critic_confidence": c.critic_confidence,
                    "gate_report": c.gate_report_summary,
                    "artifacts": {
                        "regime_analysis": c.regime_analysis,
                        "benchmark": c.benchmark,
                        "equity_curve": c.equity_curve,
                    },
                    "oos_outcome": o.outcome if o else "PENDING",
                    "oos_lineage_id": o.lineage_id if o else c.__dict__.get("lineage_id", ""),
                    "oos_evaluated_at": o.evaluated_at if o else "",
                }
    detail = await persistence.load_candidate_detail(goal_id, strategy_hash, user_id)
    if detail is None:
        raise HTTPException(404, f"No research run {goal_id}")
    if detail.get("_missing"):
        raise HTTPException(404, f"No candidate {strategy_hash} in run {goal_id}")
    return detail


@router.get("/runs/{goal_id}/candidates/{strategy_hash}/gates", response_model=list[GateResultResponse])
async def get_candidate_gates(
    goal_id: str,
    strategy_hash: str,
    user_id: int = Depends(get_current_user_id),
) -> list[GateResultResponse]:
    """Per-candidate gate results — the dossier leads with these (A-6b)."""
    detail = await _candidate_detail_or_404(goal_id, strategy_hash, user_id)
    results = (detail.get("gate_report") or {}).get("results", [])
    return [
        GateResultResponse(
            gate_id=r.get("gate_id", "?"),
            status=str(r.get("status", "")),
            value=r.get("value"),
            threshold=r.get("threshold"),
            details=r.get("details", {}) or {},
        )
        for r in results
    ]


@router.get("/runs/{goal_id}/candidates/{strategy_hash}/critique", response_model=CritiqueResponse)
async def get_candidate_critique(
    goal_id: str,
    strategy_hash: str,
    user_id: int = Depends(get_current_user_id),
) -> CritiqueResponse:
    """Per-candidate adversarial critique (A-6c)."""
    detail = await _candidate_detail_or_404(goal_id, strategy_hash, user_id)
    crit = detail.get("critique") or {}
    return CritiqueResponse(
        confidence=crit.get("confidence", detail.get("critic_confidence", "low")),
        recommendation=crit.get("recommendation", ""),
        weaknesses=crit.get("weaknesses", []),
        prose=crit.get("reasoning", ""),
    )


@router.get("/runs/{goal_id}/candidates/{strategy_hash}/oos", response_model=OOSResponse)
async def get_candidate_oos(
    goal_id: str,
    strategy_hash: str,
    user_id: int = Depends(get_current_user_id),
) -> OOSResponse:
    """Per-candidate out-of-sample verdict (A-6d)."""
    detail = await _candidate_detail_or_404(goal_id, strategy_hash, user_id)
    return OOSResponse(
        outcome=detail.get("oos_outcome", "PENDING"),
        lineage_id=detail.get("oos_lineage_id", detail.get("lineage_id", "")),
        evaluated_at=detail.get("oos_evaluated_at", ""),
    )


class CandidateArtifactsResponse(BaseModel):
    """Evidence drill-downs for the Candidate Dossier (ATSX-27)."""

    regime_analysis: dict[str, Any] = {}
    benchmark: dict[str, Any] = {}
    equity_curve: list[float] = []


@router.get(
    "/runs/{goal_id}/candidates/{strategy_hash}/artifacts",
    response_model=CandidateArtifactsResponse,
)
async def get_candidate_artifacts(
    goal_id: str,
    strategy_hash: str,
    user_id: int = Depends(get_current_user_id),
) -> CandidateArtifactsResponse:
    """Per-candidate evidence: regime breakdown, benchmark, equity curve (ATSX-27)."""
    detail = await _candidate_detail_or_404(goal_id, strategy_hash, user_id)
    art = detail.get("artifacts") or {}
    return CandidateArtifactsResponse(
        regime_analysis=art.get("regime_analysis", {}) or {},
        benchmark=art.get("benchmark", {}) or {},
        equity_curve=art.get("equity_curve", []) or [],
    )


def _event_payload(r: dict[str, Any]) -> dict[str, Any]:
    """Normalize a stored event row into the wireframe EventResponse shape."""
    detail = r["detail"] or {}
    ts = r["ts"]
    return {
        "id": r["id"],
        "ts": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
        "kind": _normalize_kind(r["kind"], detail),
        "raw_kind": r["kind"],
        "phase": r["phase"] or "",
        "lineage_id": r["lineage_id"] or "",
        "title": _event_title(r["kind"], detail),
        "detail": detail,
        "strategy_hash": r["strategy_hash"],
    }


@router.get("/runs/{goal_id}/events", response_model=list[EventResponse])
async def get_run_events(
    goal_id: str,
    since: int = 0,
    limit: int = 200,
    user_id: int = Depends(get_current_user_id),
) -> list[EventResponse]:
    """Activity stream for a run, paged by ?since=<eventId> (ownership-checked).

    Reads from research_events (flushed by the A-2 heartbeat), normalizing the
    loop's raw event kinds into the wireframe taxonomy with a human title.
    """
    rows = await persistence.load_events(goal_id, user_id, since=since, limit=limit)
    if rows is None:
        raise HTTPException(404, f"No research run {goal_id}")
    return [EventResponse(**_event_payload(r)) for r in rows]


@router.get("/runs/{goal_id}/events/stream")
async def stream_run_events(
    goal_id: str,
    since: int = 0,
    user_id: int = Depends(get_current_user_id),
) -> StreamingResponse:
    """SSE stream of the activity events (ATSX-26 / P4). Additive — clients may
    still poll GET /events. Tails the persisted research_events and closes once
    the run is terminal and the backlog is drained.
    """
    # Ownership check before opening the stream (fast 404).
    first = await persistence.load_events(goal_id, user_id, since=since, limit=200)
    if first is None:
        raise HTTPException(404, f"No research run {goal_id}")

    terminal = {"completed", "failed", "interrupted", "stopped"}

    async def _gen():
        cursor = since
        drained_after_terminal = 0
        for _ in range(6000):  # ~100 min hard cap (1s cadence) — runaway backstop
            rows = await persistence.load_events(goal_id, user_id, since=cursor, limit=200)
            if rows:
                for r in rows:
                    cursor = r["id"]
                    yield f"data: {json.dumps(_event_payload(r))}\n\n"
            rec = _runs.get(goal_id)
            is_terminal = rec is None or rec.status in terminal
            if is_terminal and not rows:
                drained_after_terminal += 1
                if drained_after_terminal >= 2:
                    yield "event: end\ndata: {}\n\n"
                    return
            else:
                drained_after_terminal = 0
            await asyncio.sleep(1.0)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/runs/{goal_id}/graveyard", response_model=GraveyardResponse)
async def get_run_graveyard(
    goal_id: str,
    user_id: int = Depends(get_current_user_id),
) -> GraveyardResponse:
    """The graveyard (A-7): every strategy that died + an aggregate by cause.

    Counts reconcile with state.failure_count. Live state preferred, DB fallback.
    """
    rec = _runs.get(goal_id)
    if rec is not None and rec.user_id == user_id and rec.state is not None:
        failures = [
            {
                "strategy_hash": fc.strategy_hash,
                "template_id": fc.template_id,
                "security_id": fc.security_id,
                "failed_gate": fc.failed_gate or "",
                "failure_reason": fc.failure_reason,
                "critic_notes": fc.critic_notes or "",
                "gate_details": fc.gate_details or {},
                "hypothesis_id": fc.hypothesis_id,
                "params": fc.params or {},
            }
            for fc in rec.state.all_failures  # 1a: full record, not the per-asset-cleared working memory
        ]
    else:
        failures = await persistence.load_failures(goal_id, user_id)
        if failures is None:
            raise HTTPException(404, f"No research run {goal_id}")

    by_cause: dict[str, int] = {}
    for f in failures:
        cause = f.get("failed_gate") or f.get("failure_reason") or "unknown"
        by_cause[cause] = by_cause.get(cause, 0) + 1
    return GraveyardResponse(
        total=len(failures),
        by_cause=by_cause,
        failures=[FailureItem(**f) for f in failures],
    )


@router.get("/runs/{goal_id}/report", response_model=ReportResponse)
async def get_run_report(
    goal_id: str,
    user_id: int = Depends(get_current_user_id),
) -> ReportResponse:
    """The Reporter's FinalReport (A-8) — honest, template-bound numbers.

    Live (rec.report) preferred; falls back to the persisted report_json so it
    survives a restart. ``available=False`` while a run hasn't finished a report.
    """
    rec = _runs.get(goal_id)
    if rec is not None and rec.user_id == user_id and rec.report is not None:
        from src.backend.ai.research.report_generator import serialize_report
        data = serialize_report(rec.report)
        return ReportResponse(
            status=rec.status,
            goal_text=rec.goal_text,
            available=True,
            sections=[ReportSectionResponse(**s) for s in data["sections"]],
        )

    loaded = await persistence.load_report(goal_id, user_id)
    if loaded is None:
        if rec is not None and rec.user_id == user_id:
            # Run live but no report yet.
            return ReportResponse(status=rec.status, goal_text=rec.goal_text, available=False)
        raise HTTPException(404, f"No research run {goal_id}")
    sections = loaded["report"].get("sections", []) if isinstance(loaded["report"], dict) else []
    return ReportResponse(
        status=loaded["status"],
        goal_text=loaded["goal_text"],
        available=bool(sections),
        sections=[ReportSectionResponse(**s) for s in sections],
    )


@router.get("/stats", response_model=RegistryStatsResponse)
async def get_registry_stats(
    user_id: int = Depends(get_current_user_id),
) -> RegistryStatsResponse:
    """Director-dashboard aggregates across the caller's runs (A-10).

    Honest: backed by the populated research_* tables. The backtesting
    TrialEventRegistry is not wired to research runs, so we do not report from it.
    """
    s = await persistence.aggregate_stats(user_id)
    return RegistryStatsResponse(**s)


@router.get("/catalog")
async def get_catalog(_user_id: int = Depends(get_current_user_id)) -> dict[str, Any]:
    """F5 — the Start-screen catalog: existing strategy templates, families, curated
    universe baskets, known symbols (for validation), and the rigor presets. Read-only."""
    from src.backend.ai.research.strategist import TEMPLATES, FAMILY_MAP
    from src.backend.ai.analysis.clustering import ASSET_CLASS, ASSET_CLASS_LABELS

    templates = [
        {
            "id": tid,
            "family": next((f for f, ts in FAMILY_MAP.items() if tid in ts), ""),
            "params": {k: [v.get("low"), v.get("high")] for k, v in space.items()},
        }
        for tid, space in TEMPLATES.items()
    ]
    families = [{"id": f, "templates": ts} for f, ts in FAMILY_MAP.items()]
    by_class: dict[str, set[str]] = {}
    for sym, cls in ASSET_CLASS.items():
        by_class.setdefault(cls, set()).add(sym)
    baskets = [
        {"id": cls, "label": ASSET_CLASS_LABELS.get(cls, cls), "tickers": sorted(syms)}
        for cls, syms in sorted(by_class.items())
    ]
    return {
        "templates": templates,
        "families": families,
        "baskets": baskets,
        "known_symbols": sorted(ASSET_CLASS.keys()),
        "rigor_presets": ["exploratory", "standard", "strict"],
    }
