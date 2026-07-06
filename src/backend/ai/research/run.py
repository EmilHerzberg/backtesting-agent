"""Top-level entry point: START -> RESULT.

One function call runs the entire autonomous research pipeline.
No LLM required — works out of the box with yfinance data.

Usage:
    import asyncio
    from src.backend.ai.research.run import run_research

    report = asyncio.run(run_research(
        goal="momentum strategies for AAPL MSFT",
        assets=["AAPL", "MSFT"],
        max_runs=50,
    ))
"""

from __future__ import annotations

import logging
from typing import Any

from src.backend.ai.research.budgets import AgentBudgetController
from src.backend.ai.research.critic import AdversarialCritic
from src.backend.ai.research.executor import ResearchExecutor
from src.backend.ai.research.gatekeeper import ResearchGatekeeper
from src.backend.ai.research.loop import DirectorConfig, RuleBasedOrchestrator, research_loop
from src.backend.ai.research.report_generator import generate_final_report, llm_narrate_report
from src.backend.ai.research.reporter import ResearchReport
from src.backend.ai.research.state import Budget, GoalBrief, ResearchState
from src.backend.ai.research.strategist import LLMStrategist, RuleBasedStrategist
from src.backend.backtesting.validation.lineage import LineageTracker

logger = logging.getLogger(__name__)


_OHLCV = ["Open", "High", "Low", "Close", "Volume"]


def _make_provider():
    """The marketdata provider for the research loop. Default yahoo; set ``settings.data_provider`` to
    another name (e.g. alphavantage) to route the whole loop through that provider's adjustment
    handling. Stateless — no persistence."""
    from src.backend.marketdata.provider import create_provider

    name = "yahoo"
    try:
        from src.backend.shared.config import settings
        name = getattr(settings, "data_provider", None) or "yahoo"
    except Exception:
        pass
    return create_provider(name)


def _to_date(s):
    from datetime import date

    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except Exception:
        return None


def _default_fetch(security_id: str, start: str, end: str):
    """Fetch daily OHLCV through the marketdata PROVIDER layer (YahooProvider by default), not raw
    ``yf.Ticker`` — so the research loop shares the provider-layer correctness fixes (M32 end-inclusive,
    adjustment conventions, priority-aggregation) with the CLI. Stateless: no persistence, no DB growth."""
    from src.backend.shared.types import BarInterval

    df = _make_provider().fetch_ohlcv(security_id, BarInterval.ONE_DAY, _to_date(start), _to_date(end))
    if df is None or df.empty:
        raise ValueError(f"No data for {security_id}")
    for col in _OHLCV:
        if col not in df.columns:
            raise ValueError(f"Missing column {col} in {security_id} data")
    return df[_OHLCV]


class _CachedFetch:
    """Opt-in PERSISTENT (DB) fetch via CacheManager — reserved for paid providers / intraday where
    re-fetching costs API quota. NOT the yfinance-daily default (which stays persistence-free so the
    server DB doesn't grow). One CacheManager per run (its engine is built once)."""

    def __init__(self):
        from src.backend.marketdata.cache import CacheManager

        self._cm = CacheManager(provider=_make_provider())

    def __call__(self, security_id: str, start: str, end: str):
        from src.backend.shared.types import BarInterval

        df = self._cm.get_or_fetch(security_id, BarInterval.ONE_DAY, _to_date(start), _to_date(end))
        if df is None or df.empty:
            raise ValueError(f"No data for {security_id}")
        return df[_OHLCV]


class _SimpleDataAgent:
    """Data agent: provider-layer fetch + an in-memory PER-RUN cache (no DB growth). The research loop
    calls prepare() many times per run for the same (asset, window); memoizing collapses those into one
    fetch — big speed win + fewer provider hits — while the cache is discarded when the run ends.
    ``use_price_cache=True`` routes through the persistent DB cache instead (paid/intraday quota)."""

    def __init__(self, fetch_fn=None, *, use_price_cache: bool = False):
        self._mem: dict = {}
        if fetch_fn is not None:
            self._fetch = fetch_fn
        elif use_price_cache:
            self._fetch = _CachedFetch()
        else:
            self._fetch = _default_fetch

    def prepare(self, security_id: str, window_start: str, window_end: str):
        key = (security_id, window_start, window_end)
        df = self._mem.get(key)
        if df is None:
            df = self._fetch(security_id, window_start, window_end)
            self._mem[key] = df
        # Defensive copy: callers/backtesting.py may slice or annotate; keep the cached frame pristine.
        return df.copy() if df is not None else df


