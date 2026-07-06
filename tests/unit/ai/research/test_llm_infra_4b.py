"""Phase 4 / 4B mediums — LLM plumbing honesty (M42 JSON extraction, M44 unknown-pricing).

- M42: extract_json_object was a first-{ to last-} slice that discarded billed output on prose with a
  stray brace, two objects, or a raw newline in a string.
- M44: TokenLedger fabricated €0 for unpriced models, so used_eur read €0.0000 and the € cap never bound.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.backend.ai.research.agent_llm import LLMHandle, TokenLedger, extract_json_object


@pytest.mark.finding("M42")
def test_extract_json_recovers_output_the_old_slice_discarded():
    # Two objects → first one wins (old slice json.loads'd the whole span → None).
    assert extract_json_object('{"a": 1} then {"b": 2}') == {"a": 1}
    # Trailing prose containing a brace (old: last-} grabbed the stray brace → None).
    assert extract_json_object('{"a": 1} done }') == {"a": 1}
    # Raw newline inside a string (old: strict json.loads rejected the control char → None).
    assert extract_json_object('{"note": "line1\nline2"}') == {"note": "line1\nline2"}
    # Code fence is unwrapped.
    assert extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    # Genuinely no object → None.
    assert extract_json_object("no json here at all") is None


def _handle(inp, out):
    return LLMHandle(provider=None, model="m", input_price_per_m=inp, output_price_per_m=out)


@pytest.mark.finding("M44")
def test_ledger_does_not_fabricate_zero_cost_for_unpriced_model():
    led = TokenLedger(budget=SimpleNamespace(used_eur=0.0))
    usage = SimpleNamespace(prompt_tokens=1_000, completion_tokens=1_000)

    led.record(usage, _handle(None, None))          # unknown pricing
    assert led.cost_known is False
    assert led.cost_eur == 0.0                       # NOT a fabricated cost
    assert led.prompt_tokens == 1_000 and led.n_calls == 1   # tokens still tracked

    # A genuinely-priced model still accrues cost and doesn't flip cost_known back on falsely.
    led.record(SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=1_000_000), _handle(1.0, 2.0))
    assert led.cost_eur == pytest.approx(3.0)
    assert led.cost_known is False                   # once unknown, stays unknown for the run


@pytest.mark.finding("M44")
def test_ledger_free_model_is_zero_not_unknown():
    led = TokenLedger(budget=SimpleNamespace(used_eur=0.0))
    led.record(SimpleNamespace(prompt_tokens=1_000, completion_tokens=1_000), _handle(0.0, 0.0))
    assert led.cost_known is True                    # 0.0 is a KNOWN (free) price, not unknown
    assert led.cost_eur == 0.0
