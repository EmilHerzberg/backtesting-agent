"""Phase 0 — engine validation-confidence primitives (REGIME-VALIDATION-CONFIDENCE-SPEC v3)."""
from __future__ import annotations

import numpy as np
import pytest

from src.backend.backtesting.engine.confidence import (
    STRONG_FLOOR,
    block_bootstrap_sharpe_ci,
    confidence_tier,
    per_bar_sharpe_and_t,
    scaled_min_trades,
    student_t_critical,
)


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