async def run_research(
    goal: str = "Find profitable trading strategies",
    assets: list[str] | None = None,
    *,
    max_runs: int = 100,
    max_eur: float = 50.0,
    max_seconds: int = 3600,
    target_candidates: int = 3,
    strategy_families: list[str] | None = None,
    rigor: str = "standard",
    seed: int = 42,
    fetch_fn: Any = None,
    on_start: Any = None,
    on_event: Any = None,
    control: Any = None,
    enable_oos: bool = True,          # D9/H5: OOS validation is the honest default (opt OUT explicitly)
    oos_db_path: str = ":memory:",    # per-run by default (disk-clean); set a file path for cross-run persistence
    enable_leakage_canary: bool = True,  # M22: run the leakage canary on survivors (re-runs on synthetics)
    use_price_cache: bool = False,       # persist fetched bars in the DB cache (paid/intraday quota);
                                         # OFF for the yfinance-daily default so the server DB doesn't grow
    commission_pct: float = 0.001,       # H29/D8: same realistic cost model the CLI uses —
    spread_bps: float = 5.0,             # effective per-side cost = commission + half-spread + slippage
    slippage_bps: float = 2.0,           # (≈14.5 bps/side by default, not the old bare 10 bps)
    agent_mode: str = "rule_based",   # W0: rule_based | ai_assisted | full_ai
    provider: str | None = None,      # W0: LLM provider name (registry); None = auto/none
    model: str | None = None,         # W0: model id; None = provider default
    mode: str = "robustness",         # P1: robustness | regime
    window_start: str | None = None,  # P1: regime window start (ignored in robustness)
    window_end: str | None = None,    # P1: regime window end
) -> ResearchReport:
    """Run the full autonomous research pipeline.

    START -> propose -> execute -> gate -> critic -> learn -> RESULT

    Args:
        goal: Natural language research goal.
        assets: List of ticker symbols to research.
        max_runs: Maximum number of backtest runs.
        max_eur: Maximum cost budget (for LLM calls, not used in rule-based mode).
        max_seconds: Maximum wall-clock time.
        target_candidates: Stop when this many validated strategies found.
        strategy_families: Filter templates by family ("trend_following", "mean_reversion", "multi_factor").
        seed: Random seed for reproducibility.
        fetch_fn: Custom data fetch function(security_id, start, end) -> DataFrame.
        on_start: Callback(state) invoked once with the live ResearchState before the
            loop starts (lets an observer, e.g. the API run registry, track progress).
        on_event: Callback(event_type, payload) for progress tracking.
        enable_oos: Whether to run OOS lockbox evaluation on candidates.
        oos_db_path: Path to the OOS lockbox database.

    Returns:
        ResearchReport with validated candidates, trial statistics, and honest assessment.
    """
    if assets is None:
        assets = ["AAPL"]

    if strategy_families is None:
        strategy_families = ["trend_following", "mean_reversion", "multi_factor"]  # F4

    # F1: Strict rigor forces out-of-sample validation on (also re-enables it if a caller opted out).
    if rigor == "strict":
        enable_oos = True

    # P1: effective backtest window — regime uses the user's window (BOTH bounds required, atomic — M1/S1);
    # robustness keeps the fixed default and ignores any window.
    from src.backend.ai.research.strategist import WINDOW_START as _DEF_WS, WINDOW_END as _DEF_WE
    if mode == "regime":
        if not (window_start and window_end):
            raise ValueError("regime mode requires both window_start and window_end")
        if window_start >= window_end:
            raise ValueError(f"window_start ({window_start}) must precede window_end ({window_end})")
        eff_ws, eff_we = window_start, window_end
        # S3: regime has no *robustness* OOS (post-window is semantically wrong for a regime window) →
        # disable it; P2's within-regime forward-slice hold-out replaces it (below).
        enable_oos = False
    else:
        eff_ws, eff_we = _DEF_WS, _DEF_WE

    # P2 select-on-train: split the regime window → the strategist + backtest + gates + critic see the
    # TRAIN slice only (selection never touches the hold-out, Rita/C-1); state keeps the FULL window
    # (display, decay, hold-out bound). ``None`` → window too short to split → stays UNVALIDATED (P2-5).
    from src.backend.ai.research.loop import _train_split
    _split = _train_split(eff_ws, eff_we) if mode == "regime" else None
    train_ws, train_we = (eff_ws, _split) if _split else (eff_ws, eff_we)

    # ── Build state ───────────────────────────────────────────
    # C3/M50 — parse the user's free-text goal into structured numeric criteria so goal completion is
    # decided on whether candidates actually meet the user's Sharpe/drawdown/… thresholds, not a raw
    # candidate count.
    from src.backend.ai.goals.criteria import parse_criteria
    _criteria = parse_criteria(goal)["criteria"]
    state = ResearchState(
        goal=GoalBrief(
            goal_text=goal,
            asset_pool=assets,
            strategy_families=strategy_families,
            max_runs=max_runs,
            max_eur=max_eur,
            max_seconds=max_seconds,
            target_candidates=target_candidates,
            criteria=_criteria,
        ),
        budget=Budget(
            max_runs=max_runs,
            max_eur=max_eur,
            max_seconds=max_seconds,
        ),
    )

    # Expose the live state to observers (e.g. the API run registry) before the loop runs.
    if on_start is not None:
        on_start(state)

    # ── W0: provider plumbing + cost ledger (inert until W1; rule_based = no LLM) ──
    from src.backend.ai.research.agent_llm import TokenLedger, resolve_agent_llm
    ledger = TokenLedger(budget=state.budget)
    llm = None
    if agent_mode != "rule_based":
        llm = resolve_agent_llm(provider, model)
        if llm is None:
            logger.warning("agent_mode=%s requested but no provider resolved → rule_based", agent_mode)
            agent_mode = "rule_based"
    state.agent_mode = agent_mode  # effective mode (W0-2: honest about what actually ran)
    # P2: record the effective provider type for the leakage marker (F-11) — "" for rule_based/no-LLM.
    state.provider_type = getattr(getattr(llm, "provider", None), "provider_type", "") if llm is not None else ""
    # H31: record the effective MODEL id too — the leakage badge is per-model (a provider can ship a
    # validated model AND an unvalidated sibling), so provider granularity alone is over-optimistic.
    state.model_id = getattr(llm, "model", "") if llm is not None else ""
    state.mode = mode
    state.window_start = eff_ws       # FULL window (display, decay, hold-out bound)
    state.window_end = eff_we
    state.train_end = _split or ""    # P2: the split boundary the loop reads for the hold-out ("" = no split)
    # NOTE: `llm`/`ledger` are not yet handed to any agent — W1 wires the Critic.

    # ── Build agents ──────────────────────────────────────────
    # Selection path (strategist + its fallback + critic) sees the TRAIN slice (P2-R1: the fallback too,
    # else an LLM failure silently backtests the full window and the hold-out is no longer unseen).
    if agent_mode == "full_ai" and llm is not None:
        strategist = LLMStrategist(
            llm=llm, ledger=ledger,
            fallback=RuleBasedStrategist(seed=seed, window_start=train_ws, window_end=train_we),
            window_start=train_ws, window_end=train_we, mode=mode, goal=goal,
        )
    else:
        strategist = RuleBasedStrategist(seed=seed, window_start=train_ws, window_end=train_we)
    # H29/D8: charge the same realistic effective cost as the CLI (commission + half-spread + slippage),
    # not a bare commission — otherwise AI-discovered strategies are graded ~30% cheaper than documented.
    from src.backend.backtesting.costs.model import effective_commission_pct
    executor = ResearchExecutor(commission=effective_commission_pct(commission_pct, spread_bps, slippage_bps))
    gatekeeper = ResearchGatekeeper(rigor=rigor, mode=mode)
    critic = AdversarialCritic(
        llm=(llm if agent_mode in ("ai_assisted", "full_ai") else None),
        ledger=ledger,
        mode=mode, window_start=train_ws, window_end=train_we, goal=goal,
    )
    data_agent = _SimpleDataAgent(fetch_fn=fetch_fn, use_price_cache=use_price_cache)
    orchestrator = RuleBasedOrchestrator(DirectorConfig(oos_enabled=enable_oos))
    lineage_tracker = LineageTracker()
    budget_controller = AgentBudgetController()

    # ── OOS lockbox (optional) ────────────────────────────────
    lockbox = None
    if enable_oos:
        # Review fix: a REQUESTED OOS run must not silently degrade to in-sample validation if the
        # lockbox can't be built. oos_enabled is derived purely from lockbox presence, and
        # validated_count/goal_met count in-sample candidates when it's off — so swallowing the error
        # would let a run the user asked to hold-out-validate report "validated" on in-sample data alone.
        # Fail loudly instead (honest: we cannot deliver the OOS contract that was requested).
        try:
            from src.backend.backtesting.lockbox.service import OOSLockboxService
            lockbox = OOSLockboxService(db_path=oos_db_path)
        except Exception as exc:
            raise RuntimeError(
                f"OOS validation was requested (enable_oos=True) but the lockbox could not be "
                f"initialised at {oos_db_path!r}: {exc}. Refusing to silently validate in-sample."
            ) from exc

    # ── Run the loop ──────────────────────────────────────────
    logger.info(
        "Starting research: goal=%r, assets=%s, max_runs=%d, target=%d",
        goal, assets, max_runs, target_candidates,
    )

    state = await research_loop(
        state,
        strategist=strategist,
        executor=executor,
        gatekeeper=gatekeeper,
        critic=critic,
        data_agent=data_agent,
        orchestrator=orchestrator,
        lockbox=lockbox,
        lineage_tracker=lineage_tracker,
        budget_controller=budget_controller,
        on_event=on_event,
        control=control,
        enable_leakage_canary=enable_leakage_canary,
    )

    # ── Generate report ───────────────────────────────────────
    report = generate_final_report(state)
    if agent_mode in ("ai_assisted", "full_ai") and llm is not None:  # W3/W3B: LLM Reporter (narration)
        await llm_narrate_report(report, state, llm, ledger)

    logger.info(
        "Research complete: phase=%s, candidates=%d, trials=%d, oos=%d, agent_mode=%s, run_mode=%s, cost=€%.4f, tokens=%d",
        state.phase, len(state.candidates), state.total_iterations,
        len(state.oos_results), agent_mode, mode, ledger.cost_eur,
        ledger.prompt_tokens + ledger.completion_tokens,
    )

    return report
