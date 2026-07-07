"""W2 unit tests — LLM Strategist path (mock provider, €0; no real API call)."""

import json
from unittest.mock import AsyncMock

import pytest

from src.backend.ai.models import ChatResponse, TokenUsage
from src.backend.ai.research.agent_llm import LLMHandle, TokenLedger
from src.backend.ai.research.state import Budget, FailureContext
from src.backend.ai.research.strategist import (
    BAR_SIZE,
    FAMILY_MAP,
    TEMPLATES,
    WINDOW_END,
    WINDOW_START,
    LLMStrategist,
    RuleBasedStrategist,
)

FAM = next(iter(FAMILY_MAP))            # a real family
TID = FAMILY_MAP[FAM][0]               # a template in that family
SPACE = TEMPLATES[TID]


def _params_at(frac: float) -> dict:
    out = {}
    for k, ps in SPACE.items():
        v = ps["low"] + frac * (ps["high"] - ps["low"])
        out[k] = int(round(v)) if ps.get("type") == "int" else float(v)
    return out


def _resp(d, prompt=500, completion=150):
    return ChatResponse(
        model="m", provider="p", content=json.dumps(d),
        usage=TokenUsage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion),
    )


def _resp_raw(text, prompt=10, completion=10):
    return ChatResponse(model="m", provider="p", content=text,
                        usage=TokenUsage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=20))


def _strat(supports_json=True, max_eur=5.0):
    prov = AsyncMock()
    llm = LLMHandle(provider=prov, model="m", input_price_per_m=1.0, output_price_per_m=1.0,
                    supports_json_mode=supports_json)
    led = TokenLedger(budget=Budget(max_runs=10, max_eur=max_eur))
    fb = RuleBasedStrategist(seed=7)
    return LLMStrategist(llm=llm, ledger=led, fallback=fb), prov, led, fb


def _in_bounds(params):
    for k, ps in SPACE.items():
        assert ps["low"] <= params[k] <= ps["high"], f"{k}={params[k]} out of [{ps['low']},{ps['high']}]"


def _strat_win(ws, we):
    prov = AsyncMock()
    llm = LLMHandle(provider=prov, model="m", input_price_per_m=1.0, output_price_per_m=1.0, supports_json_mode=True)
    led = TokenLedger(budget=Budget(max_runs=10, max_eur=5.0))
    fb = RuleBasedStrategist(seed=7, window_start=ws, window_end=we)
    return LLMStrategist(llm=llm, ledger=led, fallback=fb, window_start=ws, window_end=we), prov


# ── P1: regime window plumbing + C-6 (the LLM never chooses the window) ──

async def test_rulebased_stamps_custom_window():
    s = RuleBasedStrategist(seed=1, window_start="2022-01-01", window_end="2023-06-30")
    _, spec = await s.propose("SPY", [FAM], [], {})
    assert (spec["window_start"], spec["window_end"]) == ("2022-01-01", "2023-06-30")


async def test_rulebased_default_window_unchanged():
    s = RuleBasedStrategist(seed=1)
    _, spec = await s.propose("SPY", [FAM], [], {})
    assert (spec["window_start"], spec["window_end"]) == (WINDOW_START, WINDOW_END)


def test_repair_params_enforces_sma_fast_slow():
    from src.backend.ai.research.strategist import _repair_params
    assert _repair_params("sma_crossover", {"fast_period": 47, "slow_period": 29})["slow_period"] == 52  # bumped
    assert _repair_params("sma_crossover", {"fast_period": 10, "slow_period": 50})["slow_period"] == 50  # ok
    assert _repair_params("rsi_reversion", {"period": 14}) == {"period": 14}                              # untouched


async def test_llm_window_is_run_config_not_llm_choice():
    # C-6: even if the LLM emits a rogue window, the spec uses the run-config window.
    strat, prov = _strat_win("2021-03-01", "2022-03-01")
    prov.chat_completion.return_value = _resp({
        "template_id": TID, "params": _params_at(0.5),
        "window_start": "1999-01-01", "window_end": "2000-01-01"})  # rogue — must be ignored
    _, spec = await strat.propose("AAPL", [FAM], [], {})
    assert (spec["window_start"], spec["window_end"]) == ("2021-03-01", "2022-03-01")


async def test_valid_proposal_parsed_and_recorded():
    strat, prov, led, fb = _strat()
    prov.chat_completion.return_value = _resp({
        "template_id": TID, "params": _params_at(0.5),
        "economic_rationale": "mean reversion after dips", "claimed_mechanism": "overreaction",
        "falsifiable_prediction": "Sharpe > 0.5"})
    hyp, spec = await strat.propose("AAPL", [FAM], [], {})
    assert spec["template_id"] == TID
    _in_bounds(spec["params"])
    assert hyp.author == "llm_strategist"
    assert led.prompt_tokens == 500 and led.n_calls == 1   # billed
    assert fb._tried_hashes == {spec["strategy_hash"]}     # shared dedup set


async def test_out_of_bounds_clamped():
    strat, prov, _, _ = _strat()
    huge = {k: ps["high"] + 1000 for k, ps in SPACE.items()}
    prov.chat_completion.return_value = _resp({"template_id": TID, "params": huge})
    _, spec = await strat.propose("AAPL", [FAM], [], {})
    _in_bounds(spec["params"])                              # clamped into range


