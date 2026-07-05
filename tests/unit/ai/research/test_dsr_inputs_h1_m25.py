"""H1 + M25 — Deflated-Sharpe multiplicity inputs must be per-period and honestly counted.

H1 (found by six reviewers): the loop fed `np.var(annualized Sharpes)` into `deflated_sharpe()`'s
per-period `trial_sr_variance`, so the expected-max-Sharpe hurdle `sr0` was ~sqrt(252) too large and
the DSR pinned near 0 (kill-everything at >=20 trials, vacuous below).
M25: `n_trials` was `state.total_iterations` (padded with error/skip iterations) instead of the
number of trials that actually produced a Sharpe, and the variance/N scopes didn't match.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from src.backend.ai.research.loop import _dsr_registry_inputs, _period_sharpe, research_loop
from src.backend.ai.research.state import Budget, GoalBrief, Hypothesis, ResearchState
from src.backend.backtesting.gates.deflated_sharpe import DeflatedSharpeGate, deflated_sharpe
from src.backend.backtesting.gates.pipeline import GateContext


@pytest.mark.finding("H1")
def test_period_sharpe_is_per_period_not_annualized():
    returns = np.array([0.01, -0.005, 0.008, 0.002, -0.003, 0.006])
    expected = float(returns.mean() / returns.std(ddof=1))
    assert _period_sharpe(returns) == pytest.approx(expected)
    # Per-period magnitude — never the annualized value (~expected * sqrt(252)).
    assert abs(_period_sharpe(returns)) < 1.0


@pytest.mark.finding("H1")
def test_period_sharpe_none_on_degenerate_series():
    assert _period_sharpe(None) is None
    assert _period_sharpe([0.01]) is None                    # too short
    assert _period_sharpe([0.01, 0.01, 0.01]) is None        # zero variance
    assert _period_sharpe([0.01, float("nan"), 0.02]) is not None  # NaNs dropped, 2 finite remain


@pytest.mark.finding("H1")
def test_annualized_variance_collapses_dsr_but_per_period_discriminates():
    """The same strategy: per-period trial variance lets the DSR discriminate; the annualized
    variance the old loop fed collapses it to ~0 — the exact H1 symptom."""
    rng = np.random.default_rng(0)
    returns = rng.normal(0.0015, 0.008, 500)  # a solid per-period edge
    n_trials = 30
    var_period = 0.004

    dsr_period = deflated_sharpe(returns, n_trials, var_period)
    dsr_annual = deflated_sharpe(returns, n_trials, var_period * 252)  # what the buggy loop fed

    assert dsr_annual < 0.01           # collapsed to ~0 (H1)
    assert dsr_period > 0.2            # per-period units → the gate actually discriminates
    assert dsr_period > dsr_annual
    assert 0.0 < dsr_period <= 1.0


@pytest.mark.finding("M25")
def test_dsr_inputs_count_only_measured_trials_with_ddof1():
    samples = [0.05, 0.08, 0.03, 0.10]
    n, var, defaulted = _dsr_registry_inputs(samples)
    assert n == 4                                            # measured trials, not total_iterations
    assert var == pytest.approx(float(np.var(samples, ddof=1)))  # ddof=1 (fixes N6 too)
    assert defaulted is False
    # Too few measured trials → floored variance, explicitly flagged defaulted (M24), never a spurious 0.
    assert _dsr_registry_inputs([0.05]) == (1, 0.001, True)
    assert _dsr_registry_inputs([]) == (0, 0.001, True)


def _dsr_ctx(returns, *, n_trials, sr_variance, defaulted):
    return GateContext(
        metrics={}, trades=[], returns=returns, equity_curve=[],
        n_trials_global=n_trials, trial_sr_variance=sr_variance,
        trial_sr_variance_defaulted=defaulted,
    )


@pytest.mark.finding("M24")
def test_deflated_gate_flags_defaulted_variance_as_provisional():
    """A defaulted (unmeasured) variance is provisional and explicitly flagged — never a firm verdict,
    regardless of the magic floor value or the trial count."""
    returns = np.random.default_rng(1).normal(0.001, 0.01, 300)
    res = DeflatedSharpeGate().check(_dsr_ctx(returns, n_trials=50, sr_variance=0.001, defaulted=True))
    assert res.details.get("sr_variance_defaulted") is True
    assert res.details.get("provisional") is True


@pytest.mark.finding("M24")
def test_deflated_gate_measured_variance_not_flagged():
    """A real measured variance with enough trials yields a firm verdict, flagged not-defaulted."""
    returns = np.random.default_rng(2).normal(0.001, 0.01, 300)
    res = DeflatedSharpeGate().check(_dsr_ctx(returns, n_trials=50, sr_variance=0.02, defaulted=False))
    assert res.details.get("sr_variance_defaulted") is False
    assert not res.details.get("provisional")  # firm PASS/FAIL, not provisional


def _hyp():
    return Hypothesis(
        hypothesis_id=f"hyp_{uuid.uuid4().hex[:8]}", author="t", economic_rationale="r",
        claimed_mechanism="m", falsifiable_prediction="p", proposed_template_id="sma_crossover",
    )


def _spec(v):
    return {
        "strategy_hash": f"{'a' * 60}{v:04d}", "template_id": "sma_crossover",
        "params": {"fast_period": 10 + v, "slow_period": 50},
        "window_start": "2018-01-01", "window_end": "2022-12-31",
    }


@pytest.mark.finding("H1")
@pytest.mark.finding("M25")
@pytest.mark.asyncio
async def test_loop_feeds_per_period_variance_and_measured_count_to_gate():
    """P1-01: the load-bearing seam. The loop must pass PER-PERIOD trial-Sharpe variance and the
    MEASURED-trial count to update_registry_stats — not np.var(annualized sharpes) / total_iterations
    (the exact original H1/M25 bug). Reverting loop.py to feed _sharpe_values / total_iterations makes
    this test fail."""
    rng = np.random.default_rng(0)
    returns_list = [
        rng.normal(0.0015, 0.010, 300),
        rng.normal(0.0005, 0.012, 300),
        rng.normal(0.0025, 0.009, 300),
    ]
    period_sharpes = [_period_sharpe(r) for r in returns_list]

    state = ResearchState(
        goal=GoalBrief(goal_text="x", asset_pool=["AAPL"], strategy_families=["trend_following"],
                       target_candidates=99, max_runs=3),
        budget=Budget(max_runs=3),
    )

    cc = {"n": 0}

    async def propose(asset, strategy_families, failure_context, registry_summary):
        cc["n"] += 1
        return _hyp(), _spec(cc["n"])

    strategist = AsyncMock()
    strategist.propose = propose

    ci = {"i": 0}

    def run(spec, data, **kw):
        r = returns_list[min(ci["i"], len(returns_list) - 1)]
        ci["i"] += 1
        return {
            "sharpe_annual": float(np.mean(r) / np.std(r) * np.sqrt(252)),
            "total_return": 0.2, "max_drawdown": -0.1, "n_trades": 80,
            "exposure_time": 0.5, "returns": r, "buy_hold_return": 0.1,
        }

    executor = MagicMock()
    executor.run.side_effect = run
    gatekeeper = MagicMock()
    gatekeeper.evaluate.return_value = {"passed": True, "results": []}
    gatekeeper.update_registry_stats = MagicMock()
    critic = AsyncMock()
    critic.review.return_value = {"recommendation": "accept", "confidence": "medium", "weaknesses": []}
    data_agent = MagicMock()
    data_agent.prepare.return_value = "mock_df"

    await research_loop(state, strategist, executor, gatekeeper, critic, data_agent)

    calls = gatekeeper.update_registry_stats.call_args_list
    assert len(calls) >= 3
    last_n, last_var = calls[-1].args[0], calls[-1].args[1]
    # Measured-trial count (M25), and the PER-PERIOD variance (H1) — not the ~252x annualized one.
    assert last_n == 3
    assert last_var == pytest.approx(float(np.var(period_sharpes, ddof=1)))
    annual_var = float(np.var([float(np.mean(r) / np.std(r) * np.sqrt(252)) for r in returns_list], ddof=1))
    assert last_var != pytest.approx(annual_var, rel=1e-3)
