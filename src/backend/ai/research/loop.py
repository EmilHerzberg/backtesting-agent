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
import zlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal, Protocol

import numpy as np

from src.backend.ai.research.budgets import AgentBudgetController, BudgetExceededError
from src.backend.ai.research.state import (
    Candidate,
    DataSnapshot,
    FailureContext,
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
    skip_breaker: int = 6                # M48: rotate/stop after this many consecutive "skipped" iterations
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
            "consecutive_skips": state.consecutive_skips,
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
        # R3b (M48) — skip breaker: a run of consecutive "skipped" iterations (the strategist keeps
        # re-proposing an exhausted hypothesis family, every proposal blocked by the budget/dedup guard)
        # makes zero forward progress yet spends a paid strategist call each spin. Rotate to the next asset,
        # or stop on the last/only one, rather than spinning to the T6 iteration backstop.
        if state.consecutive_skips >= cfg.skip_breaker:
            return D("next_asset", "skip_breaker") if queue_non_empty else D("done", "skip_breaker_last")
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

def _compute_regime_analysis(market_returns: Any, strategy_returns: Any = None) -> dict[str, Any]:
    """Split the window into three sub-periods and label each bull/bear/sideways.

    M60: the regime LABEL comes from the ASSET's close-to-close (MARKET) returns — NOT the strategy's
    own equity. The old code labeled from the strategy's equity, so a flat market where the strategy
    made money was mislabeled 'bull', and the critic then rejected for 'regime concentration' on a
    fabricated market label. Each segment reports the market regime + the strategy's return/Sharpe in
    that window (the honest quantity for the regime-dependence check)."""
    if market_returns is None or len(market_returns) < 60:
        return {}

    mkt = np.asarray(market_returns, dtype=np.float64)
    strat = np.asarray(strategy_returns, dtype=np.float64) if strategy_returns is not None else None
    n = len(mkt)
    regimes = {}

    for i, label in enumerate(["early", "mid", "late"]):
        start = i * (n // 3)
        end = min(start + (n // 3), n)
        seg = mkt[start:end]
        if len(seg) == 0:
            continue
        mkt_cum = float(np.prod(1 + seg) - 1)
        regime_type = "bull" if mkt_cum > 0.05 else ("bear" if mkt_cum < -0.05 else "sideways")
        # The strategy's performance IN this market window — reported ONLY when the strategy series aligns
        # 1:1 with the market series. TI-5: on a length mismatch DON'T substitute the market segment (that
        # silently reports the MARKET's return/Sharpe as if they were the strategy's); mark the strategy
        # numbers unavailable and report a neutral 0.0 (safe for the critic's numeric regime checks).
        _aligned = strat is not None and len(strat) == n
        if _aligned:
            s_seg = strat[start:end]
            s_cum = float(np.prod(1 + s_seg) - 1)
            s_sharpe = float(s_seg.mean() / s_seg.std() * np.sqrt(252)) if s_seg.std() > 0 else 0.0
        else:
            s_cum = 0.0
            s_sharpe = 0.0
        regimes[label] = {
            "type": regime_type,                 # from the MARKET
            "market_return": round(mkt_cum, 4),
            "return": round(s_cum, 4),           # the STRATEGY's return in this window (0.0 if unavailable)
            "sharpe": round(s_sharpe, 2),
            "strategy_available": _aligned,
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
VALIDATE_T = 1.65            # P2-R4: ~95% one-sided; stricter than quick/medium selection t*
DECAY_SHARPE_FLOOR = 0.10    # M29: below this an in-regime Sharpe is too small for an honest retained-ratio
# NOTE: the legacy fixed-20 bar (VALIDATE_MIN_TRADES / OOS_MIN_TRADES) is gone — the trade bar is now the
# frequency-scaled `scaled_min_trades` (ceil `confidence.VALIDATE_CEIL`=20, floors REGIME_FLOOR/OOS_FLOOR).
# D2 (locked owner decision): "validated" = risk-adjusted skill. The total-return-vs-fee-paying-buy-and-hold
# comparison is computed + reported ALWAYS; it gates the OOS PASS only when this explicit toggle is on.
OOS_TOTAL_RETURN_FLOOR = False


def _days(a: str, b: str) -> int:
    """Calendar days between two ISO dates (module-level: shared by decay + hold-out + train-split)."""
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except Exception:
        return 0


def _seed_from_hash(strategy_hash: str) -> int:
    """A stable, non-negative bootstrap seed DERIVED FROM the strategy fingerprint (valconf CI seeding).

    This makes each strategy's Sharpe CI a reproducible PROPERTY OF THE STRATEGY: identical across every run
    (never wiggles because a different run seed was chosen) and decorrelated from other strategies' draws. A
    flat shared seed (0) is reproducible too, but couples all candidates' draws to one RNG stream; tying the
    seed to the *run* seed would instead make the same strategy's band shift between runs — the opposite of
    what a confidence band should do. crc32 is deterministic and JSON-safe (a uint32, well within the RNG range).
    """
    return int(zlib.crc32((strategy_hash or "").encode("utf-8")) & 0xFFFFFFFF)


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


def _dsr_registry_inputs(period_sharpes: list[float],
                         trial_lengths: list[int] | None = None,
                         ) -> tuple[int, float, bool, float]:
    """Deflated-Sharpe multiplicity inputs (H1 / M25 / M24 / PF4).

    Returns ``(n_trials, trial_sr_variance, variance_defaulted, trial_median_t)`` where N is the
    number of gate-evaluable trials (those that produced a measurable per-period Sharpe) and the
    variance is the per-period trial-Sharpe variance (ddof=1) — the two share one scope, so the
    expected-max-Sharpe hurdle sits on the same footing as the per-period ``sr_hat`` the gate
    computes. ``trial_median_t`` is the median trial return-series length: the PF4 null-variance
    floor must sit on the TRIALS' clock (their null dispersion ~1/T_trial), not the candidate's.
    When fewer than two trials have been measured the variance cannot be estimated, so a floor is
    returned with ``variance_defaulted=True`` (M24). A MEASURED variance of exactly 0.0 (perfectly
    clustered trials) is returned as-is with ``variance_defaulted=False`` — the PF4 floor in the
    gate sets the bar and the verdict stays FIRM (review fix: the old path re-flagged it as
    'unmeasured' and leaked a provisional PASS on exactly the clustering extreme)."""
    n = len(period_sharpes)
    med_t = float(np.median(trial_lengths)) if trial_lengths else 0.0
    if n > 1:
        return n, float(np.var(period_sharpes, ddof=1)), False, med_t
    return n, 0.001, True, med_t


def _train_split(window_start: str, window_end: str) -> str | None:
    """P2 select-on-train: the ISO date splitting the regime window into train=[ws, split] +
    hold-out=[split, we]. Returns None when the window is too short to carve an honest hold-out
    (span < ~300d → the 4mo floor would exceed the 40% cap, P2-R2) — no split, stays UNVALIDATED
    (P2-5). The split is set from window LENGTH only. NOTE (M27, IMPLEMENTED — valconf): the hold-out trade
    bar is frequency-SCALED, not fixed. ``_run_regime_holdout`` passes the selection ``train_trades``/
    ``train_days`` to ``assess_confidence`` → ``scaled_min_trades(floor=REGIME_FLOOR=5, ceil=VALIDATE_CEIL=20)``,
    so a slow low-frequency template can earn ``regime_validated`` on as few as 5 hold-out trades. This function
    only carves the date boundary; the scaled bar is applied downstream (the observed hold-out Sharpe/t/CI are
    always reported regardless)."""
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
    # M29: `retained` is a ratio, so it blows up as the denominator → 0. Regime mode uses SOFT quality
    # gates (it never hard-fails a low-Sharpe idea), so an in-regime Sharpe of ~0.02 is routine — and
    # `0.5 / 0.02 = 25.0` renders as "2500% retained", self-deception the model-honesty principle forbids.
    # Only compute the ratio above a floor (and clamp it), and ALWAYS emit the signed delta, which stays
    # meaningful (and preserves sign) when the ratio is undefined — recovering the dropped negative-edge info.
    delta = round(oor_sharpe - in_regime_sharpe, 3)
    if in_regime_sharpe >= DECAY_SHARPE_FLOOR:
        retained = max(-2.0, min(2.0, round(oor_sharpe / in_regime_sharpe, 3)))
    else:
        retained = None                            # base too small (or non-positive) for an honest ratio
    return {"out_of_regime_sharpe": round(oor_sharpe, 3), "retained_fraction": retained,
            "retained_delta": delta, "period": [start, end]}


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
    """H18/D6 — validation t* tightened for reusing the SAME hold-out across surfaced ideas.

    The regime hold-out is peeked at once per surfaced candidate; held at a fixed 1.65 bar the
    false-validation rate inflates badly (~64% over 20 independent peeks). The k-th peek must clear
    ``t* = Φ⁻¹(1-α_k)`` with ``α_k = 1-(1-0.05)^(1/k)`` (the Šidák per-test level for k tests), clamped
    to never fall below the single-test bar VALIDATE_T — so reuse only ever TIGHTENS the bar
    (k=1 ⇒ VALIDATE_T, k=20 ⇒ ~2.80).

    HONEST SCOPE (review): this is an *online* per-peek escalation, NOT strict family-wise control.
    Because the k-th test is judged at α_k (an increasing bar) rather than every test at the final
    α_{k_final}, the realized family-wise false-validation rate is ~1-Π_j(1-α_j) ≈ 11% (k=5), 17%
    (k=20) — a large mitigation from the 64% fixed-bar baseline, but not the nominal 5%. Earlier-
    surfaced candidates keep the verdict they earned at their (looser) bar; they are not
    retro-adjudicated at the final k. The peek count is also per-RUN (in-memory), so re-running the
    same regime goal re-mines the slice from k=1 — a known residual (see PHASE2-3-REVIEW / H18)."""
    from statistics import NormalDist
    k = max(1, int(k))
    alpha_k = 1.0 - (1.0 - 0.05) ** (1.0 / k)
    return max(VALIDATE_T, float(NormalDist().inv_cdf(1.0 - alpha_k)))


def _run_regime_holdout(spec, data_agent, executor, train_end, window_end, *,
                        t_star: float = VALIDATE_T, train_trades: int = 0, train_days: float = 0,
                        seed: int = 0) -> dict:
    """P2 + M27/valconf — within-regime forward-slice validation, frequency-aware and graded.

    Select-on-train: the idea was surfaced on the train slice; here we test whether the edge PERSISTS on
    the unseen final hold-out. The trade bar SCALES to the strategy's own tempo (estimated from the train
    window) × the hold-out length, so a slow strategy isn't punished for being slow and a lucky few-trade
    slice can't certify. A real per-trade significance test at ``t_star`` (Šidák-reuse-corrected by the
    caller, H18) earns ``regime_validated`` (tier strong/moderate); a negative/collapsed edge is
    ``regime_failed``; anything else stays ``unvalidated`` — including a per-BAR evidence signal, which
    NEVER validates (R6). The observed Sharpe, t, sample sizes, tier, and a block-bootstrap CI are ALWAYS
    reported. Local backtest (no LLM). Never raises into the loop."""
    if not train_end or _days(train_end, window_end) < MIN_HOLD_DAYS:
        return {"status": "unvalidated", "confidence_tier": "inconclusive",
                "reason": "no usable hold-out slice", "holdout_period": [train_end, window_end]}
    try:
        data, wb = _prepare_with_warmup(data_agent, spec.get("security_id", ""), train_end, window_end, spec)
        m = executor.run({**spec, "window_start": train_end, "window_end": window_end}, data, warmup_bars=wb)
    except Exception as exc:
        return {"status": "unvalidated", "confidence_tier": "inconclusive",
                "reason": "hold-out backtest failed", "error": str(exc),
                "holdout_period": [train_end, window_end]}

    from src.backend.backtesting.engine.confidence import (
        REGIME_FLOOR,
        TIER_FAILED,
        TIER_MODERATE,
        TIER_STRONG,
        assess_confidence,
    )
    a = assess_confidence(
        train_trades=int(train_trades), train_days=float(train_days),
        holdout_days=float(_days(train_end, window_end)),
        test_trades=int(m.get("n_trades", 0)), trade_returns=m.get("trade_returns") or [],
        daily_returns=m.get("returns", []), exposure_time=float(m.get("exposure_time", 0.0) or 0.0),
        observed_sharpe=float(m.get("sharpe_annual", 0.0)), ppy=252.0, t_star=float(t_star),
        floor=REGIME_FLOOR, seed=int(seed),
        in_market_returns=m.get("returns_in_market"),   # valconf: edge-when-deployed Sharpe + CI
    )
    # tier → control status (§6). Only a per-trade strong/moderate VALIDATES; a real per-trade collapse
    # (negative/failed) is regime_failed; per-bar/weak/inconclusive stay unvalidated (per-bar never certifies).
    if a.tier in (TIER_STRONG, TIER_MODERATE):
        status = "regime_validated"
    elif a.tier == TIER_FAILED:
        status = "regime_failed"
    else:
        status = "unvalidated"
    return {
        "status": status, "confidence_tier": a.tier, "basis": a.basis,
        "holdout_period": [train_end, window_end], "holdout_trades": a.n_trades,
        "holdout_t": round(float(a.t_stat), 3), "t_star": round(float(t_star), 3),
        # holdout_sharpe = the headline (geometric/compounded) Sharpe. observed_sharpe = the Sharpe the tier's
        # positive-edge check actually keyed on (spec §5.5): the geometric headline on the per_trade validating
        # path (so it equals holdout_sharpe there), the ARITHMETIC daily Sharpe on the per_bar evidence path
        # (where it can differ in SIGN from the geometric headline — Jensen). NOTE: the block-bootstrap CI is a
        # sampling band on the ARITHMETIC Sharpe, so on the per_trade path it can sit slightly above the
        # geometric holdout_sharpe by ~σ²·ppy/2 — that gap is display-only and never moves a verdict (D8).
        "holdout_sharpe": round(float(m.get("sharpe_annual", 0.0)), 3),
        "observed_sharpe": round(float(a.observed_sharpe), 4),
        "n_bars_in_market": a.n_bars_in_market, "min_req_trades": a.min_req_trades,
        "ci_low": a.ci_low, "ci_high": a.ci_high, "ci_level": a.ci_level,
        # valconf in-market masking: the edge WHILE DEPLOYED (cash days excluded), same scale as holdout_sharpe.
        "in_market_sharpe": a.in_market_sharpe,
        "in_market_ci_low": a.in_market_ci_low, "in_market_ci_high": a.in_market_ci_high,
    }


# ── OOS lockbox helper ────────────────────────────────────────────────

class _PromotionToken:
    """Lightweight promotion token (avoids sqlalchemy import for lockbox)."""

    def __init__(self, approver: str, strategy_hash: str, lineage_id: str):
        self.token_id = f"promo_{uuid.uuid4().hex[:12]}"
        self.approver = approver
        self.strategy_hash = strategy_hash
        self.lineage_id = lineage_id
        self.approved_at = datetime.now(timezone.utc)


def _oos_verdict(m: dict, *, train_trades: int = 0, train_days: float = 0,
                 oos_days: float = 0, seed: int = 0) -> tuple[Any, Any]:
    """D5 / H3 + valconf/R5 + D2 — the OOS pass bar: frequency-aware, graded, RISK-ADJUSTED.

    Returns ``(OOSOutcome, ConfidenceAssessment, extras)``: the outcome is the control verdict the lockbox/
    budget/goal logic consumes; the assessment rides alongside so its tier + CI can be SURFACED for display
    (spec §5.6); ``extras`` carries the D2 benchmark comparison (excess Sharpe + fee-net excess total return)
    for the OOSResult/report — display evidence, never steering anything but the verdict rule below.

    The trade bar SCALES to the strategy's IS tempo × the OOS window length (floor ``OOS_FLOOR``), so a slow
    strategy over the long OOS window isn't auto-UNEVALUATED. The PASS/FAIL/UNEVALUATED contract:
      * PASS ⇐ a real per-trade significance test clears the (df-aware) bar AND the RISK-ADJUSTED edge beats
        buy-and-hold (excess Sharpe > 0 — D2; the old total-return arm was a beta bar, see OD7). With
        ``OOS_TOTAL_RETURN_FLOOR`` on, the fee-net total-return floor applies additionally (explicit product
        policy, off by default → report-only).
      * FAIL ⇐ a real per-trade test ran and the bar above was not met (TERMINAL).
      * UNEVALUATED ⇐ too thin for a per-trade test ('we don't know' — never a FAIL, model-honesty). A
        per-bar block-bootstrap CI is still computed as evidence, but per-bar NEVER produces a PASS (R6).
    """
    from src.backend.backtesting.engine.confidence import OOS_FLOOR, assess_confidence
    from src.backend.backtesting.lockbox.service import OOSOutcome

    a = assess_confidence(
        train_trades=int(train_trades), train_days=float(train_days), holdout_days=float(oos_days),
        test_trades=int(m.get("n_trades", 0)), trade_returns=m.get("trade_returns") or [],
        daily_returns=m.get("returns", []), exposure_time=float(m.get("exposure_time", 0.0) or 0.0),
        observed_sharpe=float(m.get("sharpe_annual", 0.0)), ppy=252.0, t_star=VALIDATE_T,
        floor=OOS_FLOOR, seed=int(seed),
        in_market_returns=m.get("returns_in_market"),   # valconf: edge-when-deployed Sharpe + CI
    )
    if a.basis != "per_trade":                   # too thin for a real significance test → not a failure
        return OOSOutcome.UNEVALUATED, a, {}
    if not bool(m.get("benchmark_available", True)):
        # M46 (review fix): an uncomputable benchmark must not masquerade as "benchmark with
        # Sharpe 0" — without a real buy-and-hold comparison the D2 excess-skill question is
        # unanswerable → honest absence (retryable), never a silently-degraded absolute-Sharpe PASS.
        return OOSOutcome.UNEVALUATED, a, {"benchmark_unavailable": True}
    # D2 (locked owner decision, reconciled plan §1): the PASS certifies RISK-ADJUSTED skill —
    # excess Sharpe over buy-and-hold — matching every upstream gate (DSR/ValConf). The old
    # total-return-vs-buy-and-hold arm was a beta bar in a skill bar's costume (OD7): it silently
    # failed genuine market-neutral / low-beta edges in bull markets. Known residual (conscious
    # choice, within D2's letter): a plain Sharpe DIFFERENCE is not beta-neutral — in a very
    # high-Sharpe bull window it can still fail true market-neutral skill; a regression alpha/IR
    # upgrade is a candidate for the FB4 phase, recorded in the Track-1 review.
    excess_sharpe = float(m.get("sharpe_annual", 0.0)) - float(m.get("buy_hold_sharpe") or 0.0)
    passed = bool(a.validates) and excess_sharpe > 0.0
    # D2's separate, explicitly-labelled total-return comparison: strategy net return vs a buy-and-
    # hold that ALSO pays its entry+exit commission (a real alternative costs money too). Report-only
    # by default; a hard product floor only via the explicit OOS_TOTAL_RETURN_FLOOR toggle.
    c = float(m.get("commission", 0.0) or 0.0)
    bh_net = (1.0 + float(m.get("buy_hold_return", 0.0))) * (1.0 - c) ** 2 - 1.0
    excess_total_net = float(m.get("total_return", 0.0)) - bh_net
    if OOS_TOTAL_RETURN_FLOOR:
        passed = passed and excess_total_net > 0.0
    extras = {"excess_sharpe": round(excess_sharpe, 6),
              "excess_total_return_net": round(excess_total_net, 6),
              "total_return_floor": bool(OOS_TOTAL_RETURN_FLOOR)}
    return (OOSOutcome.PASS if passed else OOSOutcome.FAIL), a, extras


def _record_oos(state: ResearchState, candidate: Candidate, outcome_value: str,
                lineage_id: str, emit: Any, assessment: Any = None,
                extras: dict | None = None) -> None:
    """Append the OOS verdict to state (last-wins per hash for the trust badge) and emit it.

    ``assessment`` (a ConfidenceAssessment) is the OOS evidence from this evaluation; its tier + CI ride
    alongside the outcome for display (spec §5.6). It is ``None`` on the recover path (a prior terminal
    verdict is replayed without re-running the backtest) — then no fresh CI is available.
    """
    a = assessment
    result = OOSResult(
        strategy_hash=candidate.strategy_hash,
        lineage_id=lineage_id,
        outcome=outcome_value,
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        confidence_tier=getattr(a, "tier", "") or "",
        basis=getattr(a, "basis", "") or "",
        ci_low=getattr(a, "ci_low", None),
        ci_high=getattr(a, "ci_high", None),
        ci_level=getattr(a, "ci_level", None),
        in_market_sharpe=getattr(a, "in_market_sharpe", None),
        in_market_ci_low=getattr(a, "in_market_ci_low", None),
        in_market_ci_high=getattr(a, "in_market_ci_high", None),
        excess_sharpe=(extras or {}).get("excess_sharpe"),
        excess_total_return_net=(extras or {}).get("excess_total_return_net"),
        total_return_floor=bool((extras or {}).get("total_return_floor", False)),
    )
    state.oos_results.append(result)
    emit("oos_result", {
        "strategy_hash": candidate.strategy_hash, "outcome": outcome_value,
        "confidence_tier": result.confidence_tier, "basis": result.basis,
        "ci_low": result.ci_low, "ci_high": result.ci_high, "ci_level": result.ci_level,
        "in_market_sharpe": result.in_market_sharpe,
        "in_market_ci_low": result.in_market_ci_low, "in_market_ci_high": result.in_market_ci_high,
        # D2: the benchmark comparison — risk-adjusted (gates the PASS) + fee-net total-return (report-only
        # unless the explicit floor toggle is on).
        "excess_sharpe": result.excess_sharpe,
        "excess_total_return_net": result.excess_total_return_net,
        "total_return_floor": result.total_return_floor,
    })


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
    # The lockbox callable must return a bare OOSOutcome, so we stash the assessment (tier + CI) in a
    # closure cell to surface it via _record_oos afterwards (spec §5.6 — evidence rides alongside).
    captured: dict[str, Any] = {}

    def _oos_backtest() -> Any:
        oos_start = spec.get("window_end") or _env_bounds()[0]
        oos_end = _env_bounds()[1]
        oos_spec = {**spec, "window_start": oos_start, "window_end": oos_end}
        oos_data, oos_wb = _prepare_with_warmup(
            data_agent, state.current_asset, oos_start, oos_end, oos_spec,
        )
        oos_metrics = executor.run(oos_spec, oos_data, warmup_bars=oos_wb)
        # valconf/R5: scale the OOS trade bar to the IS selection tempo (candidate's IS trades over the IS
        # window span) × the OOS window length, so a slow strategy isn't auto-UNEVALUATED by a fixed bar.
        outcome, assessment, extras = _oos_verdict(
            oos_metrics,
            train_trades=int(getattr(candidate, "n_trades", 0) or 0),
            train_days=_days(getattr(state, "window_start", "") or "",
                             getattr(state, "window_end", "") or ""),
            oos_days=_days(oos_start, oos_end),
            # valconf CI seeding: the OOS band is a reproducible property of this strategy's fingerprint.
            seed=_seed_from_hash(getattr(candidate, "strategy_hash", "") or ""),
        )
        captured["assessment"] = assessment
        captured["extras"] = extras
        return outcome

    outcome = lockbox.evaluate(token, run_oos_backtest=_oos_backtest)
    _record_oos(state, candidate, outcome.value, budget_lineage, emit,
                captured.get("assessment"), captured.get("extras"))

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
    coverage: Any = None,        # CoverageMap when coverage memory is on (sampling state)
    coverage_dsr: bool = False,  # coverage-v2 N-wire: size sr0 to the campaign visited count
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
    _trial_lengths: list[int] = []   # PF4: trial return-series lengths (the trials' clock)

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
            # H19: capture is_mutation BEFORE _prev_hypothesis_template is updated below — the old code
            # recomputed it AFTER the update, so it was ALWAYS True and the mutation cap never fired.
            _is_mutation = (hypothesis.proposed_template_id == _prev_hypothesis_template
                            and _prev_hypothesis_template != "")
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
            is_mutation = _is_mutation   # H19: computed above, before the prev-template update
            # H19: key the caps on the stable lineage ROOT (a hypothesis FAMILY), not the fresh per-call
            # hyp_{uuid} — which reset the per-hypothesis counter every iteration, so the anti-brute-force
            # caps (max_trials_per_hypothesis / max_mutations_after_failed_gate) could never fire.
            _root = lineage_tracker.get_root(state.current_lineage_id)
            _family_key = _root.lineage_id if _root is not None else state.current_lineage_id
            try:
                budget_controller.check_and_consume(
                    agent_id="strategist",
                    hypothesis_id=_family_key,
                    lineage_id=_family_key,
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
            # M60: label regimes from the ASSET's (market) close-to-close returns, not the strategy equity.
            # TI-5: if the market series is unavailable (missing / malformed ohlcv_df) skip regime labeling
            # entirely (market_returns=None → {}) rather than silently falling back to the strategy's own
            # returns — that fallback would reintroduce the exact M60 mislabeling the fix removed.
            _ohlcv = metrics.get("ohlcv_df")
            _mkt_returns = None
            try:
                if _ohlcv is not None and "Close" in _ohlcv:
                    _mkt_returns = _ohlcv["Close"].pct_change().dropna().to_numpy()
            except Exception:
                _mkt_returns = None
            regime_analysis = _compute_regime_analysis(_mkt_returns, strategy_returns=returns)
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
                    "benchmark_available": bool(metrics.get("benchmark_available", True)),  # M46: 0.0 ≠ "no benchmark"
                },
                regime_analysis=regime_analysis,
            )

            sharpe = metrics.get("sharpe_annual", 0.0)
            _sharpe_values.append(sharpe)
            _sr_period = _period_sharpe(returns)  # H1: per-period Sharpe for DSR multiplicity
            if _sr_period is not None:
                _period_sharpe_values.append(_sr_period)
                # PF4: the trials' own return-series lengths — the null dispersion of the
                # cross-trial Sharpe spread scales with the TRIALS' clocks, not the candidate's.
                _trial_lengths.append(len(returns) if returns is not None else 0)
            emit("execute", {
                "strategy_hash": spec.get("strategy_hash", ""),
                "sharpe_annual": sharpe,
                "n_trades": metrics.get("n_trades", 0),
            })

            # ── Phase 5: GATES_EVALUATED ──
            state.phase = ResearchPhase.GATING
            # H1/M25: per-period trial-Sharpe variance + a trial count that reflects only
            # gate-evaluable trials (not state.total_iterations, which counts errors/skips).
            _dsr_n_trials, sr_variance, _sr_defaulted, _trial_med_t = _dsr_registry_inputs(
                _period_sharpe_values, _trial_lengths
            )
            # coverage-v2 N-wire (B1/B2/B4/B5): when enabled, the sr0 hurdle sizes to the
            # campaign's VISITED-cell count (raw = the conservative upper bound) floored at the
            # run's own trial count — enabling can only TIGHTEN. Flag off → 0 → gate unchanged.
            _search_size = 0
            if coverage_dsr and coverage is not None:
                from src.backend.ai.research.effective_n import campaign_search_size
                _search_size = campaign_search_size(
                    getattr(coverage, "visited", {}) or {}, _dsr_n_trials)
            gatekeeper.update_registry_stats(
                _dsr_n_trials, sr_variance, variance_defaulted=_sr_defaulted,
                trial_median_t=_trial_med_t, search_size=_search_size,
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
                # M21 (review): a hard-gate ERROR leaves first_failed_gate=None but sets errored_gate;
                # prefer it so the cause is attributed (not None → "unknown"/filtered downstream).
                _failed = gate_report.get("first_failed_gate") or gate_report.get("errored_gate") or "unknown"
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
                    failed_gate=gate_report.get("first_failed_gate") or gate_report.get("errored_gate") or "unknown",
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
                # H24 (review): surface SOFT gate FAILs (e.g. a survivorship-biased default provider)
                # as candidate weaknesses in BOTH modes. Previously only regime mode did this, so a
                # default robustness run dropped the survivorship caveat entirely. The regime block
                # below recomputes weaknesses for its confidence tier; here we ensure robustness at
                # least records the caveat on the candidate (surfaced in the report/dossier).
                candidate.weaknesses = [
                    {"gate": _r.get("gate_id"), "value": _r.get("value"),
                     "threshold": _r.get("threshold"),
                     "reason": (_r.get("details") or {}).get("reason", "")}
                    for _r in gate_report.get("results", [])
                    if "FAIL" in str(_r.get("status", "")).upper() and _r.get("gate_id") != "minimum_activity"
                ]
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
                        t_star=_sidak_t_star(_ho_prior + 1),
                        # valconf/M27: the frequency-scaled bar needs the strategy's train-window tempo.
                        train_trades=int(metrics.get("n_trades", 0)),
                        train_days=_days(getattr(state, "window_start", ""), getattr(state, "train_end", "")),
                        # valconf CI seeding: the band is a reproducible property of this strategy's fingerprint.
                        seed=_seed_from_hash(candidate.strategy_hash))
                    if _hold.get("basis") == "per_trade":   # a REAL significance test ran → consumes a Šidák peek
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
        # M48: track consecutive "skipped" iterations (persistent budget/dedup skips make no progress and
        # reset no other counter) so the Director can rotate/stop a zombie spin.
        state.consecutive_skips = state.consecutive_skips + 1 if outcome == "skipped" else 0

        if outcome == "candidate":
            state.candidates.append(candidate)
            _regime_failed = getattr(candidate, "validation_status", "") == "regime_failed"
            # M49 (+F1): the plateau watermark must track ACCEPTED-candidate quality, not the raw in-sample
            # Sharpe of gate-FAILED / critic-REJECTED trials — nor a regime_failed idea, which by definition
            # cleared the (soft) regime gates on a HIGH in-sample Sharpe and then collapsed out-of-fit, i.e.
            # exactly the overfit-high-Sharpe profile that would pin the watermark and make R4 abandon a
            # still-productive asset. A regime_failed idea is surfaced but does NOT advance the watermark.
            if not _regime_failed:
                state.best_sharpe_on_asset.append(
                    max(sharpe, state.best_sharpe_on_asset[-1]) if state.best_sharpe_on_asset else sharpe)
            # M28: a regime idea that FAILED its within-regime hold-out is still *surfaced* (appended) but
            # is NOT a success — it must not reset the consecutive-failure breaker, otherwise a stream of
            # regime_failed ideas would keep R4 (max_consecutive_failures) from ever firing and the loop
            # would grind on a dead asset. Count it as a failure; every other candidate resets as before.
            if _regime_failed:
                state.consecutive_failures += 1
            else:
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