@pytest.mark.finding("M38")
async def test_majority_invented_params_fall_back_to_rule_based():
    # M38: when the system invents MORE THAN HALF the params, the LLM's stored rationale can't honestly
    # describe the executed spec → fall back to rule-based rather than run invented params under the LLM
    # narrative. The nearest prior test (test_out_of_bounds_clamped) only asserted _in_bounds, which the
    # rule-based fallback params ALSO satisfy, so it never gated this threshold.
    if len(SPACE) < 2:
        pytest.skip("template has <2 params — the >half threshold is degenerate")
    strat, prov, _, _ = _strat()
    prov.chat_completion.return_value = _resp({"template_id": TID, "params": {}})   # ALL midpoint-filled
    hyp, _ = await strat.propose("AAPL", [FAM], [], {})
    assert hyp.author == "rule_based_strategist"           # pre-fix: ran the fully-invented spec as "llm"

    prov.chat_completion.return_value = _resp({"template_id": TID, "params": "not-a-dict"})
    hyp2, _ = await strat.propose("AAPL", [FAM], [], {})
    assert hyp2.author == "rule_based_strategist"          # non-dict params → all invented → fallback


@pytest.mark.finding("M38")
async def test_one_invented_param_stays_llm_and_records_provenance():
    if len(SPACE) < 2:
        pytest.skip("template has <2 params")
    strat, prov, _, _ = _strat()
    one_missing = _params_at(0.5)
    dropped = next(iter(SPACE))
    del one_missing[dropped]                               # exactly ONE param invented (midpoint-filled)
    prov.chat_completion.return_value = _resp({"template_id": TID, "params": one_missing})
    hyp, spec = await strat.propose("AAPL", [FAM], [], {})
    assert hyp.author == "llm_strategist"                  # ≤half invented → still trusts the LLM narrative
    assert any(dropped in r and "midpoint" in r for r in spec["repaired"])   # M38 provenance recorded


async def test_unknown_template_falls_back():
    strat, prov, _, _ = _strat()
    prov.chat_completion.return_value = _resp({"template_id": "totally_bogus", "params": {}})
    hyp, _ = await strat.propose("AAPL", [FAM], [], {})
    assert hyp.author == "rule_based_strategist"            # fallback


async def test_duplicate_falls_back():
    strat, prov, _, fb = _strat()
    params = _params_at(0.5)
    from src.backend.ai.research.strategist import _compute_strategy_hash
    fb._tried_hashes.add(_compute_strategy_hash(TID, params, "AAPL"))   # already tried
    prov.chat_completion.return_value = _resp({"template_id": TID, "params": params})
    hyp, _ = await strat.propose("AAPL", [FAM], [], {})
    assert hyp.author == "rule_based_strategist"


async def test_window_is_system_fixed():
    strat, prov, _, _ = _strat()
    prov.chat_completion.return_value = _resp({
        "template_id": TID, "params": _params_at(0.5),
        "window_start": "1999-01-01", "window_end": "2001-01-01", "bar_size": "1h"})  # LLM tries to set them
    _, spec = await strat.propose("AAPL", [FAM], [], {})
    assert spec["window_start"] == WINDOW_START and spec["window_end"] == WINDOW_END
    assert spec["bar_size"] == BAR_SIZE


async def test_hypothesis_spec_consistency():
    strat, prov, _, _ = _strat()
    prov.chat_completion.return_value = _resp({"template_id": TID, "params": _params_at(0.4)})
    hyp, spec = await strat.propose("AAPL", [FAM], [], {})
    assert hyp.proposed_template_id == spec["template_id"]
    assert hyp.hypothesis_id


async def test_isolation_spec_has_no_rationale():
    strat, prov, _, _ = _strat()
    prov.chat_completion.return_value = _resp({
        "template_id": TID, "params": _params_at(0.5), "economic_rationale": "SECRET"})
    _, spec = await strat.propose("AAPL", [FAM], [], {})
    assert "economic_rationale" not in spec and "claimed_mechanism" not in spec


async def test_failure_context_in_prompt():
    strat, prov, _, _ = _strat()
    fc = [FailureContext(strategy_hash="h", template_id=TID, params={"x": 1},
                         security_id="AAPL", failed_gate="minimum_activity")]
    prov.chat_completion.return_value = _resp({"template_id": TID, "params": _params_at(0.5)})
    await strat.propose("AAPL", [FAM], fc, {})
    user = next(m.content for m in prov.chat_completion.call_args.args[0].messages if m.role == "user")
    assert "minimum_activity" in user and TID in user


async def test_over_budget_skips_llm():
    strat, prov, led, _ = _strat(max_eur=1.0)
    led.budget.used_eur = 1.0          # at cap
    hyp, _ = await strat.propose("AAPL", [FAM], [], {})
    prov.chat_completion.assert_not_awaited()
    assert hyp.author == "rule_based_strategist"


async def test_api_error_and_unparseable_fall_back():
    strat, prov, _, _ = _strat()
    prov.chat_completion.side_effect = RuntimeError("boom")
    hyp, _ = await strat.propose("AAPL", [FAM], [], {})
    assert hyp.author == "rule_based_strategist"
    prov.chat_completion.side_effect = None
    prov.chat_completion.return_value = _resp_raw("not json at all")
    hyp2, _ = await strat.propose("AAPL", [FAM], [], {})
    assert hyp2.author == "rule_based_strategist"


async def test_out_of_family_template_rejected():
    # request a family; the LLM returns a template that is NOT in it -> reject -> fallback.
    in_fam = set(FAMILY_MAP[FAM])
    foreign = next((t for t in TEMPLATES if t not in in_fam), None)
    assert foreign is not None, "need a template outside the family for this test"
    strat, prov, _, _ = _strat()
    prov.chat_completion.return_value = _resp({"template_id": foreign, "params": _params_at(0.5)})
    hyp, spec = await strat.propose("AAPL", [FAM], [], {})
    assert hyp.author == "rule_based_strategist"      # foreign template -> fallback
    assert spec["template_id"] in in_fam              # the fallback stays in-family
