"""Phase 4 / cluster 4B — LLM degradation & honesty (H25, H26).

- H25: strategist max_tokens=700 truncated reasoning models before the JSON → extract_json_object
  returned None → silent fallback to rule-based AFTER billing. Reasoners now get the Critic's headroom,
  and a billed-but-unparseable call is counted so the degradation is visible.
- H26: the heuristic critic hard-rejected <30 trades ("insufficient" → reject), overriding the
  calibrated smart-activity gate the candidate already passed. Trade count is now a non-critical caveat.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.backend.ai.research.agent_llm import LLMHandle
from src.backend.ai.research.critic import AdversarialCritic
from src.backend.ai.research.strategist import LLMStrategist, RuleBasedStrategist


class _MockProvider:
    def __init__(self, content):
        self._content = content
        self.last_req = None

    async def chat_completion(self, req):
        self.last_req = req
        return SimpleNamespace(
            content=self._content,
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        )


def _handle(content, reasoning):
    return LLMHandle(provider=_MockProvider(content), model="m",
                     input_price_per_m=0.0, output_price_per_m=0.0, supports_reasoning=reasoning)


@pytest.mark.finding("H25")
async def test_reasoning_model_gets_critic_order_max_tokens_and_counts_fallback():
    h = _handle("not valid json", reasoning=True)
    strat = LLMStrategist(h, None, RuleBasedStrategist())
    await strat.propose("AAPL", [], [], {})
    assert h.provider.last_req.max_tokens == 4000            # reasoners are no longer truncated
    # billed but unparseable → counted (the silent LLM→heuristic degradation is now visible)
    assert strat.llm_calls == 1 and strat.fallback_after_bill == 1


@pytest.mark.finding("H25")
async def test_non_reasoning_model_keeps_small_cap():
    h = _handle("not valid json", reasoning=False)
    strat = LLMStrategist(h, None, RuleBasedStrategist())
    await strat.propose("AAPL", [], [], {})
    assert h.provider.last_req.max_tokens == 700


def _metrics(**over):
    m = {"sharpe_annual": 1.2, "n_trades": 15, "total_return": 0.20, "max_drawdown": -0.10,
         "buy_hold_return": 0.10}
    m.update(over)
    return m


@pytest.mark.finding("H26")
def test_critic_does_not_reject_a_gate_passed_thin_sample_on_trade_count():
    # 15 trades: below the old hardcoded 30, but the smart-activity gate already vetted trade count.
    r = AdversarialCritic()._heuristic_review({}, _metrics(n_trades=15), {})
    assert r["recommendation"] != "reject"


@pytest.mark.finding("H26")
def test_critic_still_rejects_overfit_sharpe():
    r = AdversarialCritic()._heuristic_review({}, _metrics(sharpe_annual=5.0, n_trades=50), {})
    assert r["recommendation"] == "reject"     # Sharpe>3 "overfit" is still a critical reject


@pytest.mark.finding("M40")
def test_critic_rejects_losing_strategy():
    r = AdversarialCritic()._heuristic_review({}, _metrics(total_return=-0.05, n_trades=50, sharpe_annual=0.8), {})
    assert r["recommendation"] == "reject"     # a non-positive return is a critical failure


@pytest.mark.finding("M40")
def test_critic_will_not_accept_without_benchmark():
    # strong-looking but NO benchmark data (no benchmark dict, no buy_hold_return) → must not accept.
    r = AdversarialCritic()._heuristic_review(
        {}, {"sharpe_annual": 1.5, "n_trades": 150, "total_return": 0.30, "max_drawdown": -0.10}, {})
    assert r["recommendation"] != "accept"
    assert any("benchmark" in w.lower() for w in r["weaknesses"])


@pytest.mark.finding("H26")
def test_gate_passed_thin_sample_is_accepted_not_investigated():
    # F1 (Phase-4 review): the PRIOR test only asserted != "reject", but a clean thin-sample candidate
    # returned "investigate", which the robustness loop treats as a TERMINAL kill — so the median
    # gate-passing candidate (~12 trades) was still killed on trade count. The thin count is now a
    # verdict-neutral caveat, so a clean candidate is ACCEPTED (with the caveat surfaced as a weakness).
    r = AdversarialCritic()._heuristic_review({}, _metrics(n_trades=12), {})
    assert r["recommendation"] == "accept"                       # pre-fix: "investigate" → loop kill
    assert any("trade count" in w.lower() for w in r["weaknesses"])   # …but the caveat is still shown


@pytest.mark.finding("H26")
def test_reject_reasoning_names_the_real_critical_cause_not_the_thin_caveat():
    # F2: `critical` is any()-over-all but the reasoning used to quote weaknesses[0]; the thin-trade note
    # was appended first, so a reject on overfit/losing was mislabeled "Modest trade count…" — poisoning
    # the M37 critic_note fed to the strategist.
    overfit = AdversarialCritic()._heuristic_review({}, _metrics(sharpe_annual=5.0, n_trades=12), {})
    assert overfit["recommendation"] == "reject"
    assert "overfit" in overfit["reasoning"].lower() and "trade count" not in overfit["reasoning"].lower()

    losing = AdversarialCritic()._heuristic_review({}, _metrics(total_return=-0.05, n_trades=12), {})
    assert losing["recommendation"] == "reject"
    assert "trade count" not in losing["reasoning"].lower()   # names the losing return, not the caveat


@pytest.mark.finding("M40")
def test_critic_tolerates_none_and_nan_metrics():
    # F3: metrics.get returns None for a present-but-None key, and a NaN return silently passed the M40
    # losing-strategy guard (NaN <= 0 is False). Coercion means None can't crash and NaN is flagged.
    AdversarialCritic()._heuristic_review({}, _metrics(sharpe_annual=None, total_return=None), {})  # no crash
    nan = AdversarialCritic()._heuristic_review({}, _metrics(total_return=float("nan"), n_trades=50), {})
    assert nan["recommendation"] == "reject"                  # NaN return coerced to 0.0 → losing/critical


@pytest.mark.finding("M39")
def test_heuristic_critique_is_stamped_source():
    r = AdversarialCritic()._heuristic_review({}, _metrics(), {})
    assert r["source"] == "heuristic"          # degradation is visible in the persisted critique


@pytest.mark.finding("M37")
def test_strategist_feedback_carries_the_critic_note():
    strat = LLMStrategist(
        LLMHandle(provider=None, model="m", input_price_per_m=0.0, output_price_per_m=0.0),
        None, RuleBasedStrategist(),
    )
    fc = SimpleNamespace(template_id="sma", params={}, failed_gate=None,
                         failure_reason="critic_rejection", critic_notes="Pure beta: just tracked the market")
    rendered = strat._render("AAPL", [], [fc], {})
    assert "Pure beta" in rendered             # the critic's substance reaches the strategist prompt


@pytest.mark.finding("H31")
def test_run_leakage_badge_is_per_model_not_provider(monkeypatch):
    # The run badge must reflect the MODEL that ran, not the provider summary — a provider that ships
    # one validated model badged EVERY run on it clean, even a run on an unvalidated sibling model.
    import src.backend.ai.research.router as rt

    monkeypatch.setattr(rt, "model_leakage", lambda mid: "unvalidated")
    monkeypatch.setattr(rt, "provider_leakage", lambda pt: "mechanism_only")
    assert rt._run_leakage("deepseek", "deepseek-chat") == "unvalidated"     # the model wins


# ── M57: silent LLM-degradation is surfaced (the claude/moonshot 401/400 finding) ──────────────────

class _RaisingProvider:
    """A provider whose LLM call hard-fails — models an unfunded (400) / invalid-key (401) account."""

    def __init__(self, exc: Exception | None = None):
        self._exc = exc or RuntimeError("Error code: 401 - Invalid Authentication")

    async def chat_completion(self, req):
        raise self._exc


def _raising_handle(reasoning: bool = True) -> LLMHandle:
    return LLMHandle(provider=_RaisingProvider(), model="m",
                     input_price_per_m=1.0, output_price_per_m=2.0, supports_reasoning=reasoning)


def _degraded_state(agent_mode: str = "full_ai", failures: int = 2):
    from src.backend.ai.research.state import Budget, GoalBrief, ResearchState

    st = ResearchState(goal=GoalBrief(goal_text="mean reversion on staples"), budget=Budget())
    st.agent_mode = agent_mode
    st.budget.llm_failures = failures
    return st


@pytest.mark.finding("M57")
def test_token_ledger_record_failure_propagates_to_budget():
    from src.backend.ai.research.agent_llm import TokenLedger
    from src.backend.ai.research.state import Budget

    b = Budget()
    ledger = TokenLedger(budget=b)
    ledger.record_failure(RuntimeError("401"))
    ledger.record_failure(RuntimeError("401"))
    # Counted on the ledger AND propagated to the Budget so it outlives the (discarded) ledger.
    assert ledger.n_failures == 2
    assert b.llm_failures == 2


@pytest.mark.finding("M57")
async def test_strategist_hard_failure_is_recorded_and_still_falls_back():
    from src.backend.ai.research.agent_llm import TokenLedger
    from src.backend.ai.research.state import Budget

    ledger = TokenLedger(budget=Budget())
    strat = LLMStrategist(_raising_handle(), ledger, RuleBasedStrategist())
    hyp, spec = await strat.propose("KO", ["mean_reversion"], [], {})
    assert spec["template_id"]                       # the run continues on the rule-based fallback
    assert ledger.budget.llm_failures == 1           # …but the silent degradation is now visible


@pytest.mark.finding("M57")
async def test_critic_hard_failure_is_recorded_and_still_falls_back():
    from src.backend.ai.research.agent_llm import TokenLedger
    from src.backend.ai.research.state import Budget

    ledger = TokenLedger(budget=Budget())
    critic = AdversarialCritic(llm=_raising_handle(), ledger=ledger)
    verdict = await critic.review({}, _metrics(), {})
    assert verdict["source"] == "heuristic"          # fell back to the heuristic critic
    assert ledger.budget.llm_failures == 1


@pytest.mark.finding("M57")
async def test_reporter_hard_failure_is_recorded():
    from src.backend.ai.research.agent_llm import TokenLedger
    from src.backend.ai.research.report_generator import generate_final_report, llm_narrate_report

    st = _degraded_state(failures=0)                 # start clean; the reporter call is what fails
    ledger = TokenLedger(budget=st.budget)
    report = generate_final_report(st)
    await llm_narrate_report(report, st, _raising_handle(), ledger)
    assert ledger.budget.llm_failures == 1           # templated-instead-of-LLM narrative is a degradation


@pytest.mark.finding("M57")
async def test_reporter_billed_but_all_sections_rejected_is_degraded():
    # The gemini-2.5-pro S9 case: the reporter LLM RESPONDS (and bills) but every section digit-leaks
    # (or is unparseable) → all templated. used_eur>0 yet the report is 100% rule-based. Must flag.
    import json as _json

    from src.backend.ai.research.report_generator import (
        _REPORT_SECTIONS, generate_final_report, llm_narrate_report, serialize_report)
    from src.backend.ai.research.agent_llm import TokenLedger

    digit_body = {k: "This strategy delivered a Sharpe of 1.2 and returned 34% over the window."
                  for k in _REPORT_SECTIONS}
    h = _handle(_json.dumps(digit_body), reasoning=True)     # every section contains digits → all rejected
    st = _degraded_state(failures=0)
    ledger = TokenLedger(budget=st.budget)
    report = generate_final_report(st)
    await llm_narrate_report(report, st, h, ledger)
    narr = " ".join(s["narrative"] for s in serialize_report(report)["sections"]).strip()
    assert not any(ch.isdigit() for ch in narr)      # the digit-leaking prose was correctly rejected…
    assert ledger.budget.llm_failures == 1           # …and the paid-but-fully-templated run is flagged
    assert st.llm_degraded() is True


@pytest.mark.finding("M57")
async def test_reporter_reasoning_model_gets_headroom_not_900():
    # H25 extended to the Reporter: a 900-token cap truncates a reasoner before its JSON → all templated.
    from src.backend.ai.research.report_generator import generate_final_report, llm_narrate_report

    st = _degraded_state(failures=0)
    reasoner = _handle('{"strategy_identity": "a brief search found nothing"}', reasoning=True)
    await llm_narrate_report(generate_final_report(st), st, reasoner, None)
    assert reasoner.provider.last_req.max_tokens == 4000

    non_reasoner = _handle('{"strategy_identity": "a brief search found nothing"}', reasoning=False)
    await llm_narrate_report(generate_final_report(st), st, non_reasoner, None)
    assert non_reasoner.provider.last_req.max_tokens == 900


@pytest.mark.finding("M57")
def test_research_state_llm_degraded_semantics():
    assert _degraded_state("full_ai", 2).llm_degraded() is True
    assert _degraded_state("ai_assisted", 1).llm_degraded() is True
    assert _degraded_state("full_ai", 0).llm_degraded() is False     # AI ran cleanly
    assert _degraded_state("rule_based", 5).llm_degraded() is False   # rule_based is never "degraded"


@pytest.mark.finding("M57")
def test_report_shows_degraded_banner_and_stays_digit_free():
    from src.backend.ai.research.report_generator import generate_final_report

    report = generate_final_report(_degraded_state("full_ai", 3))
    ident = report.strategy_identity
    assert "DEGRADED AI RUN" in ident.narrative               # the run admits it fell back
    assert "rule-based" in ident.narrative.lower()
    assert ident.numeric_fields["llm_call_failures"] == 3     # the count lives in numeric_fields…
    # …never in the prose (generate_final_report calls validate_narratives, which forbids digits).
    assert not any(ch.isdigit() for ch in ident.narrative)


@pytest.mark.finding("M57")
def test_report_has_no_degraded_banner_for_a_clean_run():
    from src.backend.ai.research.report_generator import generate_final_report

    report = generate_final_report(_degraded_state("full_ai", 0))
    assert "DEGRADED" not in report.strategy_identity.narrative
    assert "llm_call_failures" not in report.strategy_identity.numeric_fields


@pytest.mark.finding("M56")
def test_unknown_model_fallback_is_not_optimistically_mechanism_only(monkeypatch):
    # M56: for a run whose model is UNKNOWN (empty model_id — legacy rows / '' migration default), the
    # provider fallback must NOT upgrade it to mechanism_only just because a validated sibling exists…
    import src.backend.ai.research.router as rt

    monkeypatch.setattr(rt, "provider_leakage", lambda pt: "mechanism_only")
    assert rt._run_leakage("deepseek", "") == "unvalidated"      # pre-fix (M56): "mechanism_only"

    # …but a KNOWN provider-level risk is still surfaced (conservative — never hide risk).
    monkeypatch.setattr(rt, "provider_leakage", lambda pt: "risk")
    assert rt._run_leakage("gemini", "") == "risk"
