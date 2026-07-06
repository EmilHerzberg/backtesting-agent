"""ATS-1757/1758 — The autonomous research loop.

Single async function that drives the full state machine per
AGENT-WORKFLOW-DESIGN.md Part 3, with the rule-based Director per
DIRECTOR-REQUIREMENTS.md / DIRECTOR-TECHNICAL-SPEC.md (v2):

    GOAL_RECEIVED → STRATEGIST_THINKS → DATA_PREPARED → BACKTEST_RUN
    → GATES_EVALUATED → CRITIC_REVIEW → [auto OOS_LOCKBOX] → ORCHESTRATOR_DECIDES
    → (loop or RESULT)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal, Protocol

import numpy as np

from src.backend.ai.research.budgets import AgentBudgetController, BudgetExceededError
from src.backend.ai.research.state import (
    Budget,
    Candidate,
    DataSnapshot,
    FailureContext,
    GoalBrief,
    Hypothesis,
    OOSResult,
    ResearchPhase,
    ResearchState,
    RunArtifacts,
)
from src.backend.backtesting.validation.lineage import LineageTracker

logger = logging.getLogger(__name__)


# ── Protocols for pluggable components ────────────────────────────────

class StrategistProtocol(Protocol):
    """The LLM agent that proposes strategy specs."""

    async def propose(
        self,
        asset: str,
        strategy_families: list[str],
        failure_context: list[FailureContext],
        registry_summary: dict[str, Any],
    ) -> tuple[Hypothesis, dict[str, Any]]:
        """Return (hypothesis, strategy_spec_dict)."""
        ...


class ExecutorProtocol(Protocol):
    """Deterministic backtest execution."""

    def run(self, spec: dict[str, Any], data: Any, *, warmup_bars: int = 0) -> dict[str, Any]:
        """Run a backtest and return metrics dict."""
        ...


class GatekeeperProtocol(Protocol):
    """Deterministic quality gate pipeline."""

    def evaluate(self, metrics: dict[str, Any], returns: Any, context: dict[str, Any]) -> dict[str, Any]:
        """Run gates and return gate_report dict."""
        ...

    def update_registry_stats(
        self, n_trials: int, sr_variance: float, *, variance_defaulted: bool = False
    ) -> None:
        """Update DSR inputs from the registry."""
        ...


class CriticProtocol(Protocol):
    """Adversarial reviewer in a separate LLM context."""

    async def review(
        self,
        spec: dict[str, Any],
        metrics: dict[str, Any],
        gate_report: dict[str, Any],
    ) -> dict[str, Any]:
        """Return critique dict with 'recommendation' (accept/reject/investigate)."""
        ...


def _record_failure(state, fc) -> None:
    """Record a failed attempt in BOTH the Strategist's bounded per-asset memory (cleared on rotation)
    and the append-only full record (persisted, never cleared). See PER-ATTEMPT-PERSISTENCE-SPEC §3."""
    state.failure_context.append(fc)
    state.all_failures.append(fc)


class DataAgentProtocol(Protocol):
    """Data fetching and snapshot creation."""

    def prepare(self, security_id: str, window_start: str, window_end: str) -> Any:
        """Fetch + validate + snapshot. Returns OHLCV DataFrame."""
        ...


class OrchestratorProtocol(Protocol):
    """Meta-decision maker (per spec Part 5: Research Director)."""

    async def decide(self, state: ResearchState, last_outcome: str) -> "DirectorDecision":
        """Return a DirectorDecision: continue | next_asset | done."""
        ...


# ── Rule-based Director (default) ─────────────────────────────────────
# DIRECTOR-REQUIREMENTS.md / DIRECTOR-TECHNICAL-SPEC.md v2. Pure, deterministic,
# no LLM. The flow controller that owns when to continue / move on / stop.

@dataclass
class DirectorConfig:
    per_asset_cap: int = 25
    plateau_eps: float = 0.05
    max_consecutive_failures: int = 12
    error_breaker: int = 5
    oos_enabled: bool = False            # AUTHORITATIVE value forced by the loop (T1)

    @property
    def plateau_window(self) -> int:     # C6
        return max(4, self.per_asset_cap // 3)


@dataclass
class DirectorDecision:
    decision: Literal["continue", "next_asset", "done"]
    reason: str
    evidence: dict     # triggering numbers (D-3); MAY include wall-clock `elapsed` (non-deterministic, T4)


def plateau(best_sharpe: list[float], window: int, eps: float) -> bool:
    """True if the running-max Sharpe improved < eps over the last `window` samples.
    Sign-safe (absolute improvement); `best_sharpe` is non-decreasing by construction."""
    if len(best_sharpe) < window:
        return False
    return (best_sharpe[-1] - best_sharpe[-window]) < eps


class RuleBasedOrchestrator:
    """Deterministic flow controller (DIRECTOR-REQUIREMENTS v2). No LLM, €0."""

    def __init__(self, config: DirectorConfig | None = None):
        self.config = config or DirectorConfig()

    async def decide(self, state: ResearchState, last_outcome: str) -> DirectorDecision:
        cfg = self.config
        b = state.budget
        queue_non_empty = len(state.asset_queue) > 0
        elapsed = b.elapsed_seconds()
        validated = state.validated_count(cfg.oos_enabled)
        ev = {
            "remaining_runs": b.remaining_runs(),
            "elapsed": round(elapsed, 1),
            "validated": validated,
            "target": state.goal.target_candidates,
            "attempts_on_asset": state.attempts_on_current_asset,
            "consecutive_failures": state.consecutive_failures,
            "consecutive_errors": state.consecutive_errors,
            "last_outcome": last_outcome,
        }

        def D(decision: str, reason: str) -> DirectorDecision:
            return DirectorDecision(decision, reason, ev)  # type: ignore[arg-type]

        # R1 — goal met (OOS-aware), checked first so a goal+budget tie reports goal_met (T10)
        if validated >= state.goal.target_candidates:
            return D("done", "goal_met")
        # R2 — budget exhausted
        if (b.remaining_runs() <= 0
                or elapsed >= b.max_seconds
                or (b.max_eur > 0 and b.used_eur >= b.max_eur)):          # T9
            return D("done", "budget_exhausted")
        # R3 — circuit breaker (errors)
        if state.consecutive_errors >= cfg.error_breaker:
            return D("next_asset", "circuit_breaker") if queue_non_empty else D("done", "circuit_breaker_last")
        # R4 — asset exhausted (can stop the last asset)
        if (plateau(state.best_sharpe_on_asset, cfg.plateau_window, cfg.plateau_eps)
                or state.consecutive_failures >= cfg.max_consecutive_failures):
            return D("next_asset", "asset_exhausted") if queue_non_empty else D("done", "asset_exhausted_last")
        # R5 — fairness cap (never stops the last/only asset)
        if state.attempts_on_current_asset >= cfg.per_asset_cap and queue_non_empty:
            return D("next_asset", "fairness_cap")
        # R6 — continue
        return D("continue", "continue")


# ── Helper: regime analysis ──────────────────────────────────────────

def _compute_regime_analysis(returns: Any) -> dict[str, Any]:
    """Basic regime analysis: split returns into bull/bear/sideways windows."""
    if returns is None or len(returns) < 60:
        return {}

    arr = np.asarray(returns, dtype=np.float64)
    n = len(arr)
    regimes = {}

    for i, label in enumerate(["early", "mid", "late"]):
        start = i * (n // 3)
        end = min(start + (n // 3), n)
        segment = arr[start:end]
        if len(segment) == 0:
            continue
        cum_return = float(np.prod(1 + segment) - 1)
        seg_sharpe = 0.0
        if segment.std() > 0:
            seg_sharpe = float(segment.mean() / segment.std() * np.sqrt(252))
        regime_type = "bull" if cum_return > 0.05 else ("bear" if cum_return < -0.05 else "sideways")
        regimes[label] = {
            "type": regime_type,
            "return": round(cum_return, 4),
            "sharpe": round(seg_sharpe, 2),
            "n_bars": int(end - start),
        }

    return regimes


def _downsample_curve(curve: Any, max_points: int = 120) -> list:
    """Downsample an equity curve to <=max_points floats for the dossier sparkline."""
    if not curve:
        return []
    try:
        pts = [float(x) for x in curve]
    except (TypeError, ValueError):
        return []
    if len(pts) <= max_points:
        return [round(x, 4) for x in pts]
    step = len(pts) / max_points
    return [round(pts[int(i * step)], 4) for i in range(max_points)]


# ── P2: regime forward-slice hold-out + decay helpers (REGIME-P2-HOLDOUT-SPEC v2) ────
MIN_HOLD_DAYS = 120          # a hold-out (or decay slice) below ~4mo can't mean anything
VALIDATE_MIN_TRADES = 20     # P2-R4: a "validated" claim needs a non-trivial sample (independent of rigor)
VALIDATE_T = 1.65            # P2-R4: ~95% one-sided; stricter than quick/medium selection t*
OOS_MIN_TRADES = VALIDATE_MIN_TRADES  # D5/H3: an OOS verdict needs a real sample, else UNEVALUATED


def _days(a: str, b: str) -> int:
    """Calendar days between two ISO dates (module-level: shared by decay + hold-out + train-split)."""
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except Exception:
        return 0


def _env_bounds() -> tuple[str, str]:
    """The full available data envelope, for out-of-regime decay slices."""
    return "2010-01-01", datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _period_sharpe(returns) -> float | None:
    """Per-period (e.g. daily) Sharpe of a return series — the SAME quantity the Deflated-Sharpe
    gate uses as its ``sr_hat`` (mean / std, ddof=1). Returns ``None`` for a series too short or flat
    to have a defined Sharpe. H1: the DSR multiplicity math is per-period, never annualized."""
    if returns is None:
        return None
    r = np.asarray(returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    if r.size < 2:
        return None
    sd = r.std(ddof=1)
    if not np.isfinite(sd) or sd <= 0:
        return None
    return float(r.mean() / sd)


def _dsr_registry_inputs(period_sharpes: list[float]) -> tuple[int, float, bool]:
    """Deflated-Sharpe multiplicity inputs (H1 / M25 / M24).

    Returns ``(n_trials, trial_sr_variance, variance_defaulted)`` where N is the number of
    gate-evaluable trials (those that produced a measurable per-period Sharpe) and the variance is
    the per-period trial-Sharpe variance (ddof=1) — the two share one scope, so the expected-max-
    Sharpe hurdle sits on the same footing as the per-period ``sr_hat`` the gate computes. When
    fewer than two trials have been measured the variance cannot be estimated, so a floor is returned
    with ``variance_defaulted=True`` (M24: explicit, not a magic-value sniff downstream). Replaces
    the old ``(state.total_iterations, np.var(annualized_sharpes))`` which paired a padded iteration
    count (errors/skips included) with an annualized variance ~252x too large."""
    n = len(period_sharpes)
    if n > 1:
        return n, float(np.var(period_sharpes, ddof=1)), False
    return n, 0.001, True


def _train_split(window_start: str, window_end: str) -> str | None:
    """P2 select-on-train: the ISO date splitting the regime window into train=[ws, split] +
    hold-out=[split, we]. Returns None when the window is too short to carve an honest hold-out
    (span < ~300d → the 4mo floor would exceed the 40% cap, P2-R2) — no split, stays UNVALIDATED
    (P2-5). ``h`` is set from window LENGTH only; the per-strategy floor handles trade frequency."""
    span = _days(window_start, window_end)
    if span <= 0 or 0.40 * span < MIN_HOLD_DAYS:      # too short to validate honestly
        return None
    hold = max(int(0.25 * span), MIN_HOLD_DAYS)        # 25%, but ≥ 4mo; the guard ensures hold ≤ 40% of span
    try:
        return (date.fromisoformat(window_end) - timedelta(days=hold)).isoformat()
    except Exception:
        return None


def _spec_lookback(spec: dict) -> int:
    """Largest integer lookback in a strategy spec's params — the warm-up length its indicators need."""
    params = spec.get("params", {}) or {}
    return int(max((v for v in params.values() if isinstance(v, (int, float)) and v > 1), default=0))


