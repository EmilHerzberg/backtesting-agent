"""Phase 0 — engine validation-confidence primitives (REGIME-VALIDATION-CONFIDENCE-SPEC v3)."""
from __future__ import annotations

import numpy as np
import pytest

from src.backend.backtesting.engine.confidence import (
    STRONG_FLOOR,
    assess_confidence,
    block_bootstrap_sharpe_ci,
    confidence_tier,
    per_bar_sharpe_and_t,
    scaled_min_trades,
    student_t_critical,
)
from src.backend.backtesting.engine.metrics import annualized_sharpe


# ── R1: scaled_min_trades ────────────────────────────────────────────────
def test_scaled_min_trades_untappable_tempo_demands_full_bar():
    assert scaled_min_trades(0, 365, 120) == 20     # no trades → can't estimate → ceil
    assert scaled_min_trades(30, 0, 120) == 20      # no train days → ceil


def test_scaled_min_trades_high_frequency_hits_ceil():
    # ~200 trades/yr → ~66 expected in a 120d hold-out → clamped to ceil 20.
    assert scaled_min_trades(200, 365, 120) == 20


def test_scaled_min_trades_low_frequency_hits_floor():
    # ~6 trades/yr → ~2 expected in 120d → clamped UP to the floor 5 (not a fixed 20).
    assert scaled_min_trades(6, 365, 120) == 5


def test_scaled_min_trades_mid_frequency_scales_between():
    # ~15 trades/yr over 2y train → ~15 expected in a 365d hold-out → 15 (within [5, 20]).
    assert scaled_min_trades(30, 730, 365) == 15


# ── D1: student_t_critical ───────────────────────────────────────────────
def test_student_t_is_tighter_for_small_samples_and_converges():
    assert student_t_critical(4, 0.95) == pytest.approx(2.132, abs=1e-2)    # df=4 ≫ normal 1.645
    assert student_t_critical(1000, 0.95) == pytest.approx(1.646, abs=1e-2)  # → normal
    assert student_t_critical(0) == float("inf")


# ── R2/D5: per_bar_sharpe_and_t ──────────────────────────────────────────
def test_per_bar_edge_cases():
    assert per_bar_sharpe_and_t([0.01], 252.0) == (0.0, 0.0, 1)          # <2 bars
    s, t, n = per_bar_sharpe_and_t([0.01] * 30, 252.0)                    # zero variance
    assert t == 0.0 and n == 30
    s, t, n = per_bar_sharpe_and_t([0.003 + 0.001 * ((i % 3) - 1) for i in range(40)], 252.0)
    assert s > 0 and t > 0 and n == 40


# ── R4/F3/D3: block_bootstrap_sharpe_ci ──────────────────────────────────
def test_bootstrap_is_seed_deterministic():
    r = list(np.random.default_rng(1).normal(0.001, 0.01, 60))
    a = block_bootstrap_sharpe_ci(r, 252.0, seed=7)
    b = block_bootstrap_sharpe_ci(r, 252.0, seed=7)
    assert a == b and np.isfinite(a[0]) and a[0] <= a[1]


def test_bootstrap_degenerate_returns_nan():
    assert all(np.isnan(x) for x in block_bootstrap_sharpe_ci([0.01] * 10, 252.0, seed=1))   # < MIN_BARS
    assert all(np.isnan(x) for x in block_bootstrap_sharpe_ci([0.01] * 40, 252.0, seed=1))   # std==0


def test_bootstrap_wide_on_noise_positive_lower_bound_on_strong_signal():
    noise = list(np.random.default_rng(2).normal(0.0, 0.01, 80))          # ~zero edge
    lo, hi = block_bootstrap_sharpe_ci(noise, 252.0, seed=3)
    assert lo < hi and (hi - lo) > 0.5                                     # honestly WIDE band
    strong = list(np.random.default_rng(4).normal(0.002, 0.004, 80))      # strong daily edge
    slo, shi = block_bootstrap_sharpe_ci(strong, 252.0, seed=5)
    assert slo > 0                                                         # CI clears zero


