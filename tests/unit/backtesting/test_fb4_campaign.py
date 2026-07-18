"""FB4 (campaign-wide OOS multiplicity control) + RT2 (guarded advisory stage-1)."""

import pytest

from src.backend.ai.research.loop import _oos_verdict
from src.backend.backtesting.lockbox.service import (
    CAMPAIGN_OOS_BUDGET,
    BudgetExhaustedError,
    OOSLockboxService,
    OOSOutcome,
    PromotionToken,
)


def _svc(tmp_path):
    return OOSLockboxService(db_path=str(tmp_path / "lockbox.db"))


def _token(i):
    return PromotionToken(approver="t", strategy_hash=f"hash_{i:04d}", lineage_id=f"lin_{i:04d}")


@pytest.mark.finding("FB4")
def test_campaign_ledger_counts_only_terminal_verdicts(tmp_path):
    svc = _svc(tmp_path)
    for i, raw in enumerate([OOSOutcome.PASS, OOSOutcome.UNEVALUATED, OOSOutcome.FAIL]):
        svc.ensure_budget(f"lin_{i:04d}")
        svc.evaluate(_token(i), run_oos_backtest=lambda r=raw: r, campaign_scope="scope_a")
    assert svc.campaign_tests("scope_a") == 2      # UNEVALUATED spends nothing
    assert svc.campaign_tests("scope_b") == 0      # scopes are isolated


@pytest.mark.finding("FB4")
def test_campaign_cap_depletes_into_honest_absence(tmp_path):
    svc = _svc(tmp_path)
    for i in range(CAMPAIGN_OOS_BUDGET):           # burn the whole campaign budget
        svc.ensure_budget(f"lin_{i:04d}")
        svc.evaluate(_token(i), run_oos_backtest=lambda: OOSOutcome.FAIL,
                     campaign_scope="scope_a")
    svc.ensure_budget("lin_9999")
    with pytest.raises(BudgetExhaustedError):      # volume cannot buy more lottery tickets
        svc.evaluate(PromotionToken("t", "hash_9999", "lin_9999"),
                     run_oos_backtest=lambda: OOSOutcome.PASS, campaign_scope="scope_a")
    # a DIFFERENT campaign scope is unaffected
    svc.ensure_budget("lin_8888")
    assert svc.evaluate(PromotionToken("t", "hash_8888", "lin_8888"),
                        run_oos_backtest=lambda: OOSOutcome.PASS,
                        campaign_scope="scope_b") is OOSOutcome.PASS


@pytest.mark.finding("FB4")
def test_family_bar_is_the_fixed_budget_sidak_constant():
    # Review fix (blocker): the sequential (m=spent+1) scheme leaked FWER 20.6% at the budget.
    # True control = the SAME budget-sized bar for every test, order-free by construction.
    t0 = OOSLockboxService.campaign_adjusted_t(0)
    t49 = OOSLockboxService.campaign_adjusted_t(49)
    assert t0 == pytest.approx(3.083, abs=0.005)
    assert t49 == t0                               # count-independent: no order gaming


@pytest.mark.finding("FB4")
def test_family_wise_false_pass_rate_is_controlled_at_the_target():
    # The spec's acceptance simulation (safety doc line 231): across the FULL 50-test budget of
    # independent null hypotheses, the probability that ANY test clears the bar stays at ~alpha.
    import numpy as np

    from src.backend.backtesting.lockbox.service import (
        CAMPAIGN_ALPHA_FAMILY,
    )
    rng = np.random.default_rng(20260718)
    bar = OOSLockboxService.campaign_adjusted_t(0)
    n_families = 20_000
    t_stats = rng.standard_normal((n_families, CAMPAIGN_OOS_BUDGET))  # null: no edge
    fwer = float((t_stats > bar).any(axis=1).mean())
    assert fwer <= CAMPAIGN_ALPHA_FAMILY + 0.006   # ~0.05 + MC tolerance
    assert fwer >= CAMPAIGN_ALPHA_FAMILY - 0.015   # and not vacuously strict either


@pytest.mark.finding("FB4")
def test_campaign_ledger_persists_across_service_instances(tmp_path):
    # Review fix: an in-memory ledger resets every run — restarting must NOT wipe the campaign.
    db = str(tmp_path / "lockbox.db")
    svc1 = OOSLockboxService(db_path=db)
    svc1.ensure_budget("lin_0001")
    svc1.evaluate(_token(1), run_oos_backtest=lambda: OOSOutcome.FAIL, campaign_scope="scope_a")
    svc2 = OOSLockboxService(db_path=db)                # a "new run"
    assert svc2.campaign_tests("scope_a") == 1          # the ledger survived


@pytest.mark.finding("RT2")
async def test_soft_dsr_request_is_refused_until_mon1_exists():
    # Sequencing guard (review fix): the advisory stage-1 may not activate before the MON1
    # power canary exists and proves vacuity — a request fails loudly, never silently ignored.
    from src.backend.ai.research.run import run_research
    with pytest.raises(ValueError, match="sequencing-blocked"):
        await run_research(goal="g", assets=["AAPL"], soft_dsr=True)


@pytest.mark.finding("FB4")
def test_adjusted_t_star_tightens_the_oos_verdict():
    # A per-trade edge with t ≈ 1.9 validates at the single-test bar (1.645) but NOT at the
    # FB4 family bar (3.083) — every campaign test honestly pays the family-wise price.
    tr = [0.008 + 0.028 * ((i % 3) - 1) for i in range(30)]    # mean .008, sd ~.0229 → t ≈ 1.9
    m = {"n_trades": 30, "trade_returns": tr, "total_return": 0.5, "buy_hold_return": 0.1,
         "sharpe_annual": 1.4, "buy_hold_sharpe": 0.5}
    assert _oos_verdict(m)[0] is OOSOutcome.PASS
    assert _oos_verdict(m, t_star=3.083)[0] is not OOSOutcome.PASS
    # the FB4 bar can never be used to LOOSEN below the single-test t*
    assert _oos_verdict(m, t_star=1.0)[0] is OOSOutcome.PASS


@pytest.mark.finding("RT2")
def test_soft_dsr_flag_softens_only_the_dsr_and_only_in_robustness():
    from src.backend.ai.research.gatekeeper import RIGOR_PRESETS, build_default_pipeline
    from src.backend.backtesting.gates.pipeline import GateSeverity
    p = build_default_pipeline(RIGOR_PRESETS["standard"], mode="robustness", soft_dsr=True)
    sev = {type(g).__name__: g.severity for g in p.gates}
    assert sev["DeflatedSharpeGate"] == GateSeverity.SOFT      # advisory stage-1
    assert sev["PerformanceFloorGate"] == GateSeverity.HARD    # everything else untouched
    assert sev["BenchmarkRelativeGate"] == GateSeverity.HARD
    # regime mode ignores soft_dsr entirely (its OOS is off — softening would be a loosening)
    p2 = build_default_pipeline(RIGOR_PRESETS["standard"], mode="regime", soft_dsr=True)
    sev2 = {type(g).__name__: g.severity for g in p2.gates}
    assert sev2["DeflatedSharpeGate"] == GateSeverity.HARD


@pytest.mark.finding("RT2")
def test_soft_dsr_default_off_pipeline_unchanged():
    from src.backend.ai.research.gatekeeper import RIGOR_PRESETS, build_default_pipeline
    from src.backend.backtesting.gates.pipeline import GateSeverity
    p = build_default_pipeline(RIGOR_PRESETS["standard"], mode="robustness")
    sev = {type(g).__name__: g.severity for g in p.gates}
    assert sev["DeflatedSharpeGate"] == GateSeverity.HARD
