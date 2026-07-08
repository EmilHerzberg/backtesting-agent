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
