"""Validation-confidence primitives — REGIME-VALIDATION-CONFIDENCE-SPEC (v3).

Engine-layer, PURE, DETERMINISTIC statistics consumed by the walk-forward validator, the regime/OOS
hold-out, and single backtests. This module imports only the engine metrics helper — never ``ai/research``
(leaf capability; the import-linter boundary must stay intact).

Design principle (spec §0/R6): these produce **evidence** — a confidence *tier* + a Sharpe confidence
interval. A **validating** verdict (``regime_validated`` / OOS ``PASS``) requires REAL TRADES clearing the
per-trade significance bar. **Per-bar (daily-return) evidence never validates** (it caps at tier ``weak``),
because a held position's daily returns are serially correlated (one bet observed many times), so a naive
per-bar t is inflated ~√(bars/trades) and must not manufacture certainty.

Constants are the approved §7 defaults (2026-07-08) — kept here so they are auditable/tunable in one place.
"""
from __future__ import annotations

import math

import numpy as np

from src.backend.backtesting.engine.metrics import annualized_sharpe

# ── Tunable constants (spec §7) ──────────────────────────────────────────
VALIDATE_T = 1.65        # one-sided ~95% base significance bar (matches loop.VALIDATE_T)
STRONG_T = 2.5           # extra bar for the `strong` tier (effective strong bar = max(STRONG_T, t_star))
REGIME_FLOOR = 5         # min trades to ATTEMPT a per-trade validation on a (short) regime hold-out
OOS_FLOOR = 10           # ... on the (longer) OOS window
VALIDATE_CEIL = 20       # ceil of the frequency-scaled bar (== legacy VALIDATE_MIN_TRADES)
STRONG_FLOOR = 12        # `strong` needs a real sample — decoupled from the scaled floor (D2)
MIN_BARS = 20            # min in-market bars to compute a per-bar evidence signal / a CI
CI_LEVEL = 0.90          # bootstrap CI level (D3)
CI_RESAMPLES = 1000      # bootstrap resamples (D3)

# Tier vocabulary, ordered strongest → weakest (a total function, §5.4).
TIER_STRONG = "strong"
TIER_MODERATE = "moderate"
TIER_WEAK = "weak"
TIER_INCONCLUSIVE = "inconclusive"
TIER_FAILED = "failed"


def scaled_min_trades(
    train_trades: int, train_days: float, holdout_days: float,
    *, floor: int = REGIME_FLOOR, ceil: int = VALIDATE_CEIL,
) -> int:
    """R1 — the frequency- & window-scaled trade bar for a *validation* verdict.

    Estimate the strategy's trade rate from the TRAIN window, project it onto the hold-out length, and clamp
    to ``[floor, ceil]``. If the tempo can't be estimated (no train data / no trades), demand the full
    ``ceil`` bar rather than guessing low.
    """
    if train_days <= 0 or train_trades <= 0:
        return int(ceil)
    rate = train_trades / train_days
    expected = rate * max(holdout_days, 0.0)
    return int(min(ceil, max(floor, round(expected))))


def student_t_critical(df: int, level: float = 0.95) -> float:
    """One-sided Student-t critical value at ``df`` degrees of freedom (D1 — df-aware).

    Tightens the bar for small samples (df=5 → ~2.02 vs the normal 1.64) and converges to the normal
    quantile as df → ∞. ``df < 1`` → ``inf`` (never significant).
    """
    if df < 1:
        return float("inf")
    from scipy.stats import t as _t
    return float(_t.ppf(level, df))