def _prepare_with_warmup(data_agent, security_id: str, window_start: str, window_end: str, spec: dict):
    """M26 — fetch the evaluation window WITH a warm-up prefix so indicators converge before it.

    Returns ``(data, warmup_bars)`` where ``warmup_bars`` is the number of leading bars that precede
    ``window_start`` (0 if the strategy needs no lookback or no prior data is available). Falls back to
    a plain window fetch on any error. Pairs with C1's ``BacktestConfig.warmup_bars`` (via
    ``executor.run(..., warmup_bars=...)``) so the short OOS / hold-out / decay slices aren't scored
    on cold, unconverged indicators."""
    import pandas as pd

    lookback = _spec_lookback(spec)
    if lookback <= 0:
        return data_agent.prepare(security_id=security_id, window_start=window_start, window_end=window_end), 0
    # Reach back generously in calendar days to cover the trading-bar lookback (weekends/holidays).
    buffer_days = int(lookback * 1.7) + 10
    try:
        prep_start = (date.fromisoformat(window_start) - timedelta(days=buffer_days)).isoformat()
    except Exception:
        prep_start = window_start
    data = data_agent.prepare(security_id=security_id, window_start=prep_start, window_end=window_end)
    try:
        warmup = int((data.index < pd.Timestamp(window_start)).sum())
    except Exception:
        warmup = 0
    if warmup >= len(data) - 2:  # never let the warm-up swallow the scoring window
        warmup = 0
    return data, warmup


