"""W3 unit tests — LLM Reporter narration (mock provider, €0; no real API call)."""

import json
import re

import pytest
from unittest.mock import AsyncMock

from src.backend.ai.models import ChatResponse, TokenUsage
from src.backend.ai.research.agent_llm import LLMHandle, TokenLedger
from src.backend.ai.research.report_generator import (
    _REPORT_SECTIONS,
    _descriptors,
    generate_final_report,
    llm_narrate_report,
)
from src.backend.ai.research.state import (
    Budget,
    Candidate,
    FailureContext,
    GoalBrief,
    ResearchState,
)


def _llm(supports_json=True, in_p=1.0, out_p=2.0):
    prov = AsyncMock()
    handle = LLMHandle(provider=prov, model="m", input_price_per_m=in_p,
                       output_price_per_m=out_p, supports_json_mode=supports_json)
    return handle, prov


def _resp(content, prompt=1000, completion=200):
    return ChatResponse(
        model="m", provider="p", content=content,
        usage=TokenUsage(prompt_tokens=prompt, completion_tokens=completion,
                         total_tokens=prompt + completion),
    )


def _state(n_candidates=1, trials=8, gate="benchmark_relative"):
    goal = GoalBrief(goal_text="t", asset_pool=["AAPL"],
                     strategy_families=["trend_following"], target_candidates=1, max_runs=20)
    st = ResearchState(goal=goal, budget=Budget(max_runs=20))
    st.total_iterations = trials
    for i in range(trials):
        st.all_failures.append(FailureContext(
            strategy_hash=f"h{i}", template_id="sma_crossover", params={},
            security_id="AAPL", failed_gate=gate))
    for i in range(n_candidates):
        st.candidates.append(Candidate(
            strategy_hash=f"c{i}", run_id="r", template_id="sma_crossover", params={},
            security_id="AAPL", sharpe_annual=1.2, total_return=0.3, max_drawdown=-0.15,
            n_trades=60, benchmark={"buy_hold_return": 0.2}))
    return st


def _clean_json(extra=None):
    data = {k: f"Qualitative note for {k} without any figure." for k in _REPORT_SECTIONS}
    if extra:
        data.update(extra)
    return json.dumps(data)


async def test_narratives_replaced_and_recorded():
    st = _state()
    report = generate_final_report(st)
    llm, prov = _llm(in_p=2.0, out_p=4.0)
    prov.chat_completion.return_value = _resp(_clean_json(), prompt=1_000_000, completion=500_000)
    led = TokenLedger(budget=st.budget)
    await llm_narrate_report(report, st, llm, led)
    assert report.strategy_identity.narrative == "Qualitative note for strategy_identity without any figure."
    assert report.oos_status.narrative == "Qualitative note for oos_status without any figure."
    report.validate_narratives()                          # clean -> passes
    assert led.cost_eur == pytest.approx(4.0)             # 2.0*1 + 4.0*0.5
    prov.chat_completion.assert_awaited_once()


async def test_digit_leak_falls_back_per_section():
    st = _state()
    report = generate_final_report(st)
    tmpl_hyp = report.hypothesis.narrative                 # capture template
    llm, prov = _llm()
    prov.chat_completion.return_value = _resp(_clean_json({"hypothesis": "We tried 8 templates."}))
    await llm_narrate_report(report, st, llm, TokenLedger(budget=st.budget))
    assert report.hypothesis.narrative == tmpl_hyp         # leaked digit -> template kept
    assert report.strategy_identity.narrative.startswith("Qualitative note")  # clean -> LLM
    report.validate_narratives()


async def test_missing_key_keeps_template():
    st = _state()
    report = generate_final_report(st)
    tmpl_oos = report.oos_status.narrative
    data = {k: f"Qualitative note for {k}." for k in _REPORT_SECTIONS if k != "oos_status"}
    llm, prov = _llm()
    prov.chat_completion.return_value = _resp(json.dumps(data))
    await llm_narrate_report(report, st, llm, TokenLedger(budget=st.budget))
    assert report.oos_status.narrative == tmpl_oos         # missing -> template
    assert report.strategy_identity.narrative.startswith("Qualitative note")


async def test_no_digit_in_prompt():
    st = _state()
    report = generate_final_report(st)
    llm, prov = _llm()
    prov.chat_completion.return_value = _resp(_clean_json())
    await llm_narrate_report(report, st, llm, TokenLedger(budget=st.budget))
    req = prov.chat_completion.call_args.args[0]
    user_msg = next(m.content for m in req.messages if m.role == "user")
    assert re.search(r"\d", user_msg) is None              # descriptors are digit-free (W3-2/AC-7)
    assert req.max_tokens <= 900
    assert req.json_mode is True


