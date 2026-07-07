"""Phase 5 / 5B — planner routing (M15) + regime goal-counting (M28)."""
from __future__ import annotations

import pytest

from src.backend.ai.research.state import Budget, Candidate, GoalBrief, ResearchState


@pytest.mark.finding("M15")
def test_breakout_keyword_routes_to_trend_following_not_mean_reversion():
    from src.backend.ai.goals.planner import parse_goal_scope

    scope = parse_goal_scope("find me a breakout strategy")
    pool = scope.strategy_pool                # families resolved to strategy CLASSES
    assert any(c in pool for c in ("SMACrossover", "MACDSignalCross"))   # trend-following classes
    assert "BollingerBreakout" not in pool    # no longer mis-routed to the mean-reversion family


def _cand(hash_, status):
    return Candidate(strategy_hash=hash_, run_id="r", template_id="t", params={}, security_id="AAPL",
                     validation_status=status)


def _state(cands):
    st = ResearchState(
        goal=GoalBrief(goal_text="t", asset_pool=["AAPL"], strategy_families=["trend_following"],
                       target_candidates=2, max_runs=20),
        budget=Budget(max_runs=20),
    )
    st.candidates = cands
    return st


@pytest.mark.finding("M28")
def test_regime_failed_candidate_does_not_count_toward_the_goal():
    st = _state([_cand("v", "regime_validated"), _cand("f", "regime_failed")])
    # regime mode disables OOS; a regime_failed idea must NOT be counted (pre-fix: both counted → goal_met
    # could fire on failed ideas and stop the search).
    assert st.validated_count(oos_enabled=False) == 1
    assert not st.goal_met()                  # only 1 counts, target is 2