def _slice_edge(spec, data_agent, executor, start, end, in_regime_sharpe) -> dict | None:
    """Run the SAME strategy on one out-of-regime slice; report retained edge. None if the slice is
    too short to mean anything."""
    if _days(start, end) < MIN_HOLD_DAYS:
        return None
    try:
        data, wb = _prepare_with_warmup(data_agent, spec.get("security_id", ""), start, end, spec)
        m = executor.run({**spec, "window_start": start, "window_end": end}, data, warmup_bars=wb)
        oor_sharpe = float(m.get("sharpe_annual", 0.0))
    except Exception as exc:
        return {"note": "decay backtest failed", "error": str(exc), "period": [start, end]}
    retained = round(oor_sharpe / in_regime_sharpe, 3) if in_regime_sharpe > 0 else None
    return {"out_of_regime_sharpe": round(oor_sharpe, 3), "retained_fraction": retained, "period": [start, end]}


def _compute_regime_decay(spec, in_regime_sharpe, data_agent, executor, window_start, window_end) -> dict:
    """C2/F-7 + P2-4 — how much edge persists OUTSIDE the regime, on a slice just BEFORE window_start
    AND just AFTER window_end (the fade-in/out shape). The after-slice only if data exists after
    window_end (a regime may run to ~now → before-only). Characterization ONLY (never validation).
    Never raises into the loop."""
    env_start, env_end = _env_bounds()
    before = _slice_edge(spec, data_agent, executor, env_start, window_start, in_regime_sharpe)
    after = _slice_edge(spec, data_agent, executor, window_end, env_end, in_regime_sharpe)
    if before is None and after is None:
        return {"note": "no sufficient out-of-regime period"}
    return {
        "in_regime_sharpe": round(float(in_regime_sharpe), 3),
        "before": before,          # slice just before the regime (fade-in) — None if too short
        "after": after,            # slice just after the regime (fade-out) — None if no post-window data
    }


def _sidak_t_star(k: int) -> float:
    """H18/D6 — validation t* corrected for reusing the SAME hold-out across k surfaced ideas.

    The regime hold-out is peeked at once per surfaced candidate; held at a fixed 1.65 bar the
    family-wise false-validation rate inflates (~64% over 20 independent peeks). Šidák keeps it near
    the intended 5%: per-test ``α_k = 1-(1-0.05)^(1/k)`` and ``t* = Φ⁻¹(1-α_k)``. Clamped to never
    fall below the single-test bar VALIDATE_T, so reuse only ever TIGHTENS the bar (k=1 ⇒ VALIDATE_T,
    more peeks ⇒ a higher t*)."""
    from statistics import NormalDist
    k = max(1, int(k))
    alpha_k = 1.0 - (1.0 - 0.05) ** (1.0 / k)
    return max(VALIDATE_T, float(NormalDist().inv_cdf(1.0 - alpha_k)))