async def test_numeric_fields_untouched():
    st = _state()
    report = generate_final_report(st)
    before = dict(report.benchmark_comparison.numeric_fields)
    llm, prov = _llm()
    prov.chat_completion.return_value = _resp(_clean_json())
    await llm_narrate_report(report, st, llm, TokenLedger(budget=st.budget))
    assert report.benchmark_comparison.numeric_fields == before
    assert report.benchmark_comparison.numeric_fields["best_sharpe"] == 1.2


def test_honest_tone_wiring_zero_candidates():
    st = _state(n_candidates=0)
    d = _descriptors(st)
    assert d["outcome"] == "nothing survived"
    assert d["dominant_kill_reason"] == "failing to beat buy-and-hold"   # friendly map (W3S-2)
    assert re.search(r"\d", json.dumps(d)) is None                       # no digit anywhere


@pytest.mark.finding("M46")
def test_oos_descriptor_is_honest_tri_state():
    from src.backend.ai.research.state import OOSResult

    st = _state(n_candidates=2)
    # 1 PASS + 1 FAIL must NOT be narrated as "passed out-of-sample" (a single PASS ≠ the run passing).
    st.oos_results = [OOSResult(strategy_hash="c0", lineage_id="l", outcome="PASS"),
                      OOSResult(strategy_hash="c1", lineage_id="l", outcome="FAIL")]
    assert _descriptors(st)["oos"] == "mixed out-of-sample results (some passed, some failed)"
    # all-UNEVALUATED (thin sample / data outage) must NOT be narrated as "failed out-of-sample".
    st.oos_results = [OOSResult(strategy_hash="c0", lineage_id="l", outcome="UNEVALUATED")]
    assert _descriptors(st)["oos"] == "out-of-sample inconclusive (too few trades)"
    assert re.search(r"\d", json.dumps(_descriptors(st))) is None        # stays digit-free (AC-7)


@pytest.mark.finding("M46")
def test_missing_benchmark_is_not_a_beat():
    st = _state(n_candidates=1)
    st.candidates[0].benchmark = {}          # no benchmark to compare against
    st.candidates[0].total_return = 0.3      # positive return
    assert _descriptors(st)["vs_benchmark"] == "benchmark unavailable"   # pre-fix: "beat buy-and-hold"


@pytest.mark.finding("M46")
def test_uncomputable_benchmark_sentinel_is_not_a_beat():
    # M46 (live path): the runner coalesces an UNCOMPUTABLE buy-and-hold to the float 0.0 — which the loop
    # actually builds (benchmark dict with buy_hold_return=0.0), so a None-only guard was dead in production.
    # Key on benchmark_available instead of the 0.0 sentinel.
    st = _state(n_candidates=1)
    st.candidates[0].benchmark = {"buy_hold_return": 0.0, "benchmark_available": False}
    st.candidates[0].total_return = 0.3      # positive return
    assert _descriptors(st)["vs_benchmark"] == "benchmark unavailable"   # pre-fix: "beat buy-and-hold" (0.3 > 0.0)


async def test_honest_tone_in_prompt():
    st = _state(n_candidates=0)
    report = generate_final_report(st)
    llm, prov = _llm()
    prov.chat_completion.return_value = _resp(_clean_json())
    await llm_narrate_report(report, st, llm, TokenLedger(budget=st.budget))
    user_msg = next(m.content for m in prov.chat_completion.call_args.args[0].messages if m.role == "user")
    assert "nothing survived" in user_msg


async def test_over_budget_skips_call():
    st = _state()
    report = generate_final_report(st)
    tmpl = report.strategy_identity.narrative
    b = Budget(max_runs=20, max_eur=1.0)
    b.used_eur = 1.0                                        # at the cap
    llm, prov = _llm()
    await llm_narrate_report(report, st, llm, TokenLedger(budget=b))
    prov.chat_completion.assert_not_awaited()              # pre-call guard
    assert report.strategy_identity.narrative == tmpl       # templated


async def test_api_error_falls_back_to_templates():
    st = _state()
    report = generate_final_report(st)
    tmpl = report.strategy_identity.narrative
    llm, prov = _llm()
    prov.chat_completion.side_effect = RuntimeError("boom")
    await llm_narrate_report(report, st, llm, TokenLedger(budget=st.budget))
    assert report.strategy_identity.narrative == tmpl
    report.validate_narratives()


async def test_unparseable_falls_back():
    st = _state()
    report = generate_final_report(st)
    tmpl = report.strategy_identity.narrative
    llm, prov = _llm()
    prov.chat_completion.return_value = _resp("sorry, no json here")
    await llm_narrate_report(report, st, llm, TokenLedger(budget=st.budget))
    assert report.strategy_identity.narrative == tmpl       # data={} -> all templated
    assert prov.chat_completion.await_count <= 1            # one call


async def test_json_mode_gated():
    st = _state()
    report = generate_final_report(st)
    llm, prov = _llm(supports_json=False)
    prov.chat_completion.return_value = _resp(_clean_json())
    await llm_narrate_report(report, st, llm, TokenLedger(budget=st.budget))
    assert prov.chat_completion.call_args.args[0].json_mode is False
