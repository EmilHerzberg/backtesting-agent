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
    gate_version = 2  # PF4: the conservative null-variance floor changes verdicts
    cost_rank = 9
    severity = GateSeverity.HARD

    THRESHOLD = 0.95
    PROVISIONAL_BELOW = 20  # below this many trials, DSR is provisional
    # PF4 (Track 2, reconciled plan §2a — pre-registered, FROZEN): the measured cross-trial
    # Sharpe dispersion collapses when trials cluster (near-identical strategies → near-identical
    # Sharpes → tiny V → a too-low expected-max hurdle: a loosening in a measurement's costume).
    # Floor it with a conservative NULL variance on the per-period clock: the CLT null variance of
    # a zero-skill per-period Sharpe estimate is ~1/T; measured cross-trial dispersion runs 2-3×
    # that under serial dependence, so the frozen inflation sits at the conservative end.
    # V_used = max(V_measured, V_NULL_INFLATION / (T-1)) — monotone-STRICTER by construction
    # (the mandatory PF4 check sr0(V_used) ≥ sr0(V_measured) holds identically; asserted in tests).
    V_NULL_INFLATION = 3.0

    def check(self, ctx: GateContext) -> GateResult:
        n_trials = ctx.n_trials_global
        sr_variance = ctx.trial_sr_variance
        # M24: track whether the variance is a floored default (unmeasured) explicitly, instead of
        # sniffing the magic 0.001 value downstream. PF4 review fix: a MEASURED 0.0 (perfectly
        # clustered trials) is NOT re-flagged as unmeasured — the null-variance floor below sets
        # the bar and the verdict stays firm; only negative/explicitly-defaulted values default.
        sr_variance_defaulted = bool(ctx.trial_sr_variance_defaulted)
        if sr_variance < 0 or (sr_variance == 0 and sr_variance_defaulted):
            sr_variance = 0.001  # small default to avoid division by zero
            sr_variance_defaulted = True
        sr_variance = max(sr_variance, 0.0)

        if n_trials < 2:
            return self._pass(
                reason="too few trials for DSR, provisional pass",
                provisional=True,
                n_trials=n_trials,
                sr_variance=sr_variance,
                sr_variance_defaulted=True,
            )

        returns = ctx.returns
        if returns is None or len(returns) < 3:
            return self._fail(reason="insufficient return data for DSR")

        # PF4: conservative null-variance floor (see V_NULL_INFLATION above). Applies to the
        # MEASURED variance too, not just the defaulted one — clustered trials are precisely the
        # measured-but-collapsed case the floor exists for. Review-hardened, two clocks:
        # (1) the CANDIDATE's effective clock — a sparse strategy's per-period Sharpe carries
        #     ~exposure×T informative observations, not T (safety doc: 'low-exposure cells are
        #     estimated from n_trades, not T_bars ... biasing lenient');
        # (2) the TRIALS' clock — the dispersion being floored is cross-trial, and its null
        #     scales with the trials' own lengths (~1/T_trial), not the candidate's.
        # The floor takes the max of both nulls (the stricter one governs). Staged scope: this is
        # the per-run floor mechanism; the frozen-grid pre-flight curve (and the replace-vs-floor
        # decision it informs) lands with the PF gates (PF1/PF5), per the reconciled plan.
        t_cand = len(returns) - 1
        exposure = float(ctx.metrics.get("exposure_time", 0.0) or 0.0)
        if exposure > 1.0:                    # percent convention → fraction
            exposure = exposure / 100.0
        n_eff_cand = max((exposure if 0.0 < exposure <= 1.0 else 1.0) * t_cand, 1.0)
        inv_null = 1.0 / n_eff_cand
        t_trials = float(getattr(ctx, "trial_median_t", 0.0) or 0.0)
        if t_trials > 1:
            inv_null = max(inv_null, 1.0 / (t_trials - 1.0))
        v_null = self.V_NULL_INFLATION * inv_null
        v_null_floored = sr_variance < v_null
        sr_variance_used = max(sr_variance, v_null)

        dsr = deflated_sharpe(returns, n_trials, sr_variance_used)

        # A defaulted (unmeasured) variance can never be a firm PASS/FAIL — it stays provisional.
        is_provisional = n_trials < self.PROVISIONAL_BELOW or sr_variance_defaulted

        # MON2 seed: report which variance actually set the bar, so a too-high hurdle is
        # attributable to its true lever (V/T), never silently absorbed.
        v_fields = dict(
            sr_variance=sr_variance_used,
            sr_variance_measured=sr_variance,
            v_null=v_null,
            v_null_floored=v_null_floored,
            sr_variance_defaulted=sr_variance_defaulted,
        )

        if is_provisional:
            why = (
                f"only {n_trials} trials"
                if n_trials < self.PROVISIONAL_BELOW
                else "trial-Sharpe variance unmeasured"
            )
            return self._pass(
                value=dsr,
                dsr=dsr,
                n_trials=n_trials,
                provisional=True,
                reason=f"DSR={dsr:.3f}, provisional ({why})",
                **v_fields,
            )

        if dsr >= self.THRESHOLD:
            return self._pass(value=dsr, dsr=dsr, n_trials=n_trials, **v_fields)

        return self._fail(
            value=dsr,
            threshold=self.THRESHOLD,
            reason=f"DSR {dsr:.3f} below threshold {self.THRESHOLD}",
            dsr=dsr,
            n_trials=n_trials,
            **v_fields,
        )