def per_bar_sharpe_and_t(daily_returns, ppy: float) -> tuple[float, float, int]:
    """R2/D5 — per-bar (daily-return) evidence. Returns ``(annualized_sharpe, naive_t, n)``.

    The ``t`` here is a NAIVE ``mean/std·√N`` and is **display-only** (D5): per-bar evidence never gates a
    validating status (§0/R6), so its autocorrelation inflation cannot manufacture certainty. A HAC/
    Newey-West standard error is a documented fast-follow if per-bar is ever allowed to influence more.
    """
    r = np.asarray(daily_returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    n = int(r.size)
    # A constant series has no variance → no meaningful Sharpe/t. Detect it by peak-to-peak, not std:
    # np.std of identical floats returns a ~1e-18 mean-rounding residual, not exactly 0.
    if n < 2 or float(np.ptp(r)) == 0.0:
        return 0.0, 0.0, n
    sharpe = annualized_sharpe(r, ppy)
    sd = float(r.std(ddof=1))
    t = float(r.mean() / sd * math.sqrt(n)) if sd > 0 else 0.0
    return sharpe, t, n


def block_bootstrap_sharpe_ci(
    daily_returns, ppy: float, *,
    level: float = CI_LEVEL, n_resamples: int = CI_RESAMPLES, seed: int = 0,
    block_len: int | None = None,
) -> tuple[float, float]:
    """R4/F3/D3 — a MOVING-BLOCK bootstrap CI on the annualized Sharpe.

    Block (not iid) resampling preserves the serial correlation of the return series, so the interval comes
    out honestly wide on autocorrelated / thin data (an iid bootstrap would be spuriously narrow — the
    anti-honest failure the spec review caught). Deterministic given ``seed``. Returns ``(nan, nan)`` when
    the series is too short / degenerate for a meaningful interval.
    """
    r = np.asarray(daily_returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    N = int(r.size)
    # Too short or a constant series (ptp==0 is exact; std has a ~1e-18 float residual) → no meaningful CI.
    if N < MIN_BARS or float(np.ptp(r)) == 0.0:
        return (float("nan"), float("nan"))
    if block_len is None:
        block_len = max(2, int(round(math.sqrt(N))))
    block_len = int(min(block_len, N))
    rng = np.random.default_rng(seed)
    n_blocks = int(math.ceil(N / block_len))
    starts_max = N - block_len
    sharpes = np.empty(n_resamples, dtype=np.float64)
    for i in range(n_resamples):
        starts = rng.integers(0, starts_max + 1, size=n_blocks)
        sample = np.concatenate([r[s:s + block_len] for s in starts])[:N]
        sharpes[i] = annualized_sharpe(sample, ppy)
    alpha = (1.0 - level) / 2.0
    return (float(np.quantile(sharpes, alpha)), float(np.quantile(sharpes, 1.0 - alpha)))


def confidence_tier(
    *, basis: str, t: float, observed_sharpe: float, n_trades: int, t_star: float, ci_low: float,
) -> str:
    """R3/R13 — the total, ordered tier function (§5.4). First matching rule wins; a default guarantees
    totality. ``basis`` is ``"per_trade"`` / ``"per_bar"`` / ``"none"``.

    Honesty invariants: only a ``per_trade`` basis can reach ``moderate``/``strong`` (the tiers the
    consumers map to a validating status); a ``per_bar`` basis caps at ``weak``; ``strong`` clears the
    Šidák-reuse-corrected bar too (``max(STRONG_T, t_star)``, R9 monotonicity) and needs ``STRONG_FLOOR``
    trades and a positive CI lower bound.
    """
    ci_ok = ci_low is not None and math.isfinite(ci_low) and ci_low > 0.0

    if basis == "per_trade":
        # 1 — a real test ran and the edge is negative / collapsed.
        if observed_sharpe < 0.0 or t <= -t_star:
            return TIER_FAILED
        # 2 — strong: high, reuse-corrected, well-sampled, CI clears zero.
        bar_strong = max(STRONG_T, t_star)
        if n_trades >= STRONG_FLOOR and t >= bar_strong and ci_ok:
            return TIER_STRONG
        # 3 — moderate: clears the df-aware significance bar (tightened for small samples).
        bar_mod = max(t_star, student_t_critical(max(1, n_trades - 1), 0.95))
        if t >= bar_mod and observed_sharpe > 0.0:
            return TIER_MODERATE
        # 4 — ran but not significant.
        return TIER_WEAK

    if basis == "per_bar":
        # Evidence only — never validates. Positive daily edge → weak; else inconclusive.
        return TIER_WEAK if observed_sharpe > 0.0 else TIER_INCONCLUSIVE

    # 5 — no usable statistic (too thin / degenerate).
    return TIER_INCONCLUSIVE
