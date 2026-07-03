"""ATS-1764/1765/1766 — Adversarial Critic agent.

Runs in a SEPARATE LLM context. Never sees the Strategist's reasoning.
Receives only: spec + metrics + gate results + benchmarks.
Outputs: CriticReport with weaknesses, confidence, recommendation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from src.backend.ai.models import ChatMessage, ChatRequest
from src.backend.ai.research.agent_llm import extract_json_object

if TYPE_CHECKING:
    from src.backend.ai.research.agent_llm import LLMHandle, TokenLedger

logger = logging.getLogger(__name__)


class CriticRecommendation(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    INVESTIGATE = "investigate"


class CriticConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class CriticReport:
    """Output of the adversarial critic."""

    weaknesses: list[str] = field(default_factory=list)
    confidence: CriticConfidence = CriticConfidence.LOW
    recommendation: CriticRecommendation = CriticRecommendation.INVESTIGATE
    reasoning: str = ""


CRITIC_SYSTEM_PROMPT = """You are an adversarial reviewer for quantitative trading strategies.
Your job is to find weaknesses. You are deliberately skeptical.

You are given:
- Strategy spec (template, parameters, asset, costs)
- In-sample metrics (Sharpe, return, drawdown, trade count)
- Quality gate results (which passed, which failed, values)
- Benchmark comparison (buy-and-hold, market)

You do NOT have access to:
- The researcher's hypothesis or economic rationale
- The researcher's chain-of-thought
- Any conversation between the researcher and the system

Attack the strategy for:
1. OVERFITTING: Is the parameter set suspiciously precise? Few trades + high Sharpe?
2. REGIME DEPENDENCE: Does performance concentrate in one market regime?
3. PURE BETA: Is this just buying dips in a bull market? Check benchmark comparison.
4. COST FRAGILITY: How close to breakeven under stressed costs?
5. SAMPLE SIZE: Are there enough trades for statistical significance?
6. LEAKAGE SMELL: Anything suspicious about the execution timing or data usage?

Output a JSON object with:
{
  "weaknesses": ["list of specific weaknesses found"],
  "confidence": "low|medium|high",
  "recommendation": "accept|reject|investigate",
  "reasoning": "detailed reasoning for your recommendation"
}

Rules:
- "high" confidence requires: walk-forward validated, 100+ trades, benchmark beats, no red flags
- "reject" if: any critical weakness found (overfitting, leakage, pure beta with no alpha)
- "accept" if: no critical weaknesses, reasonable sample size, beats benchmarks
- "investigate" if: mixed signals, some concerns but not dealbreakers
- NEVER recommend "accept" without checking benchmark comparison
- Be specific about numbers — reference actual metrics values
"""


def _window_months(start: str, end: str) -> int:
    """Window length in months — the leakage-safe regime context (DURATION, not calendar dates)."""
    from datetime import date
    try:
        return max(1, round((date.fromisoformat(end) - date.fromisoformat(start)).days / 30.44))
    except Exception:
        return 0


# P1 Chunk B — regime-fit Critic prompt (mode="regime"). ANTI-LEAKAGE: gets the window DURATION (months), not
# the calendar dates. Judges IN-SAMPLE overfit / pure-beta / leakage; DEFERS sample-adequacy to the activity
# tier (does NOT reject on trade count alone — that collapsed everything to very_low); caps confidence at "medium".
REGIME_CRITIC_PROMPT = """You are an adversarial reviewer for a REGIME-FIT trading strategy, fitted to ONE
specific ~{months}-month market window (the exact dates are withheld — judge the strategy on its EVIDENCE, not
on what you recall about any period). Your job is to find weaknesses. You are deliberately skeptical.

You are given: the research GOAL (the user's regime hypothesis); the strategy spec; in-sample metrics (within
the regime window); quality gate results (incl. a per-trade sample-confidence tier); the benchmark comparison.

This is REGIME-FIT research — the strategy is NOT expected to generalize beyond this ~{months}-month window, so
do NOT reject it merely for REGIME DEPENDENCE (that is the point). SAMPLE ADEQUACY is ALREADY SCORED by the
activity gate's tier (thin/adequate) — do NOT reject on trade count / sample size ALONE; note it, but let the
tier carry it. Judge whether the EDGE IS REAL beyond that:
1. IN-SAMPLE OVERFIT: is the edge curve-fit to this window? Suspiciously precise params? One or two trades
   carrying the WHOLE result (concentration), regardless of the raw count?
2. PURE BETA: is this just riding the regime's trend with no strategy-specific edge? Check the benchmark.
3. LEAKAGE SMELL: anything off about execution timing or data usage?
4. COST FRAGILITY: how close to breakeven under stressed costs?

Output a JSON object with:
{{"weaknesses": ["..."], "confidence": "low|medium|high", "recommendation": "accept|reject|investigate",
  "reasoning": "..."}}