def _run_regime_holdout(spec, data_agent, executor, train_end, window_end, *,
                        t_star: float = VALIDATE_T) -> dict:
    """P2 — within-regime forward-slice validation. Select-on-train: the idea was surfaced on the
    train slice; here we test whether the edge PERSISTS on the unseen final hold-out. A pass earns
    ``regime_validated``; a collapse ``regime_failed``; a too-thin slice stays ``unvalidated``
    (unvalidatable, not a failure). Uses a DEDICATED stricter bar (P2-R4), NOT the selection rigor;
    ``t_star`` may be raised above VALIDATE_T by the caller to correct for hold-out reuse (H18/D6).
    Local backtest (no LLM). Never raises into the loop."""
    if not train_end or _days(train_end, window_end) < MIN_HOLD_DAYS:
        return {"status": "unvalidated", "reason": "no usable hold-out slice"}
    try:
        data, wb = _prepare_with_warmup(data_agent, spec.get("security_id", ""), train_end, window_end, spec)
        m = executor.run({**spec, "window_start": train_end, "window_end": window_end}, data, warmup_bars=wb)
    except Exception as exc:
        return {"status": "unvalidated", "reason": "hold-out backtest failed", "error": str(exc)}
    n = int(m.get("n_trades", 0))
    tr = m.get("trade_returns") or []            # executor.run returns trade_returns (executor.py:109)
    if n < VALIDATE_MIN_TRADES or len(tr) < 2:   # too thin to VALIDATE (P2-R4) — unvalidatable, NOT a failure
        return {"status": "unvalidated",
                "reason": f"hold-out too thin to validate ({n} < {VALIDATE_MIN_TRADES} trades)",
                "holdout_period": [train_end, window_end], "holdout_trades": n}
    from src.backend.backtesting.gates.basic_gates import per_trade_t
    t = per_trade_t(tr)                          # shared helper — same math as the activity gate
    passed = t >= t_star                          # positive + significant at the (reuse-corrected) bar
    return {"status": "regime_validated" if passed else "regime_failed",
            "holdout_period": [train_end, window_end], "holdout_trades": n,
            "holdout_t": round(float(t), 3), "t_star": round(float(t_star), 3),
            "holdout_sharpe": round(float(m.get("sharpe_annual", 0.0)), 3)}


# ── OOS lockbox helper ────────────────────────────────────────────────

class _PromotionToken:
    """Lightweight promotion token (avoids sqlalchemy import for lockbox)."""

    def __init__(self, approver: str, strategy_hash: str, lineage_id: str):
        self.token_id = f"promo_{uuid.uuid4().hex[:12]}"
        self.approver = approver
        self.strategy_hash = strategy_hash
        self.lineage_id = lineage_id
        self.approved_at = datetime.now(timezone.utc)


def _oos_verdict(m: dict) -> Any:
    """D5 / H3 — the real OOS pass bar.

    The old bar was sign-only (``sharpe_annual > 0 and total_return > 0``): a single lucky trade
    passed. The honest bar requires a real trade sample, per-trade significance at the validation
    ``t*``, and a positive edge *over buy-and-hold* (beating a flat long, not just being positive).
    Too few trades is UNEVALUATED — 'we don't know' — never a FAIL (model-honesty principle).
    """
    from src.backend.backtesting.gates.basic_gates import per_trade_t
    from src.backend.backtesting.lockbox.service import OOSOutcome

    n = int(m.get("n_trades", 0))
    tr = m.get("trade_returns") or []
    if n < OOS_MIN_TRADES or len(tr) < 2:
        return OOSOutcome.UNEVALUATED            # too thin to judge — not a failure
    t = per_trade_t(tr)                          # shared helper — same math as the activity gate
    excess = float(m.get("total_return", 0.0)) - float(m.get("buy_hold_return", 0.0))
    passed = (t >= VALIDATE_T) and (excess > 0.0)
    return OOSOutcome.PASS if passed else OOSOutcome.FAIL


def _record_oos(state: ResearchState, candidate: Candidate, outcome_value: str,
                lineage_id: str, emit: Any) -> None:
    """Append the OOS verdict to state (last-wins per hash for the trust badge) and emit it."""
    state.oos_results.append(OOSResult(
        strategy_hash=candidate.strategy_hash,
        lineage_id=lineage_id,
        outcome=outcome_value,
        evaluated_at=datetime.now(timezone.utc).isoformat(),
    ))
    emit("oos_result", {"strategy_hash": candidate.strategy_hash, "outcome": outcome_value})


def _run_oos_lockbox(
    lockbox: Any,
    candidate: Candidate,
    spec: dict,
    state: ResearchState,
    data_agent: DataAgentProtocol,
    executor: ExecutorProtocol,
    emit: Any,
    lineage_tracker: LineageTracker | None = None,
) -> None:
    """Run OOS lockbox evaluation for a candidate. Budget-exempt: does NOT consume a run.

    H14: the budget and terminal result are keyed on the lineage ROOT, so mutated children of the
    same hypothesis share one scarce OOS allowance — a fresh per-iteration lineage would hand every
    candidate its own untouched budget, defeating the lockbox. H16: a candidate that already has a
    terminal verdict recovers it instead of re-raising AlreadyEvaluatedError (which left it PENDING
    forever). H3/H17: the bar is significance-based, and an unevaluable candidate is UNEVALUATED,
    never a terminal FAIL.
    """
    from src.backend.backtesting.lockbox.service import OOSOutcome

    # H14: root the budget/token on the lineage root (one shared family allowance).
    budget_lineage = state.current_lineage_id
    if lineage_tracker is not None:
        root = lineage_tracker.get_root(state.current_lineage_id)
        if root is not None:
            budget_lineage = root.lineage_id

    # H16: recover a prior terminal verdict rather than re-evaluating (or re-raising).
    prior = lockbox.get_result(candidate.strategy_hash)
    if prior is not None:
        _record_oos(state, candidate, prior.value, budget_lineage, emit)
        return

    lockbox.ensure_budget(budget_lineage)
    token = _PromotionToken(
        approver="auto",
        strategy_hash=candidate.strategy_hash,
        lineage_id=budget_lineage,
    )

    # Build an OOS backtest callable for the lockbox: the window runs from the IS window_end to the
    # latest available data (H15 — the live envelope, never a hardcoded literal that goes stale).
    # H17: infra failures are allowed to PROPAGATE — the lockbox maps them to UNEVALUATED, not FAIL.
    def _oos_backtest() -> Any:
        oos_start = spec.get("window_end") or _env_bounds()[0]
        oos_end = _env_bounds()[1]
        oos_spec = {**spec, "window_start": oos_start, "window_end": oos_end}
        oos_data, oos_wb = _prepare_with_warmup(
            data_agent, state.current_asset, oos_start, oos_end, oos_spec,
        )
        oos_metrics = executor.run(oos_spec, oos_data, warmup_bars=oos_wb)
        return _oos_verdict(oos_metrics)

    outcome = lockbox.evaluate(token, run_oos_backtest=_oos_backtest)
    _record_oos(state, candidate, outcome.value, budget_lineage, emit)

    if outcome is OOSOutcome.FAIL:
        logger.info("OOS FAIL for %s — terminal.", candidate.strategy_hash[:16])
    elif outcome is OOSOutcome.UNEVALUATED:
        logger.info("OOS UNEVALUATED for %s — retryable (thin sample or data outage).",
                    candidate.strategy_hash[:16])


