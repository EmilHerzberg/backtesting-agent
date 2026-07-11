"""valconf §5.6 — the OOS confidence tier + Sharpe CI are surfaced through the ``/candidates`` serializer,
which is the data source for the OOS-CI frontend chip (the console polls this endpoint; the SSE event alone
never reaches the candidate list). The chip rides beside the PASS/FAIL/UNEVALUATED verdict as evidence."""
from __future__ import annotations

import pytest

from src.backend.ai.research import router as research_router
from src.backend.ai.research.router import RunRecord, get_run_candidates
from src.backend.ai.research.state import (
    Budget,
    Candidate,
    GoalBrief,
    OOSResult,
    ResearchState,
)


def _state_with(cand_hashes: list[str], oos_results: list[OOSResult]) -> ResearchState:
    state = ResearchState(
        goal=GoalBrief(goal_text="t", asset_pool=["AAPL"], target_candidates=1),
        budget=Budget(max_runs=10),
    )
    state.candidates = [
        Candidate(strategy_hash=h, run_id="r", template_id="sma", params={}, security_id="AAPL")
        for h in cand_hashes
    ]
    state.oos_results = oos_results
    return state


@pytest.mark.finding("valconf-oos-chip")
async def test_oos_ci_is_surfaced_on_the_candidate_response():
    uid = 7
    oos = OOSResult(
        strategy_hash="h1", lineage_id="l", outcome="PASS",
        confidence_tier="moderate", basis="per_trade", ci_low=0.30, ci_high=1.80, ci_level=0.90,
        in_market_sharpe=1.24, in_market_ci_low=0.78, in_market_ci_high=1.90,
    )
    research_router._runs["g1"] = RunRecord(goal_id="g1", user_id=uid, state=_state_with(["h1"], [oos]))
    try:
        out = await get_run_candidates("g1", uid)
    finally:
        research_router._runs.pop("g1", None)

    assert len(out) == 1
    c = out[0]
    assert c.oos_outcome == "PASS"                                  # the verdict (unchanged contract)
    assert c.oos["confidence_tier"] == "moderate"                  # … with the tier + CI riding alongside
    assert c.oos["basis"] == "per_trade"
    assert (c.oos["ci_low"], c.oos["ci_high"], c.oos["ci_level"]) == (0.30, 1.80, 0.90)
    # valconf in-market masking: the edge-when-deployed Sharpe + CI ride along too
    assert c.oos["in_market_sharpe"] == 1.24
    assert (c.oos["in_market_ci_low"], c.oos["in_market_ci_high"]) == (0.78, 1.90)


@pytest.mark.finding("valconf-oos-chip")
async def test_no_result_or_recover_path_leaves_oos_empty_so_no_chip_renders():
    uid = 7
    # h1 has no OOSResult; h2 has one from the RECOVER path (no fresh assessment → empty tier).
    recover = OOSResult(strategy_hash="h2", lineage_id="l", outcome="PASS", confidence_tier="")
    research_router._runs["g2"] = RunRecord(
        goal_id="g2", user_id=uid, state=_state_with(["h1", "h2"], [recover]),
    )
    try:
        out = await get_run_candidates("g2", uid)
    finally:
        research_router._runs.pop("g2", None)

    by_hash = {c.strategy_hash: c for c in out}
    # no result → PENDING verdict, empty oos (the chip only renders when a tier is present)
    assert by_hash["h1"].oos == {} and by_hash["h1"].oos_outcome == "PENDING"
    # recover path → the verdict is replayed, but there is no fresh CI, so no chip
    assert by_hash["h2"].oos == {} and by_hash["h2"].oos_outcome == "PASS"
