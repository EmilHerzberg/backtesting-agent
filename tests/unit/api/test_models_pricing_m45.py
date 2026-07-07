"""Phase 4-review — M45: the /models endpoint distinguishes a genuinely-free model (priced 0) from an
unpriced/unknown model (None). Pre-fix `if m.input_price_per_m` mapped Decimal('0') (falsy) to null, so
"free" was served as "unknown" and the free-model auto-pick path was unreachable. The M45 code lived
untested (tracker evidence "(code)"); this pins the None-vs-0 round-trip through the real endpoint mapping.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

import src.backend.api.routers.ai as ai_router


def _model(model_id: str, price):
    return SimpleNamespace(
        model_id=model_id, display_name=model_id, provider="p", description="",
        context_window=1000, input_price_per_m=price, output_price_per_m=price,
        supports_streaming=True, supports_tools=False, supports_vision=False,
        supports_reasoning=False, leakage="unvalidated",
    )


@pytest.mark.finding("M45")
async def test_models_endpoint_serializes_free_as_zero_and_unpriced_as_none(monkeypatch):
    monkeypatch.setattr(
        ai_router, "get_all_models",
        lambda: [_model("free", Decimal("0")), _model("unpriced", None)],
    )
    resp = await ai_router.list_models(_user_id=1, session=None)
    by_id = {r.model_id: r for r in resp}

    assert by_id["free"].input_price == 0.0          # genuinely FREE → 0 (pre-fix: None, "unknown")
    assert by_id["free"].output_price == 0.0
    assert by_id["unpriced"].input_price is None     # UNKNOWN → null (distinct from free)
    assert by_id["unpriced"].output_price is None