Rules:
- Regime-fit with NO out-of-regime validation here — "high" confidence is NOT available; cap at "medium".
- "reject" ONLY for: in-sample OVERFIT, leakage, or PURE BETA with no regime-specific edge. Do NOT reject for a
  thin sample alone — the tier already scores that; use "investigate" for a plausible-but-thin idea.
- "investigate" / "accept" (at most "medium") for a plausible regime-specific mechanism that beats the benchmark
  WITHIN the regime — explicitly REGIME-FIT, not robust. A thin-but-plausible idea → "investigate", not reject.
- Be specific about numbers — reference actual metrics values.
"""

CRITIC_TOOLS = [
    "read_spec",
    "read_metrics",
    "read_gate_report",
    "read_benchmark",
    "read_regime_analysis",
    "record_critique",
]


class AdversarialCritic:
    """Adversarial critic agent with isolated LLM context.

    This is the interface layer. The actual LLM call is injected via
    the CriticProtocol in the research loop, allowing mock testing
    without real API calls.
    """

    def __init__(self, llm: "LLMHandle | None" = None, ledger: "TokenLedger | None" = None,
                 mode: str = "robustness", window_start: str = "", window_end: str = "", goal: str = ""):
        self._llm = llm
        self._ledger = ledger
        self.mode = mode
        self.window_start = window_start
        self.window_end = window_end
        self.goal = goal   # user's regime hypothesis (regime mode)

    def _system_prompt(self) -> str:
        # P1 / anti-leakage: regime mode judges overfit vs the window DURATION (months), never the dates.
        if self.mode == "regime":
            return REGIME_CRITIC_PROMPT.format(months=_window_months(self.window_start, self.window_end))
        return CRITIC_SYSTEM_PROMPT

    async def review(
        self,
        spec: dict[str, Any],
        metrics: dict[str, Any],
        gate_report: dict[str, Any],
    ) -> dict[str, Any]:
        """Review a strategy that passed gates.

        Uses the LLM (W1) when an LLMHandle is configured (agent_mode != rule_based).
        Falls back to the rule-based heuristic in every other case — no provider, over
        EUR budget, API error, or an unparseable verdict — so a critic failure never
        silently accepts. Isolation: only spec + metrics + gate_report are sent; the
        Strategist's hypothesis/reasoning is never available here.
        """
        if self._llm is None:
            return self._heuristic_review(spec, metrics, gate_report)
        if self._over_budget():
            logger.info("Critic: over EUR budget — using heuristic")
            return self._heuristic_review(spec, metrics, gate_report)
        try:
            req = ChatRequest(
                model=self._llm.model,
                messages=[
                    ChatMessage(role="system", content=self._system_prompt()),
                    ChatMessage(role="user", content=self._render_evidence(spec, metrics, gate_report)),
                ],
                temperature=0.2,
                max_tokens=4000,   # reasoner models spend tokens on reasoning BEFORE the JSON verdict;
                                   # 900 truncated it → "unparseable → heuristic". Non-reasoners stop early.
                json_mode=self._llm.supports_json_mode,
            )
            resp = await self._llm.provider.chat_completion(req)
            if self._ledger is not None:
                self._ledger.record(resp.usage, self._llm)
            verdict = self._parse_verdict(resp.content)
            if verdict is None:
                logger.warning("Critic: unparseable LLM verdict — using heuristic")
                return self._heuristic_review(spec, metrics, gate_report)
            return verdict
        except Exception as exc:  # noqa: BLE001 — any LLM failure must fall back, never accept
            logger.warning("Critic LLM failed (%s) — using heuristic", exc)
            return self._heuristic_review(spec, metrics, gate_report)

    def _over_budget(self) -> bool:
        if not self._ledger:
            return False
        b = self._ledger.budget
        return b.max_eur > 0 and b.used_eur >= b.max_eur

    def _render_evidence(
        self, spec: dict[str, Any], metrics: dict[str, Any], gate_report: dict[str, Any]
    ) -> str:
        """Build the critic's evidence — an ALLOWLIST of named scalar fields only.

        Never dumps raw `metrics` (holds numpy returns / the OHLCV DataFrame / a large
        equity curve → unserializable + bloat). The allowlist also guarantees isolation:
        any unnamed key (e.g. a stray hypothesis/rationale) cannot leak to the model.
        """
        benchmark = metrics.get("benchmark", {}) or {}
        regime = metrics.get("regime_analysis", {}) or {}
        regime_summary = {
            k: {"type": v.get("type"), "sharpe": v.get("sharpe")}
            for k, v in regime.items() if isinstance(v, dict)
        }
        gate_summary = {
            "passed": gate_report.get("passed"),
            "first_failed_gate": gate_report.get("first_failed_gate"),
            "gates": [
                {"id": g.get("gate_id"), "status": g.get("status"),
                 "value": g.get("value"), "threshold": g.get("threshold")}
                for g in gate_report.get("results", []) if isinstance(g, dict)
            ],
        }
        evidence = {
            "strategy": {
                "template_id": spec.get("template_id"),
                "params": spec.get("params", {}),
                "security_id": spec.get("security_id"),
                "commission": metrics.get("commission"),
            },
            "in_sample_metrics": {
                k: metrics.get(k) for k in (
                    "sharpe_annual", "total_return", "max_drawdown", "n_trades",
                    "exposure_time", "win_rate", "profit_factor",
                )
            },
            "benchmark": {
                "buy_hold_return": benchmark.get("buy_hold_return", metrics.get("buy_hold_return")),
                "buy_hold_sharpe": benchmark.get("buy_hold_sharpe", metrics.get("buy_hold_sharpe")),
            },
            "regime": regime_summary,
            "gates": gate_summary,
        }
        if self.mode == "regime" and self.goal:
            evidence["research_goal"] = self.goal   # user's regime hypothesis (character, not dates)
        return json.dumps(evidence, default=str)

    @staticmethod
    def _parse_verdict(content: str | None) -> dict[str, Any] | None:
        """Extract a verdict JSON object from the model's reply (markdown-tolerant)."""
        data = extract_json_object(content)
        if data is None:
            return None
        rec = str(data.get("recommendation", "")).lower().strip()
        if rec not in ("accept", "reject", "investigate"):
            return None
        conf = str(data.get("confidence", "")).lower().strip()
        if conf not in ("low", "medium", "high"):
            conf = "low"
        w = data.get("weaknesses", [])
        w = [str(x) for x in w] if isinstance(w, list) else [str(w)]
        return {
            "weaknesses": w,
            "confidence": conf,
            "recommendation": rec,
            "reasoning": str(data.get("reasoning", "")),
        }

    def _heuristic_review(
        self,
        spec: dict[str, Any],
        metrics: dict[str, Any],
        gate_report: dict[str, Any],
    ) -> dict[str, Any]:
        """Rule-based fallback critic when no LLM is available.

        Checks per spec Part 5: overfitting, regime dependence, pure beta,
        cost fragility, sample size, leakage smell.
        """
        weaknesses = []
        sharpe = metrics.get("sharpe_annual", 0.0)
        n_trades = metrics.get("n_trades", 0)
        total_return = metrics.get("total_return", 0.0)
        max_dd = metrics.get("max_drawdown", 0.0)

        # Benchmark comparison (try nested then flat).
        benchmark = metrics.get("benchmark", {})
        bh_return = benchmark.get("buy_hold_return", metrics.get("buy_hold_return", 0.0))

        # 1. OVERFITTING: suspiciously precise params + high Sharpe + low trades
        if n_trades < 30:
            weaknesses.append(f"Low trade count ({n_trades}) — insufficient for statistical significance")
        if sharpe > 3.0:
            weaknesses.append(f"Suspiciously high Sharpe ({sharpe:.2f}) — likely overfit")

        # 2. REGIME DEPENDENCE: check if performance concentrates in one regime
        regime = metrics.get("regime_analysis", {})
        if regime:
            regime_sharpes = [r.get("sharpe", 0) for r in regime.values() if isinstance(r, dict)]
            if len(regime_sharpes) >= 2:
                pos_regimes = sum(1 for s in regime_sharpes if s > 0)
                if pos_regimes <= 1 and len(regime_sharpes) >= 3:
                    weaknesses.append(
                        "Regime concentration: positive Sharpe in only one market regime"
                    )
                neg_regimes = [s for s in regime_sharpes if s < -0.5]
                if neg_regimes:
                    weaknesses.append(
                        f"Negative Sharpe ({min(neg_regimes):.2f}) in at least one regime period"
                    )

        # 3. PURE BETA: just buying dips in a bull market?
        if bh_return > 0 and total_return > 0:
            excess = total_return - bh_return
            if excess < 0:
                weaknesses.append(f"Strategy underperforms buy-and-hold ({total_return:.1%} vs {bh_return:.1%})")

        # 4. COST FRAGILITY (check if near breakeven)
        if 0 < total_return < 0.02:
            weaknesses.append(f"Marginal return ({total_return:.1%}) — likely unprofitable after real costs")

        # 5. SAMPLE SIZE
        if max_dd < -0.30:
            weaknesses.append(f"Severe max drawdown ({max_dd:.1%})")

        # Determine recommendation
        critical = any("insufficient" in w.lower() or "overfit" in w.lower() for w in weaknesses)
        if critical:
            return {
                "weaknesses": weaknesses,
                "confidence": "medium",
                "recommendation": "reject",
                "reasoning": f"Critical weakness found: {weaknesses[0]}",
            }
        elif weaknesses:
            return {
                "weaknesses": weaknesses,
                "confidence": "low",
                "recommendation": "investigate",
                "reasoning": f"{len(weaknesses)} concern(s) found but none critical",
            }
        else:
            confidence = "high" if n_trades >= 100 and sharpe > 0.5 else "medium"
            return {
                "weaknesses": [],
                "confidence": confidence,
                "recommendation": "accept",
                "reasoning": "No critical weaknesses found",
            }