# ── R3/R13/R6: confidence_tier (the total ordered function) ──────────────
def test_tier_per_trade_failed_on_negative_or_collapsed():
    assert confidence_tier(basis="per_trade", t=3.0, observed_sharpe=-0.2, n_trades=30, t_star=1.65, ci_low=0.5) == "failed"
    assert confidence_tier(basis="per_trade", t=-2.0, observed_sharpe=0.1, n_trades=30, t_star=1.65, ci_low=0.1) == "failed"


def test_tier_per_trade_strong_moderate_weak():
    assert confidence_tier(basis="per_trade", t=3.0, observed_sharpe=1.2, n_trades=STRONG_FLOOR + 3, t_star=1.65, ci_low=0.4) == "strong"
    # moderate: clears the df-aware bar + positive Sharpe, but CI doesn't clear 0 (so not strong)
    assert confidence_tier(basis="per_trade", t=2.0, observed_sharpe=0.8, n_trades=15, t_star=1.65, ci_low=-0.1) == "moderate"
    # ran but not significant
    assert confidence_tier(basis="per_trade", t=1.0, observed_sharpe=0.5, n_trades=15, t_star=1.65, ci_low=0.1) == "weak"


def test_tier_small_sample_t_is_tightened_by_student_t():
    # t=2.0 on 5 trades (df=4, bar≈2.13) is NOT moderate — a normal-only bar (1.65) would have passed it.
    assert confidence_tier(basis="per_trade", t=2.0, observed_sharpe=0.5, n_trades=5, t_star=1.65, ci_low=0.1) == "weak"


def test_tier_per_bar_never_validates_even_with_huge_t():
    # THE honesty invariant: per-bar caps at `weak` regardless of how large its (inflated) t is.
    assert confidence_tier(basis="per_bar", t=99.0, observed_sharpe=2.0, n_trades=0, t_star=1.65, ci_low=1.0) == "weak"
    assert confidence_tier(basis="per_bar", t=99.0, observed_sharpe=-0.1, n_trades=0, t_star=1.65, ci_low=0.0) == "inconclusive"
    assert confidence_tier(basis="none", t=0.0, observed_sharpe=0.0, n_trades=0, t_star=1.65, ci_low=float("nan")) == "inconclusive"


# ── D8 (Phase-Z): the CI rides on the REALIZED full-period series, not an in-market mask ──
@pytest.mark.finding("D8")
def test_ci_is_computed_on_the_full_period_series_not_masked():
    """The block-bootstrap CI is built from the full daily series exactly as passed (flat cash bars included) —
    the same series the reported Sharpe uses — so it brackets that Sharpe. It is NOT masked to in-market bars:
    a correct mask needs a per-bar position series the engine leaf never receives, and masking would decouple
    the CI from the reported full-period Sharpe (Phase-Z resolution, spec §7 D8)."""
    rng = np.random.default_rng(11)
    in_market = list(rng.normal(0.002, 0.01, 60))       # 60 real in-market bars
    daily = in_market + [0.0] * 60                       # + 60 flat cash bars → exposure ≈ 0.5

    a = assess_confidence(
        train_trades=0, train_days=0, holdout_days=0, test_trades=0,
        trade_returns=[], daily_returns=daily, exposure_time=0.5,
        observed_sharpe=0.0, ppy=252.0, t_star=1.65, floor=5, seed=0,
    )
    full = block_bootstrap_sharpe_ci(daily, 252.0, seed=0)
    assert (a.ci_low, a.ci_high) == (round(full[0], 4), round(full[1], 4))     # CI on the FULL series …
    masked = block_bootstrap_sharpe_ci(in_market, 252.0, seed=0)               # … a masked subset would differ
    assert (a.ci_low, a.ci_high) != (round(masked[0], 4), round(masked[1], 4))
    # and the CI brackets the full-period Sharpe (the whole point of not masking)
    point = float(annualized_sharpe(np.asarray(daily, dtype=float), 252.0))
    assert a.ci_low <= point <= a.ci_high


