"""ATS-1744 — Deflated Sharpe Ratio (DSR) computation and gate.

Bailey & Lopez de Prado (2014). Per-period (daily) units throughout.
"""

from __future__ import annotations

import math

import numpy as np
import scipy.stats

from src.backend.backtesting.gates.pipeline import (
    Gate,
    GateContext,
    GateResult,
    GateSeverity,
)


def deflated_sharpe(
    returns: np.ndarray,
    n_trials: int,
    trial_sr_variance: float,
) -> float:
    """Compute the Deflated Sharpe Ratio.

    All inputs and computations are in per-period (e.g. daily) units.
    Do NOT pass annualized Sharpe — the sqrt(n-1) term handles scaling.

    Args:
        returns: Array of per-period strategy returns.
        n_trials: Total valid research trial count from the registry.
        trial_sr_variance: Variance of per-period Sharpe estimates across trials.

    Returns:
        DSR probability in [0, 1]. Accept if >= 0.95 (configurable).
    """
    r = np.asarray(returns, dtype=np.float64)
    n = r.size
    if n < 3 or n_trials < 1 or trial_sr_variance <= 0:
        return 0.0

    sr_hat = r.mean() / r.std(ddof=1)  # per-period Sharpe
    g3 = scipy.stats.skew(r, bias=False)
    g4 = scipy.stats.kurtosis(r, fisher=False, bias=False)  # non-excess

    gamma = 0.5772156649015329  # Euler-Mascheroni
    z = scipy.stats.norm.ppf

    # Expected maximum Sharpe under the null.
    sr0 = math.sqrt(trial_sr_variance) * (
        (1 - gamma) * z(1 - 1.0 / n_trials)
        + gamma * z(1 - 1.0 / (n_trials * math.e))
    )

    num = (sr_hat - sr0) * math.sqrt(n - 1)
    den_sq = 1 - g3 * sr_hat + ((g4 - 1) / 4.0) * sr_hat ** 2
    if den_sq <= 0:
        return 0.0
    den = math.sqrt(den_sq)

    return float(scipy.stats.norm.cdf(num / den))


class DeflatedSharpeGate(Gate):
    """Gate 9: Final IS gate — multiplicity-adjusted acceptance."""

    gate_id = "deflated_sharpe"
    gate_version = 1
    cost_rank = 9
    severity = GateSeverity.HARD

    THRESHOLD = 0.95
    PROVISIONAL_BELOW = 20  # below this many trials, DSR is provisional

    def check(self, ctx: GateContext) -> GateResult:
        n_trials = ctx.n_trials_global
        sr_variance = ctx.trial_sr_variance

        if n_trials < 2:
            return self._pass(
                reason="too few trials for DSR, provisional pass", provisional=True,
            )

        returns = ctx.returns
        if returns is None or len(returns) < 3:
            return self._fail(reason="insufficient return data for DSR")

        if sr_variance <= 0:
            sr_variance = 0.001  # small default to avoid division by zero

        dsr = deflated_sharpe(returns, n_trials, sr_variance)

        is_provisional = n_trials < self.PROVISIONAL_BELOW

        if is_provisional:
            return self._pass(
                value=dsr,
                dsr=dsr,
                n_trials=n_trials,
                sr_variance=sr_variance,
                provisional=True,
                reason=f"DSR={dsr:.3f}, provisional (only {n_trials} trials)",
            )

        if dsr >= self.THRESHOLD:
            return self._pass(
                value=dsr,
                dsr=dsr,
                n_trials=n_trials,
                sr_variance=sr_variance,
            )

        return self._fail(
            value=dsr,
            threshold=self.THRESHOLD,
            reason=f"DSR {dsr:.3f} below threshold {self.THRESHOLD}",
            dsr=dsr,
            n_trials=n_trials,
            sr_variance=sr_variance,
        )
