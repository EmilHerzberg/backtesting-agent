"""1E — goal criteria: parse (M50), enforce in goal completion (C3), non-vacuous drawdown (H30).

Review: goal completion was decided on a raw candidate count; the user's typed Sharpe/drawdown/…
thresholds were parsed by dead code (M50) and, even if wired, the drawdown check was vacuous because
of a sign/scale/key mismatch (H30).
"""
from __future__ import annotations

import pytest

from src.backend.ai.goals.criteria import candidate_meets_criteria, parse_criteria
from src.backend.ai.research.state import Budget, Candidate, GoalBrief, ResearchState


def _cand(hash_: str, *, sharpe: float = 1.0, dd: float = -0.1, n: int = 50) -> Candidate:
    return Candidate(
        strategy_hash=hash_, run_id="", template_id="t", params={}, security_id="A",
        sharpe_annual=sharpe, total_return=0.2, max_drawdown=dd, n_trades=n,
    )


@pytest.mark.finding("M50")
def test_parse_emits_canonical_keys_and_abs_drawdown():
    p = parse_criteria("Finde 2 Strategien mit Sharpe > 2 und drawdown < 20%")
    assert p["target_count"] == 2
    by_metric = {c["metric"]: c for c in p["criteria"]}
    assert by_metric["sharpe_annual"]["op"] == ">=" and by_metric["sharpe_annual"]["value"] == 2.0
    dd = by_metric["max_drawdown"]
    assert dd["op"] == "<=" and dd["value"] == pytest.approx(0.20) and dd["abs"] is True


@pytest.mark.finding("H30")
def test_drawdown_criterion_rejects_regardless_of_sign():
    crit = parse_criteria("drawdown < 20%")["criteria"]
    # A 30% drawdown must FAIL a 20% limit — whether the candidate stores DD as +0.30 or -0.30.
    assert candidate_meets_criteria({"max_drawdown": 0.30}, crit) is False
    assert candidate_meets_criteria({"max_drawdown": -0.30}, crit) is False
    # A 15% drawdown passes.
    assert candidate_meets_criteria({"max_drawdown": -0.15}, crit) is True


@pytest.mark.finding("C3")
def test_goal_met_counts_only_criteria_satisfying_candidates():
    goal = GoalBrief(
        goal_text="Sharpe > 2", target_candidates=2,
        criteria=parse_criteria("Finde 2 mit Sharpe > 2")["criteria"],
    )
    state = ResearchState(goal=goal, budget=Budget())
    state.candidates = [_cand("a", sharpe=2.5), _cand("b", sharpe=0.8)]  # only 1 meets Sharpe ≥ 2
    assert state.goal_met() is False
    assert state.validated_count(oos_enabled=False) == 1
    state.candidates.append(_cand("c", sharpe=3.0))
    assert state.goal_met() is True


@pytest.mark.finding("C3")
def test_no_parsed_criteria_falls_back_to_raw_count():
    # A GoalBrief built directly (no parsed criteria) keeps the old raw-count behaviour.
    state = ResearchState(goal=GoalBrief(goal_text="x", target_candidates=2), budget=Budget())
    state.candidates = [_cand("a", sharpe=0.1), _cand("b", sharpe=0.1)]
    assert state.goal_met() is True