@pytest.mark.finding("recheck-nan")
def test_all_nan_trade_returns_are_unevaluable_not_a_per_trade_test():
    """Non-finite trade P&L (NaN/inf) must NOT slip into the per-trade path. np.ptp([nan,nan]) is nan and
    nan != 0.0 is True, so before the isfinite filter an all-NaN sample would enter per_trade with t=0 →
    validates=False → (at the OOS layer) a TERMINAL FAIL. An all-NaN sample is UNEVALUABLE: the basis must
    fall to per_bar/none, never per_trade, so the honesty invariant 'no real evidence ⇒ never a FAIL' holds."""
    a = assess_confidence(
        train_trades=0, train_days=0, holdout_days=0, test_trades=30,
        trade_returns=[float("nan")] * 30, daily_returns=[], exposure_time=0.0,
        observed_sharpe=0.5, ppy=252.0, t_star=1.65, floor=5, seed=0,
    )
    assert a.basis != "per_trade"
    assert not a.validates


@pytest.mark.finding("STATS-1")
def test_partial_nan_trades_do_not_earn_a_false_validation_via_inflated_df():
    """Recheck regression: NaN P&L in SOME trades must not inflate the effective sample. 10 reported, 7 NaN →
    3 usable. The pre-fix code gated on the reported count and passed n_trades=10 to the tier, so the Student-t
    df was 9 (bar≈1.83) instead of 2 (bar≈2.92) — a t≈2.6 on the 3 usable trades earned a FALSE MODERATE /
    regime_validated. The fix gates on (and reports) the USABLE count, so 3 usable trades stay non-validating."""
    tr = [0.02, 0.01, 0.005] + [float("nan")] * 7            # 3 usable, t≈2.6 (clears the WRONG df=9 bar)
    a = assess_confidence(
        train_trades=10, train_days=1000, holdout_days=800,   # → min_req=8; usable 3 < 8
        test_trades=10, trade_returns=tr, daily_returns=[], exposure_time=0.0,
        observed_sharpe=1.2, ppy=252.0, t_star=1.65, floor=5, seed=0,
    )
    assert a.n_trades == 3                                    # the USABLE count is reported, not the inflated 10
    assert a.basis != "per_trade" and not a.validates         # too few real trades → no significance test, no validation


# ── valconf in-market masking: the edge WHILE DEPLOYED (additive, display-only) ──
@pytest.mark.finding("valconf-inmarket")
def test_in_market_sharpe_and_ci_computed_when_a_series_is_supplied():
    """When the in-market daily series is supplied, assess_confidence reports the edge WHILE DEPLOYED
    (Sharpe + CI on those days only), on the same √ppy scale as observed_sharpe. It is additive — the
    verdict fields (tier/validates/ci) are unchanged."""
    rng = np.random.default_rng(3)
    daily_full = list(rng.normal(0.0005, 0.008, 120))        # full period (diluted by cash days)
    in_market = list(rng.normal(0.003, 0.008, 40))           # a stronger edge on the ~40 deployed days
    a = assess_confidence(
        train_trades=0, train_days=0, holdout_days=0, test_trades=0,
        trade_returns=[], daily_returns=daily_full, exposure_time=0.33,
        observed_sharpe=0.4, ppy=252.0, t_star=1.65, floor=5, seed=7,
        in_market_returns=in_market,
    )
    assert a.in_market_sharpe is not None
    assert a.in_market_ci_low is not None and a.in_market_ci_low <= a.in_market_ci_high
    # the CI is the block-bootstrap of the in-market series at the same seed (reproducible per strategy)
    lo, hi = block_bootstrap_sharpe_ci(in_market, 252.0, seed=7)
    assert (a.in_market_ci_low, a.in_market_ci_high) == (round(lo, 4), round(hi, 4))
    assert a.in_market_sharpe == round(float(annualized_sharpe(np.asarray(in_market), 252.0)), 4)


@pytest.mark.finding("valconf-inmarket")
def test_in_market_fields_none_without_a_series_or_when_too_thin():
    base = dict(
        train_trades=0, train_days=0, holdout_days=0, test_trades=0, trade_returns=[],
        daily_returns=[0.01 + 0.001 * (i % 3) for i in range(30)], exposure_time=1.0,
        observed_sharpe=0.5, ppy=252.0, t_star=1.65, floor=5, seed=0,
    )
    a = assess_confidence(**base)                                          # no series → all None
    assert (a.in_market_sharpe, a.in_market_ci_low, a.in_market_ci_high) == (None, None, None)
    b = assess_confidence(**base, in_market_returns=[0.01, 0.02, 0.015])   # < MIN_BARS → None
    assert b.in_market_sharpe is None and b.in_market_ci_low is None and b.in_market_ci_high is None
