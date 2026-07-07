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
        bollinger_breakout, generator, macd_cross, multi_indicator, rsi_reversion,
        sentiment_aware_rebound, sma_crossover)

    # F2/TI-4: assert the CALL token ``self._gated_buy(`` (not just any substring a comment could satisfy)
    # across ALL SEVEN StrategyBase entry paths — including the generator's DynamicStrategy and
    # SentimentAwareRebound, the two H13 explicitly named that the old test OMITTED — and assert none opens
    # a long via a raw ``self.buy(`` on its entry path (which would bypass the gate).
    for mod in (macd_cross, multi_indicator, rsi_reversion, bollinger_breakout, sma_crossover,
                generator, sentiment_aware_rebound):
        src = inspect.getsource(mod)
        assert "self._gated_buy(" in src, mod.__name__      # entries route through the gate
        assert "self.buy(" not in src, mod.__name__          # …and never via a raw, ungated buy


@pytest.mark.finding("M14")
def test_create_with_params_rejects_unknown_key_but_accepts_valid_and_empty():
    from src.backend.backtesting.engine.exceptions import InvalidParameterError
    from src.backend.backtesting.strategies.sma_crossover import SMACrossover

    with pytest.raises(InvalidParameterError):
        SMACrossover.create_with_params(fast_perod=10, slow_period=30)   # typo → must be rejected
    # A valid pair and empty kwargs must NOT raise (no legitimate proposal is rejected).
    SMACrossover.create_with_params(fast_period=10, slow_period=30)
    SMACrossover.create_with_params()


@pytest.mark.finding("M14")
def test_every_registered_template_accepts_its_own_default_param_set():
    # Regression guard: M14's unknown-key check must never reject a LEGITIMATE proposal. Each registered
    # template's parameter_space keys are its own tunable class attributes with valid defaults, so
    # create_with_params(**defaults) must succeed — proving the space keys are all recognized.
    from src.backend.ai.research.executor import _ensure_registry

    for template_id, cls in _ensure_registry().items():
        space = cls.parameter_space()
        assert space, template_id
        defaults = {k: getattr(cls, k) for k in space}     # KeyError-free: space keys ARE class attrs
        cls.create_with_params(**defaults)                 # must not raise (valid keys + valid defaults)


@pytest.mark.finding("F3")
def test_gated_sell_full_equity_is_sell_max_not_one_share():
    from src.backend.backtesting.strategies.base import StrategyBase

    calls = []

    class _Fake:
        _event_gate_config = None      # no gate → passthrough

        def sell(self, **kw):
            calls.append(kw)

    _Fake._apply_event_gate = StrategyBase._apply_event_gate
    _Fake._gated_sell = StrategyBase._gated_sell
    _Fake()._gated_sell(1.0)
    assert calls == [{}]               # full-equity short → sell-max, NOT self.sell(size=1.0) (one share)


@pytest.mark.finding("F3")
def test_route_signal_short_entry_goes_through_the_gate():
    import inspect

    from src.backend.backtesting.strategies.base import StrategyBase

    src = inspect.getsource(StrategyBase.route_signal)
    assert "self._gated_sell()" in src   # SHORT entries are gated now (were a raw, ungated self.sell())


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
