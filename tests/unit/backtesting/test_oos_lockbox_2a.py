"""Phase 2 / cluster 2A — OOS lockbox discipline (H3, H14, H15, H16, H17).

Review findings (docs/reviews/QUANT-REVIEW-2026-07-03.md):
  H3  — OOS PASS was sign-only (`sharpe_annual > 0 and total_return > 0`): a single lucky trade
        promoted a strategy. D5 replaces it with a real sample + per-trade significance (t ≥ 1.65)
        + positive excess over buy-and-hold; a thin sample is UNEVALUATED, not FAIL.
  R5  — valconf: the D5 trade bar was a FIXED 20, unreachable for slow strategies over the OOS window.
        `_oos_verdict` now scales the bar to the IS tempo × the OOS length (floor OOS_FLOOR), and a
        sub-bar sample that only has per-BAR daily evidence stays UNEVALUATED (per-bar never PASSes, R6).
  H14 — budget was keyed on the per-iteration lineage, so every mutated child got its own fresh
        3-evaluation allowance. It must be rooted on the lineage ROOT (one family allowance).
  H15 — the OOS window end was the hardcoded literal "2025-12-31", silently going stale. It must
        track the live data envelope.
  H16 — a re-evaluated candidate raised AlreadyEvaluatedError, which the caller swallowed, leaving
        it PENDING forever. The stored terminal verdict must be recovered instead.
  H17 — any exception from the OOS backtest became a terminal FAIL (and burned budget). An
        unevaluable candidate must be UNEVALUATED: no budget spent, no terminal row, retryable.

Each test FAILS on the pre-fix code (sign-only bar / per-child budget / stale literal / no
get_result / exception→FAIL) and passes on the fixed path.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.backend.ai.research.loop import (
    VALIDATE_T,
    _env_bounds,
    _oos_verdict,
    _run_oos_lockbox,
)
from src.backend.backtesting.engine.confidence import VALIDATE_CEIL
from src.backend.backtesting.lockbox.service import (
    AlreadyEvaluatedError,
    OOSLockboxService,
    OOSOutcome,
    PromotionToken,
)
from src.backend.backtesting.validation.lineage import LineageTracker
from tests.support.frozen_data import make_ohlcv


# ── H3 / D5: the real OOS pass bar ────────────────────────────────────

def _significant_returns(n: int = 30) -> list[float]:
    """n trades with a clearly positive, low-variance edge → per-trade t well above 1.65."""
    return [0.010 + 0.001 * ((i % 3) - 1) for i in range(n)]  # {0.009, 0.010, 0.011} repeating


@pytest.mark.finding("H3")
def test_thin_sample_is_unevaluated_not_fail():
    m = {"n_trades": VALIDATE_CEIL - 1, "trade_returns": [0.02] * (VALIDATE_CEIL - 1),
         "total_return": 5.0, "buy_hold_return": 0.0}
    # Pre-fix a lucky positive return PASSed; the honest bar says "we don't know".
    assert _oos_verdict(m)[0] is OOSOutcome.UNEVALUATED


@pytest.mark.finding("H3")
def test_significant_edge_beating_buy_hold_passes():
    m = {"n_trades": 30, "trade_returns": _significant_returns(30),
         "total_return": 0.50, "buy_hold_return": 0.10, "sharpe_annual": 1.5}
    assert _oos_verdict(m)[0] is OOSOutcome.PASS


@pytest.mark.finding("H3")
def test_insignificant_sample_fails_even_when_positive():
    # 30 trades, mean ~0 (alternating ±): t ≈ 0 < 1.65 → FAIL despite a non-trivial count.
    tr = [0.05 if i % 2 else -0.05 for i in range(30)]
    m = {"n_trades": 30, "trade_returns": tr, "total_return": 0.30, "buy_hold_return": 0.0,
         "sharpe_annual": 0.1}
    assert _oos_verdict(m)[0] is OOSOutcome.FAIL


@pytest.mark.finding("H3")
def test_significant_but_risk_adjusted_under_buy_hold_fails():
    # D2: strong, significant per-trade edge (the tier VALIDATES) but the strategy's Sharpe trails
    # buy-and-hold's → no RISK-ADJUSTED value added over the passive alternative → FAIL.
    m = {"n_trades": 30, "trade_returns": _significant_returns(30),
         "total_return": 0.10, "buy_hold_return": 0.30,
         "sharpe_annual": 1.2, "buy_hold_sharpe": 2.0}
    assert _oos_verdict(m)[0] is OOSOutcome.FAIL


@pytest.mark.finding("D2")
def test_market_neutral_skill_passes_despite_lower_total_return():
    # D2 / OD7: the old bar folded TOTAL-return-vs-buy-and-hold into the PASS — a beta bar that
    # silently failed genuine market-neutral skill in bull markets. Risk-adjusted: a significant
    # edge with a HIGHER Sharpe than buy-and-hold passes even when its total return is lower.
    m = {"n_trades": 30, "trade_returns": _significant_returns(30),
         "total_return": 0.10, "buy_hold_return": 0.30,
         "sharpe_annual": 1.5, "buy_hold_sharpe": 0.6}
    outcome, _a, extras = _oos_verdict(m)
    assert outcome is OOSOutcome.PASS
    assert extras["excess_sharpe"] > 0
    assert extras["excess_total_return_net"] < 0        # reported honestly, not gating
    assert extras["total_return_floor"] is False


@pytest.mark.finding("D2")
def test_total_return_floor_toggle_gates_when_enabled(monkeypatch):
    # The SEPARATE product floor (off by default): with the toggle on, the same market-neutral
    # edge must ALSO beat a fee-paying buy-and-hold on total return — and here it doesn't.
    import src.backend.ai.research.loop as loop_mod
    monkeypatch.setattr(loop_mod, "OOS_TOTAL_RETURN_FLOOR", True)
    m = {"n_trades": 30, "trade_returns": _significant_returns(30),
         "total_return": 0.10, "buy_hold_return": 0.30,
         "sharpe_annual": 1.5, "buy_hold_sharpe": 0.6}
    outcome, _a, extras = _oos_verdict(m)
    assert outcome is OOSOutcome.FAIL and extras["total_return_floor"] is True


@pytest.mark.finding("D2")
def test_buy_hold_comparison_charges_the_benchmark_its_fees():
    # The user-facing reality check: the buy-and-hold alternative also pays entry+exit commission.
    # Strategy net 0.099 vs B&H gross 0.10: fee-free comparison loses; fee-net comparison wins
    # (0.10 gross → (1.10)(1-0.01)^2-1 ≈ 0.0781 net at 1% commission).
    m = {"n_trades": 30, "trade_returns": _significant_returns(30),
         "total_return": 0.099, "buy_hold_return": 0.10, "commission": 0.01,
         "sharpe_annual": 1.5, "buy_hold_sharpe": 0.6}
    _outcome, _a, extras = _oos_verdict(m)
    assert extras["excess_total_return_net"] > 0


@pytest.mark.finding("D2")
def test_missing_benchmark_is_unevaluated_not_a_degraded_pass():
    # M46 (review fix): benchmark_available=False means "no benchmark computable", not "benchmark
    # with Sharpe 0" — the excess-skill question is unanswerable → honest UNEVALUATED, retryable.
    m = {"n_trades": 30, "trade_returns": _significant_returns(30),
         "total_return": 0.50, "buy_hold_return": 0.0, "buy_hold_sharpe": 0.0,
         "sharpe_annual": 1.5, "benchmark_available": False}
    outcome, _a, extras = _oos_verdict(m)
    assert outcome is OOSOutcome.UNEVALUATED and extras.get("benchmark_unavailable") is True


def test_pass_bar_uses_the_validation_t_star():
    """Guard: the OOS bar reuses the 1.65 validation t*, not a looser selection threshold."""
    assert VALIDATE_T == 1.65


# ── valconf / R5: the OOS trade bar is frequency-scaled to the IS tempo ──

@pytest.mark.finding("R5")
def test_slow_strategy_clears_the_frequency_scaled_oos_bar():
    """A low-frequency strategy: ~8 IS trades over ~4y produces ~12 trades over a ~6y OOS window. The old
    FIXED-20 bar called a genuinely-significant 12-trade edge UNEVALUATED ('not enough trades'); the
    tempo-scaled bar (~12) lets it earn a real PASS."""
    m = {"n_trades": 12, "trade_returns": _significant_returns(12),
         "total_return": 0.40, "buy_hold_return": 0.10, "sharpe_annual": 1.4}
    # unknown tempo → the conservative fixed ceil (20) → 12 trades is too thin → UNEVALUATED
    assert _oos_verdict(m)[0] is OOSOutcome.UNEVALUATED
    # known slow tempo: 8 trades / 1460d projected over 2190d ≈ 12 → bar 12 → the SAME sample PASSES
    assert _oos_verdict(m, train_trades=8, train_days=1460, oos_days=2190)[0] is OOSOutcome.PASS


@pytest.mark.finding("R5")
def test_fast_tempo_scales_the_oos_bar_up_to_the_ceil():
    """A very fast IS tempo projects far ABOVE the ceil, so the bar clamps DOWN to VALIDATE_CEIL (20): a
    6-trade OOS sample is well below 20 → too thin → UNEVALUATED, never a lucky PASS. (The FLOOR-clamp branch
    is covered separately by test_slow_tempo_scales_the_oos_bar_up_to_the_floor.)"""
    m = {"n_trades": 6, "trade_returns": _significant_returns(6),
         "total_return": 0.40, "buy_hold_return": 0.10, "sharpe_annual": 1.4}
    # 500 trades / 1460d projected over 2190d ≈ 749 → clamped DOWN to ceil 20; 6 < 20 → UNEVALUATED
    assert _oos_verdict(m, train_trades=500, train_days=1460, oos_days=2190)[0] is OOSOutcome.UNEVALUATED


@pytest.mark.finding("R5")
def test_slow_tempo_scales_the_oos_bar_up_to_the_floor():
    """A very slow IS tempo projects FAR BELOW OOS_FLOOR (10), and the bar clamps UP to the floor — this is
    the max(OOS_FLOOR, ...) branch the ceil test above never exercises. So a 9-trade OOS sample is still too
    thin (9 < 10 → UNEVALUATED) even though it far exceeds the ~1.5 projected count, while a 10-trade
    significant sample clears the floor (PASS). A regression that dropped OOS_FLOOR (or wired the OOS call to
    REGIME_FLOOR=5) would let those 3–9-trade samples evaluate — this test catches it."""
    slow = dict(train_trades=1, train_days=1460, oos_days=2190)      # projected ≈ 1.5 → bar clamps UP to 10
    thin = {"n_trades": 9, "trade_returns": _significant_returns(9),
            "total_return": 0.40, "buy_hold_return": 0.10, "sharpe_annual": 1.4}
    assert _oos_verdict(thin, **slow)[0] is OOSOutcome.UNEVALUATED    # 9 < OOS_FLOOR=10 → still too thin
    at_floor = {"n_trades": 10, "trade_returns": _significant_returns(10),
                "total_return": 0.40, "buy_hold_return": 0.10, "sharpe_annual": 1.4}
    assert _oos_verdict(at_floor, **slow)[0] is OOSOutcome.PASS       # 10 == OOS_FLOOR → a real verdict


@pytest.mark.finding("R5")
def test_per_bar_evidence_never_manufactures_an_oos_pass():
    """R6 honesty invariant at the OOS boundary: a sub-bar trade count with a long, positive in-market
    daily series is per-BAR evidence. It is autocorrelation-inflated, so it NEVER produces a PASS — the
    verdict stays UNEVALUATED ('we don't know'), not a lucky promotion, no matter how good the daily edge."""
    daily = [0.01, -0.005, 0.008, -0.003] * 75            # 300 bars, positive mean, non-constant
    m = {"n_trades": 3, "trade_returns": [0.02, 0.03, 0.01],
         "total_return": 0.90, "buy_hold_return": 0.10, "sharpe_annual": 1.6,
         "returns": daily, "exposure_time": 1.0}
    # 3 trades is below any scaled bar → per-bar basis (300 in-market bars) → UNEVALUATED, never PASS.
    assert _oos_verdict(m, train_trades=3, train_days=1460, oos_days=2190)[0] is OOSOutcome.UNEVALUATED


@pytest.mark.finding("recheck-nan")
def test_nan_trade_returns_are_unevaluated_not_terminal_fail():
    """H17 / model-honesty at the OOS boundary: NaN trade P&L (degenerate trades — zero-size positions,
    NaN entry price) is NOT real per-trade evidence. Before the isfinite guard it slipped the None-filter
    (np.ptp(nan)!=0 forced basis=per_trade, t=0 → validates=False → a TERMINAL FAIL that burns OOS budget).
    An unevaluable sample must be UNEVALUATED (retryable), never a terminal rejection."""
    m = {"n_trades": 30, "trade_returns": [float("nan")] * 30,
         "total_return": 0.30, "buy_hold_return": 0.05, "sharpe_annual": 1.2}
    assert _oos_verdict(m)[0] is OOSOutcome.UNEVALUATED


# ── H17: exception / thin sample → UNEVALUATED (no budget, no terminal row) ──

def _svc(tmp_path) -> OOSLockboxService:
    svc = OOSLockboxService(db_path=str(tmp_path / "lockbox.db"))
    svc.ensure_budget("root", total=3)
    return svc


@pytest.mark.finding("H17")
def test_backtest_exception_is_unevaluated_not_terminal_fail(tmp_path):
    svc = _svc(tmp_path)
    tok = PromotionToken("auto", "hashX", "root")

    def boom():
        raise RuntimeError("sharpe_annual=9.9 total_return=4.2")  # a message that would leak metrics

    out = svc.evaluate(tok, run_oos_backtest=boom)
    assert out is OOSOutcome.UNEVALUATED
    assert svc.remaining_budget("root") == 3          # no budget burned on an infra failure
    assert svc.get_result("hashX") is None            # no terminal row → retryable


@pytest.mark.finding("H17")
def test_callable_unevaluated_spends_no_budget(tmp_path):
    svc = _svc(tmp_path)
    tok = PromotionToken("auto", "hashX", "root")
    out = svc.evaluate(tok, run_oos_backtest=lambda: OOSOutcome.UNEVALUATED)
    assert out is OOSOutcome.UNEVALUATED
    assert svc.remaining_budget("root") == 3
    assert svc.get_result("hashX") is None


@pytest.mark.finding("H17")
def test_terminal_outcome_consumes_budget_and_persists(tmp_path):
    svc = _svc(tmp_path)
    tok = PromotionToken("auto", "hashP", "root")
    assert svc.evaluate(tok, run_oos_backtest=lambda: OOSOutcome.PASS) is OOSOutcome.PASS
    assert svc.remaining_budget("root") == 2          # exactly one unit consumed
    assert svc.get_result("hashP") is OOSOutcome.PASS


def test_bool_return_is_still_accepted(tmp_path):
    """Back-compat: a bool-returning callable maps True→PASS / False→FAIL."""
    svc = _svc(tmp_path)
    assert svc.evaluate(PromotionToken("a", "h1", "root"), run_oos_backtest=lambda: True) is OOSOutcome.PASS
    assert svc.evaluate(PromotionToken("a", "h2", "root"), run_oos_backtest=lambda: False) is OOSOutcome.FAIL


# ── H16: a terminal verdict is recovered, never re-raised ─────────────

@pytest.mark.finding("H16")
def test_terminal_result_is_final_and_recoverable(tmp_path):
    svc = _svc(tmp_path)
    tok = PromotionToken("auto", "hashT", "root")
    svc.evaluate(tok, run_oos_backtest=lambda: OOSOutcome.FAIL)
    # A second evaluation cannot overwrite a terminal result …
    with pytest.raises(AlreadyEvaluatedError):
        svc.evaluate(tok, run_oos_backtest=lambda: OOSOutcome.PASS)
    # … but the stored verdict is recoverable without re-running.
    assert svc.get_result("hashT") is OOSOutcome.FAIL


# ── Loop-level integration: H14 (root budget), H15 (live window), H16 (recovery) ──

class _FakeExecutor:
    """Captures the spec it is handed and returns a canned metrics dict — no real backtest."""

    def __init__(self, metrics: dict):
        self.metrics = metrics
        self.calls = 0
        self.last_spec: dict | None = None

    def run(self, spec, data, *, warmup_bars=0):
        self.calls += 1
        self.last_spec = spec
        return self.metrics


def _pass_metrics() -> dict:
    return {"n_trades": 30, "trade_returns": _significant_returns(30),
            "total_return": 0.50, "buy_hold_return": 0.10, "sharpe_annual": 1.5}


def _fixture(lineage_id: str):
    data = make_ohlcv(days=60, seed=2)
    data_agent = SimpleNamespace(prepare=lambda **kw: data)
    spec = {"window_end": "2020-06-01", "indicators": [], "strategy_hash": "ignored"}
    state = SimpleNamespace(current_lineage_id=lineage_id, current_asset="AAPL", oos_results=[])
    events: list = []
    return data_agent, spec, state, (lambda evt, payload: events.append((evt, payload))), events


@pytest.mark.finding("H14")
def test_budget_is_shared_across_the_lineage_family():
    tracker = LineageTracker()
    root = tracker.create_root()
    child_a = tracker.create_child(root.lineage_id)
    child_b = tracker.create_child(root.lineage_id)
    lockbox = OOSLockboxService(db_path=":memory:")

    for child, h in ((child_a, "hashA"), (child_b, "hashB")):
        data_agent, spec, state, emit, _ = _fixture(child.lineage_id)
        cand = SimpleNamespace(strategy_hash=h)
        _run_oos_lockbox(lockbox, cand, spec, state, data_agent, _FakeExecutor(_pass_metrics()),
                         emit, tracker)

    # Both evaluations drew from ONE root allowance (3 - 2 = 1) …
    assert lockbox.remaining_budget(root.lineage_id) == 1
    # … and no per-child budget was ever created (pre-fix each child had its own budget of 3).
    assert lockbox.remaining_budget(child_a.lineage_id) == 0
    assert lockbox.remaining_budget(child_b.lineage_id) == 0


@pytest.mark.finding("H15")
def test_oos_window_tracks_the_live_envelope_not_a_stale_literal():
    tracker = LineageTracker()
    root = tracker.create_root()
    lockbox = OOSLockboxService(db_path=":memory:")
    data_agent, spec, state, emit, _ = _fixture(root.lineage_id)
    ex = _FakeExecutor(_pass_metrics())
    _run_oos_lockbox(lockbox, SimpleNamespace(strategy_hash="hashW"), spec, state, data_agent, ex,
                     emit, tracker)

    assert ex.last_spec is not None
    assert ex.last_spec["window_end"] == _env_bounds()[1]     # today's envelope
    assert ex.last_spec["window_end"] != "2025-12-31"         # not the old hardcoded literal
    assert ex.last_spec["window_start"] == "2020-06-01"       # OOS starts at the IS window end


@pytest.mark.finding("H16")
def test_reevaluation_recovers_the_stored_verdict_without_rerunning():
    tracker = LineageTracker()
    root = tracker.create_root()
    lockbox = OOSLockboxService(db_path=":memory:")
    cand = SimpleNamespace(strategy_hash="hashR")
    ex = _FakeExecutor(_pass_metrics())

    data_agent, spec, state, emit, events = _fixture(root.lineage_id)
    _run_oos_lockbox(lockbox, cand, spec, state, data_agent, ex, emit, tracker)
    # Second call for the same candidate must NOT raise and must NOT re-run the backtest.
    _run_oos_lockbox(lockbox, cand, spec, state, data_agent, ex, emit, tracker)

    assert ex.calls == 1                                        # recovery path skipped the backtest
    assert [p["outcome"] for _, p in events] == ["PASS", "PASS"]
    assert lockbox.remaining_budget(root.lineage_id) == 2       # only ONE unit ever consumed


@pytest.mark.finding("recheck-oos-ci")
def test_oos_result_surfaces_the_confidence_tier_and_ci_for_display():
    # valconf §5.6: the OOS tier + Sharpe CI ride alongside the PASS/FAIL verdict for display (symmetric
    # with the regime hold-out), instead of being computed by assess_confidence and thrown away.
    tracker = LineageTracker()
    root = tracker.create_root()
    lockbox = OOSLockboxService(db_path=":memory:")
    data_agent, spec, state, emit, events = _fixture(root.lineage_id)
    metrics = {**_pass_metrics(), "returns": [0.01, -0.006, 0.008, -0.004] * 30, "exposure_time": 1.0}
    _run_oos_lockbox(lockbox, SimpleNamespace(strategy_hash="hashCI"), spec, state, data_agent,
                     _FakeExecutor(metrics), emit, tracker)

    rec = state.oos_results[-1]
    assert rec.outcome == "PASS" and rec.confidence_tier in ("strong", "moderate")
    assert rec.ci_low is not None and rec.ci_low <= rec.ci_high     # CI surfaced, not dropped
    # and it rides on the emitted event too (so a frontend can render it)
    assert events[-1][1]["confidence_tier"] == rec.confidence_tier
    assert events[-1][1]["ci_low"] == rec.ci_low