# ── The Loop ──────────────────────────────────────────────────────────

async def research_loop(
    state: ResearchState,
    strategist: StrategistProtocol,
    executor: ExecutorProtocol,
    gatekeeper: GatekeeperProtocol,
    critic: CriticProtocol,
    data_agent: DataAgentProtocol,
    *,
    orchestrator: OrchestratorProtocol | None = None,
    lockbox: Any = None,  # OOSLockboxService or None
    lineage_tracker: LineageTracker | None = None,
    budget_controller: AgentBudgetController | None = None,
    on_event: Any = None,  # callback for UI/logging events
    control: Any = None,  # callable() -> "run"|"pause"|"stop"|"stop_report" (A-9)
    enable_leakage_canary: bool = True,  # M22: run the leakage canary on survivors (re-runs on synthetics)
) -> ResearchState:
    """Run the autonomous research loop until budget exhausted or goal met.

    The branch decision (continue / next_asset / done) is centralised in the
    Director (single decision point per iteration, D-1). OOS validation runs
    automatically in the candidate branch before the Director decides (C1).
    """
    # Defaults for optional components.
    if orchestrator is None:
        orchestrator = RuleBasedOrchestrator()
    if lineage_tracker is None:
        lineage_tracker = LineageTracker()
    if budget_controller is None:
        budget_controller = AgentBudgetController()

    oos_enabled = lockbox is not None
    # T1 — single source of truth: the Director's OOS-awareness == lockbox presence.
    if hasattr(orchestrator, "config"):
        orchestrator.config.oos_enabled = oos_enabled
    max_iterations = state.budget.max_runs * 3 + 10        # T6 — backstop

    # Track Sharpe values across iterations. _sharpe_values stays ANNUALIZED for the
    # "sharpe_distribution" telemetry; _period_sharpe_values is PER-PERIOD and feeds the DSR
    # multiplicity variance + trial count (H1/M25 — the two must share per-period units and scope).
    _sharpe_values: list[float] = []
    _period_sharpe_values: list[float] = []

    def emit(event_type: str, payload: dict | None = None):
        if on_event:
            on_event(event_type, payload or {})

    # ── Phase 1: GOAL_RECEIVED ────────────────────────────────────
    state.phase = ResearchPhase.GOAL_RECEIVED
    emit("goal_received", {"goal": state.goal.goal_text, "assets": state.goal.asset_pool})

    # Initialize asset queue if needed.
    if not state.current_asset and state.asset_queue:
        state.advance_asset()
    elif not state.current_asset and state.goal.asset_pool:
        state.asset_queue = list(state.goal.asset_pool)
        state.advance_asset()

    # Early exit: no assets to research.
    if not state.current_asset:
        state.phase = ResearchPhase.STOPPED
        state.error_message = "No assets to research"
        state.stop_reason = "no_assets"
        emit("loop_finished", {"phase": state.phase, "reason": "no_assets"})
        return state

    # Create initial lineage for the first asset.
    if not state.current_lineage_id:
        lineage = lineage_tracker.create_root(declared_by="orchestrator")
        state.current_lineage_id = lineage.lineage_id

    emit("loop_started", {"asset": state.current_asset})

    _prev_hypothesis_template: str = ""

    while True:
        # ── T6: hard iteration backstop (skipped/error iterations consume no run) ──
        if state.total_iterations >= max_iterations:
            state.stop_reason = "iteration_cap"
            break

        # ── Cooperative control (A-9): pause/stop checked each iteration ──
        if control is not None:
            while control() == "pause":
                await asyncio.sleep(0.4)
            if control() in ("stop", "stop_report"):
                state.stop_reason = "stopped_by_user"
                state.error_message = state.error_message or "Stopped by Director"
                break

        state.lineage_nodes = lineage_tracker.serialize()  # ATSX-26: live lineage tree
        state.total_iterations += 1
        state.attempts_on_current_asset += 1

        outcome: str | None = None
        sharpe: float = 0.0
        candidate: Candidate | None = None
        spec: dict[str, Any] = {}
        metrics: dict[str, Any] = {}
        artifacts: RunArtifacts | None = None
        regime_analysis: dict[str, Any] = {}
        gate_report: dict[str, Any] = {}
        hypothesis: Hypothesis | None = None

        # ── Phase 2: STRATEGIST_THINKS ────────────────────────────
        state.phase = ResearchPhase.PROPOSING
        emit("proposing", {"asset": state.current_asset, "iteration": state.total_iterations})

        try:
            registry_summary = {
                "total_iterations": state.total_iterations,
                "candidates_found": len(state.candidates),
                "consecutive_failures": state.consecutive_failures,
                "current_asset": state.current_asset,
                "current_lineage_id": state.current_lineage_id,
                "sharpe_distribution": _sharpe_values[-20:] if _sharpe_values else [],
            }

            hypothesis, spec = await strategist.propose(
                asset=state.current_asset,
                strategy_families=state.goal.strategy_families,
                failure_context=state.failure_context[-10:],  # last 10 failures
                registry_summary=registry_summary,
            )
            state.hypotheses.append(hypothesis)

            # ── Lineage tracking ──
            # New template = new hypothesis = new root lineage; same = child (mutation).
            if hypothesis.proposed_template_id != _prev_hypothesis_template:
                lineage = lineage_tracker.create_root(
                    strategy_hash=spec.get("strategy_hash"), declared_by="strategist")
                state.current_lineage_id = lineage.lineage_id
            else:
                try:
                    lineage = lineage_tracker.create_child(
                        parent_lineage_id=state.current_lineage_id,
                        strategy_hash=spec.get("strategy_hash"), declared_by="strategist")
                    state.current_lineage_id = lineage.lineage_id
                except ValueError:
                    lineage = lineage_tracker.create_root(
                        strategy_hash=spec.get("strategy_hash"), declared_by="strategist")
                    state.current_lineage_id = lineage.lineage_id

            _prev_hypothesis_template = hypothesis.proposed_template_id

        except Exception as exc:
            logger.error("Strategist failed: %s", exc, exc_info=True)
            outcome = "error"
            state.consecutive_errors += 1

        # ── Phase 2b: agent/hypothesis budget guard (T2) ──
        if outcome is None and hypothesis is not None:
            is_mutation = hypothesis.proposed_template_id == _prev_hypothesis_template
            try:
                budget_controller.check_and_consume(
                    agent_id="strategist",
                    hypothesis_id=hypothesis.hypothesis_id,
                    lineage_id=state.current_lineage_id,
                    is_mutation_after_failure=is_mutation and state.consecutive_failures > 0,
                )
            except BudgetExceededError as exc:
                logger.warning("Agent budget exceeded: %s", exc)
                outcome = "skipped"  # neutral: no counter change, attempts still incremented

        # ── Phase 3: DATA_PREPARED ────────────────────────────────
        snapshot = None
        if outcome is None:
            state.phase = ResearchPhase.DATA_PREPARING
            try:
                raw_data = data_agent.prepare(
                    security_id=state.current_asset,
                    window_start=spec.get("window_start", "2010-01-01"),
                    window_end=spec.get("window_end", "2023-12-31"),
                )
                # H24: attach the provider's REAL bias flags (single source of truth in the capability
                # registry) — the gate reads `survivorship_bias`, which the old hand-rolled
                # {"prototype_data": True} never set, so the survivorship check was silently inert.
                from src.backend.backtesting.registry.capabilities import get_bias_flags
                snapshot = DataSnapshot(
                    security_id=state.current_asset,
                    window_start=spec.get("window_start", "2010-01-01"),
                    window_end=spec.get("window_end", "2023-12-31"),
                    provider=spec.get("provider", "yfinance"),
                    bias_flags=get_bias_flags(spec.get("provider", "yfinance")),
                    data=raw_data,
                )
                emit("data_prepared", {
                    "security_id": state.current_asset,
                    "content_hash": snapshot.content_hash,
                    "n_bars": snapshot.n_bars,
                })
            except Exception as exc:
                logger.error("Data preparation failed: %s", exc, exc_info=True)
                outcome = "error"
                state.consecutive_errors += 1

        # ── Phase 4: BACKTEST_RUN ─────────────────────────────────
        if outcome is None:
            state.phase = ResearchPhase.EXECUTING
            try:
                metrics = executor.run(spec, snapshot.data)
            except Exception as exc:
                logger.error("Executor failed: %s", exc, exc_info=True)
                state.budget.consume_run()
                outcome = "error"
                state.consecutive_errors += 1
                _record_failure(state, FailureContext(
                    strategy_hash=spec.get("strategy_hash", ""),
                    template_id=spec.get("template_id", ""),
                    params=spec.get("params", {}),
                    security_id=state.current_asset,
                    hypothesis_id=hypothesis.hypothesis_id,
                    failure_reason=f"execution_error: {exc}",
                ))

        if outcome is None:
            state.budget.consume_run()

            returns = metrics.get("returns")
            regime_analysis = _compute_regime_analysis(returns)
            artifacts = RunArtifacts(
                run_id=metrics.get("run_id", f"run_{uuid.uuid4().hex[:8]}"),
                strategy_hash=spec.get("strategy_hash", ""),
                template_id=spec.get("template_id", ""),
                params=spec.get("params", {}),
                security_id=state.current_asset,
                metrics=metrics,
                returns=returns,
                equity_curve=metrics.get("equity_curve", []),
                benchmark={
                    "buy_hold_return": metrics.get("buy_hold_return", 0.0),
                    "buy_hold_sharpe": metrics.get("buy_hold_sharpe", 0.0),
                    "buy_hold_max_drawdown": metrics.get("buy_hold_max_drawdown", 0.0),  # M19: Path B was dead without it
                },
                regime_analysis=regime_analysis,
            )

            sharpe = metrics.get("sharpe_annual", 0.0)
            _sharpe_values.append(sharpe)
            _sr_period = _period_sharpe(returns)  # H1: per-period Sharpe for DSR multiplicity
            if _sr_period is not None:
                _period_sharpe_values.append(_sr_period)
            emit("execute", {
                "strategy_hash": spec.get("strategy_hash", ""),
                "sharpe_annual": sharpe,
                "n_trades": metrics.get("n_trades", 0),
            })

            # ── Phase 5: GATES_EVALUATED ──
            state.phase = ResearchPhase.GATING
            # H1/M25: per-period trial-Sharpe variance + a trial count that reflects only
            # gate-evaluable trials (not state.total_iterations, which counts errors/skips).
            _dsr_n_trials, sr_variance, _sr_defaulted = _dsr_registry_inputs(_period_sharpe_values)
            gatekeeper.update_registry_stats(
                _dsr_n_trials, sr_variance, variance_defaulted=_sr_defaulted
            )
            # M22: a closure that re-runs THIS candidate's spec on arbitrary OHLCV — the leakage
            # canary runs it on zero-drift synthetics (only reached by survivors of the cheaper gates).
            _canary_run_fn = (
                (lambda df: executor.run(spec, df).get("returns"))
                if enable_leakage_canary else None
            )
            try:
                gate_report = gatekeeper.evaluate(
                    metrics=metrics,
                    returns=returns,
                    context={
                        "strategy_hash": spec.get("strategy_hash", ""),
                        "template_id": spec.get("template_id", ""),
                        "bias_flags": snapshot.bias_flags,
                        "benchmark": artifacts.benchmark,
                        "regime_analysis": regime_analysis,
                        "content_hash": snapshot.content_hash,
                        "run_strategy_fn": _canary_run_fn,
                    },
                )
            except Exception as exc:
                logger.error("Gatekeeper failed: %s", exc, exc_info=True)
                gate_report = {"passed": False, "first_failed_gate": "error", "error": str(exc)}

            _gate_passed = gate_report.get("passed", False)
            _gate_ev: dict[str, Any] = {"passed": _gate_passed, "strategy_hash": spec.get("strategy_hash", "")}
            if not _gate_passed:
                _failed = gate_report.get("first_failed_gate", "unknown")
                _gate_ev["failed_gate"] = _failed
                for _r in gate_report.get("results", []):
                    if _r.get("gate_id") == _failed:
                        _gate_ev["value"] = _r.get("value")
                        _gate_ev["threshold"] = _r.get("threshold")
                        break
            emit("gate_result", _gate_ev)

            if not _gate_passed:
                _record_failure(state, FailureContext(
                    strategy_hash=spec.get("strategy_hash", ""),
                    template_id=spec.get("template_id", ""),
                    params=spec.get("params", {}),
                    security_id=state.current_asset,
                    hypothesis_id=hypothesis.hypothesis_id,
                    failed_gate=gate_report.get("first_failed_gate", "unknown"),
                    gate_details=gate_report,
                    failure_reason="gate_failure",
                ))
                state.consecutive_failures += 1
                outcome = "gate_fail"

        # ── Phase 6: CRITIC_REVIEW ────────────────────────────────
        if outcome is None:
            state.phase = ResearchPhase.CRITIQUING
            try:
                # Critic does NOT receive hypothesis reasoning (per spec Part 5).
                critique = await critic.review(
                    spec=spec,
                    metrics={**metrics, "benchmark": artifacts.benchmark, "regime_analysis": regime_analysis},
                    gate_report=gate_report,
                )
            except Exception as exc:
                # CRITICAL: critic failure must NOT silently accept.
                logger.error("Critic failed: %s", exc, exc_info=True)
                critique = {"recommendation": "investigate", "error": str(exc)}

            emit("critique", {"recommendation": critique.get("recommendation")})

            _rec = critique.get("recommendation")
            _critic_no = _rec in ("reject", "investigate")
            # Robustness: reject/investigate KILL. Regime (idea-surfacing): the Critic only LOWERS confidence,
            # never kills — so a regime idea falls through to the candidate branch (DG-1).
            if _critic_no and getattr(state, "mode", "robustness") != "regime":
                _record_failure(state, FailureContext(
                    strategy_hash=spec.get("strategy_hash", ""),
                    template_id=spec.get("template_id", ""),
                    params=spec.get("params", {}),
                    security_id=state.current_asset,
                    hypothesis_id=hypothesis.hypothesis_id,
                    critic_notes=critique.get("reasoning", ""),
                    failure_reason="critic_rejection",
                ))
                state.consecutive_failures += 1
                outcome = "critic_reject"
            else:
                candidate = Candidate(
                    strategy_hash=spec.get("strategy_hash", ""),
                    run_id=artifacts.run_id,
                    template_id=spec.get("template_id", ""),
                    params=spec.get("params", {}),
                    security_id=state.current_asset,
                    lineage_id=state.current_lineage_id,   # M47: capture the lineage at creation, not at flush

                    sharpe_annual=sharpe,
                    total_return=metrics.get("total_return", 0.0),
                    max_drawdown=metrics.get("max_drawdown", 0.0),
                    n_trades=metrics.get("n_trades", 0),
                    win_rate=metrics.get("win_rate", 0.0),           # P1-09
                    profit_factor=metrics.get("profit_factor", 0.0),  # P1-09
                    gate_report_summary=gate_report,
                    critic_confidence=critique.get("confidence", "low"),
                    critique=critique,
                    regime_analysis=regime_analysis,
                    benchmark=artifacts.benchmark,
                    equity_curve=_downsample_curve(artifacts.equity_curve),
                    hypothesis_id=state.hypotheses[-1].hypothesis_id if state.hypotheses else "",
                )
                if getattr(state, "mode", "robustness") == "regime":
                    # Idea-surfacing firewall: regime ideas are UNVALIDATED; the confidence tier aggregates the
                    # sample-tier (activity) MINUS one level per soft-failed quality gate (the weakness profile).
                    _tier = ""
                    _soft_fails = []
                    for _r in gate_report.get("results", []):
                        _gid = _r.get("gate_id")
                        if _gid == "minimum_activity":
                            _d = _r.get("details") or {}
                            _tier = "thin" if _d.get("low_confidence") else _d.get("tier", "")
                        # In a PASSED report every FAIL is a SOFT quality gate (HARD fails → not passed);
                        # exclude the activity gate (its tier is handled above). Format-independent.
                        if "FAIL" in str(_r.get("status", "")).upper() and _gid != "minimum_activity":
                            _soft_fails.append({"gate": _gid, "value": _r.get("value"),
                                                "threshold": _r.get("threshold"),
                                                "reason": (_r.get("details") or {}).get("reason", "")})
                    candidate.weaknesses = _soft_fails
                    _LEVELS = ["very_low", "low", "moderate"]   # moderate = best a regime idea gets (UNVALIDATED)
                    _base = 2 if _tier == "adequate" else 1
                    candidate.validation_status = "unvalidated"
                    candidate.confidence = _LEVELS[max(0, _base - len(_soft_fails))]
                    if _critic_no:   # DG-1: the Critic only LOWERS in regime (reject→very_low, investigate→low)
                        candidate.confidence = "very_low" if _rec == "reject" else "low"
                        candidate.weaknesses.append({"gate": "critic",
                                                     "reason": (critique.get("reasoning") or "")[:200]})
                    # C2: out-of-regime decay characterization (separate from validation).
                    candidate.decay = _compute_regime_decay(
                        spec, sharpe, data_agent, executor, state.window_start, state.window_end)
                    # P2: within-regime forward-slice hold-out — upgrades UNVALIDATED → regime_validated
                    # where earned (select-on-train; runs BEFORE the cap, inline on every surfaced idea, F-7).
                    # H18/D6: the hold-out is reused on every surfaced idea against the SAME slice, so the
                    # bar is Šidák-corrected for that peek count — validating on a much-reused hold-out gets
                    # progressively harder. Only an actual test (not a too-thin slice) consumes a peek.
                    _ho_key = f"{state.current_asset}|{getattr(state, 'train_end', '')}|{state.window_end}"
                    _ho_prior = state.holdout_eval_counts.get(_ho_key, 0)
                    _hold = _run_regime_holdout(
                        spec, data_agent, executor, getattr(state, "train_end", ""), state.window_end,
                        t_star=_sidak_t_star(_ho_prior + 1))
                    if _hold["status"] in ("regime_validated", "regime_failed"):  # a real test ran
                        state.holdout_eval_counts[_ho_key] = _ho_prior + 1
                        _hold["holdout_peek_index"] = _ho_prior + 1
                    candidate.holdout = _hold
                    candidate.validation_status = _hold["status"]     # overrides the "unvalidated" default
                    if _hold["status"] == "regime_failed":            # F-5: floored + a weakness
                        candidate.confidence = "very_low"
                        candidate.weaknesses.append({
                            "gate": "holdout",
                            "reason": f"edge collapsed out-of-fit (t={_hold.get('holdout_t')} "
                                      f"< t*={_hold.get('t_star')})",
                        })
                    # regime_validated does NOT raise the confidence tier — it is a STATUS (P2-7); the
                    # /candidates ranking puts validated first.
                outcome = "candidate"

        # Every path above sets exactly one outcome (T13).
        assert outcome is not None, "every iteration must set an outcome"

        # ── Post-trial bookkeeping (only for trials that produced metrics) ──
        if outcome in ("gate_fail", "critic_reject", "candidate"):
            state.consecutive_errors = 0
            state.best_sharpe_on_asset.append(
                max(sharpe, state.best_sharpe_on_asset[-1]) if state.best_sharpe_on_asset else sharpe)

        if outcome == "candidate":
            state.candidates.append(candidate)
            state.consecutive_failures = 0
            emit("candidate_found", {"strategy_hash": spec.get("strategy_hash", "")})
            # ── C1: auto-OOS BEFORE the Director decides ──
            if oos_enabled:
                state.phase = ResearchPhase.OOS_EVALUATING
                try:
                    _run_oos_lockbox(lockbox, candidate, spec, state, data_agent, executor, emit,
                                     lineage_tracker)
                except Exception as exc:
                    logger.error("OOS lockbox error: %s", exc, exc_info=True)

        # ── Single decision point (D-1) ──
        state.phase = ResearchPhase.DECIDING
        decision = await orchestrator.decide(state, outcome)
        emit("orchestrator_decision",
             {"decision": decision.decision, "reason": decision.reason, "evidence": decision.evidence})

        if decision.decision == "done":
            state.stop_reason = decision.reason
            break
        if decision.decision == "next_asset":
            if not state.advance_asset():
                state.stop_reason = decision.reason
                break
            _prev_hypothesis_template = ""
            lineage = lineage_tracker.create_root(declared_by="orchestrator")
            state.current_lineage_id = lineage.lineage_id
        # "continue" -> next iteration

    # ── REPORTING + final state ───────────────────────────────────
    state.lineage_nodes = lineage_tracker.serialize()  # final lineage tree
    if not state.stop_reason:
        state.stop_reason = (
            "goal_met"
            if state.validated_count(oos_enabled) >= state.goal.target_candidates
            else "ended"
        )
    state.phase = ResearchPhase.REPORTING
    emit("reporting", {"candidates": len(state.candidates)})

    if state.stop_reason == "goal_met":
        state.phase = ResearchPhase.COMPLETED
    else:
        state.phase = ResearchPhase.STOPPED
        state.error_message = state.error_message or state.stop_reason

    emit("loop_finished", {
        "phase": state.phase,
        "reason": state.stop_reason,
        "candidates": len(state.candidates),
        "iterations": state.total_iterations,
        "oos_results": len(state.oos_results),
    })

    return state
