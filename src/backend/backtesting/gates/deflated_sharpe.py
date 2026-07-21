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


def expected_max_sharpe(n_trials: int, variance: float) -> float:
    """sr0: the expected maximum per-period Sharpe among n_trials zero-skill
    trials with estimator variance ``variance`` (Bailey & López de Prado) —
    exposed for MON2 telemetry and the power canary."""
    if n_trials < 2 or variance <= 0:
        return 0.0
    gamma = 0.5772156649015329
    z = scipy.stats.norm.ppf
    return float(math.sqrt(variance) * (
        (1 - gamma) * z(1 - 1.0 / n_trials)
        + gamma * z(1 - 1.0 / (n_trials * math.e))
    ))


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

    @classmethod
    def null_variance_floor(cls, t_cand: int, exposure: float = 1.0,
                            t_trials: float = 0.0) -> float:
        """The PF4 conservative null-variance floor — the SINGLE implementation
        shared by check() and the MON1 power canary (review fix: the canary had
        re-derived it inline; a later restructure would have silently broken
        its conservativeness argument with no test failing)."""
        t_cand = max(int(t_cand), 1)
        e = exposure if 0.0 < exposure <= 1.0 else 1.0
        inv_null = 1.0 / max(e * t_cand, 1.0)
        if t_trials and t_trials > 1:
            inv_null = max(inv_null, 1.0 / (float(t_trials) - 1.0))
        return cls.V_NULL_INFLATION * inv_null

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
        exposure = float(ctx.metrics.get("exposure_time", 0.0) or 0.0)
        if exposure > 1.0:                    # percent convention → fraction
            exposure = exposure / 100.0
        v_null = self.null_variance_floor(
            len(returns) - 1, exposure=exposure,
            t_trials=float(getattr(ctx, "trial_median_t", 0.0) or 0.0))
        v_null_floored = sr_variance < v_null
        sr_variance_used = max(sr_variance, v_null)

        # B4 (coverage-v2): the expected-max hurdle sizes to the SEARCH (campaign multiplicity
        # when the wire supplies it), while the provisional/auto-pass valves above keep keying on
        # the realized executed-trial count — search breadth is not evidence thinness.
        # Review fix (B5 defense-in-depth): the monotone-stricter guarantee is enforced HERE, at
        # the gate that claims it — a supplied search_size can never sit below the run's own
        # trial count, whatever a (future) caller feeds in.
        _supplied = int(getattr(ctx, "search_size", 0) or 0)
        n_search = max(_supplied, n_trials) if _supplied else n_trials

        dsr = deflated_sharpe(returns, n_search, sr_variance_used)

        # A defaulted (unmeasured) variance can never be a firm PASS/FAIL — it stays provisional.
        is_provisional = n_trials < self.PROVISIONAL_BELOW or sr_variance_defaulted

        # MON2: report which levers actually set the bar (V/T/N), so a too-high hurdle is
        # attributable to its true cause, never silently absorbed. sr0_annual is the plain-
        # language number ("the best of N junk trials looks like THIS much Sharpe here");
        # min_pass_sharpe_annual ≈ the observed Sharpe a candidate needs for a firm PASS.
        _sr0 = expected_max_sharpe(n_search, sr_variance_used)
        v_fields = dict(
            sr_variance=sr_variance_used,
            sr_variance_measured=sr_variance,
            v_null=v_null,
            v_null_floored=v_null_floored,
            sr_variance_defaulted=sr_variance_defaulted,
            sr0_annual=round(_sr0 * math.sqrt(252), 3),
            min_pass_sharpe_annual=round(
                (_sr0 + 1.645 / math.sqrt(max(len(returns) - 1, 1))) * math.sqrt(252), 3),
            binding_lever=("V_floor" if v_null_floored else
                           "V_defaulted" if sr_variance_defaulted else "V_measured"),
        )
        if _supplied:
            v_fields["search_size"] = n_search

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
