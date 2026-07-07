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


@pytest.mark.finding("M13")
def test_gated_buy_full_equity_is_buy_max_not_one_share():
    from src.backend.backtesting.strategies.base import StrategyBase

    calls = []

    class _Fake:
        _event_gate_config = None      # no gate → passthrough

        def buy(self, **kw):
            calls.append(kw)

    _Fake._apply_event_gate = StrategyBase._apply_event_gate
    _Fake._gated_buy = StrategyBase._gated_buy
    _Fake()._gated_buy(1.0)
    assert calls == [{}]               # full-equity intent → buy-max, NOT self.buy(size=1.0) (one share)


@pytest.mark.finding("M13")
def test_gated_buy_reduce_passes_a_fraction():
    from src.backend.backtesting.strategies.base import StrategyBase

    calls = []

    class _Fake:
        def buy(self, **kw):
            calls.append(kw)

        def _apply_event_gate(self, allow, size):
            return True, 0.5, None     # REDUCE gate → half size

    _Fake._gated_buy = StrategyBase._gated_buy
    _Fake()._gated_buy(1.0)
    assert calls == [{"size": 0.5}]


@pytest.mark.finding("H13")
def test_all_templates_enter_through_the_event_gate():
    import inspect

    from src.backend.backtesting.strategies import (
        bollinger_breakout, macd_cross, multi_indicator, rsi_reversion, sma_crossover)

    for mod in (macd_cross, multi_indicator, rsi_reversion, bollinger_breakout, sma_crossover):
        assert "_gated_buy" in inspect.getsource(mod), mod.__name__   # entries go through the gate now


@pytest.mark.finding("M60")
def test_regime_labels_come_from_market_not_strategy_equity():
    import numpy as np

    from src.backend.ai.research.loop import _compute_regime_analysis

    market = np.zeros(90)             # FLAT market → every sub-period is "sideways"
    strategy = np.full(90, 0.01)      # but the strategy made money
    r = _compute_regime_analysis(market, strategy_returns=strategy)
    assert r and all(seg["type"] == "sideways" for seg in r.values())   # labeled from the MARKET, not equity
    assert all(seg["return"] > 0 for seg in r.values())                 # strategy's own return still reported


@pytest.mark.finding("M28")
def test_regime_failed_candidate_does_not_count_toward_the_goal():
    st = _state([_cand("v", "regime_validated"), _cand("f", "regime_failed")])
    # regime mode disables OOS; a regime_failed idea must NOT be counted (pre-fix: both counted → goal_met
    # could fire on failed ideas and stop the search).
    assert st.validated_count(oos_enabled=False) == 1
    assert not st.goal_met()                  # only 1 counts, target is 2
