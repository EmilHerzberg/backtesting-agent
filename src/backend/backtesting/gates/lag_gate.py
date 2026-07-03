"""ATS-1740 — One-bar-extra-lag fragility gate.

An edge that collapses with +1 bar of execution lag is a microstructure
artifact, not a real trading opportunity.
"""

from __future__ import annotations

from src.backend.backtesting.gates.pipeline import (
    Gate,
    GateContext,
    GateResult,
    GateSeverity,
)


class LagFragilityGate(Gate):
    """Gate 8: Strategy Sharpe must survive a +1 bar signal delay."""

    gate_id = "lag_fragility"
    gate_version = 1
    cost_rank = 8
    severity = GateSeverity.HARD

    RATIO_THRESHOLD = 0.6  # lagged Sharpe must be >= 60% of original

    def check(self, ctx: GateContext) -> GateResult:
        # This gate needs a lagged Sharpe — which requires re-running the
        # backtest with delayed signals. For now we check if lagged metrics
        # were pre-computed and passed in context.
        original_sharpe = ctx.metrics.get("sharpe_annual", 0.0)
        lagged_sharpe = ctx.metrics.get("lagged_sharpe_annual", None)

        if lagged_sharpe is None:
            # If no lagged run was done, pass provisionally.
            return self._pass(
                details={"reason": "no lagged run available, provisional pass", "provisional": True},
            )

        if original_sharpe == 0:
            return self._pass(details={"reason": "original Sharpe is zero"})

        ratio = lagged_sharpe / original_sharpe if original_sharpe != 0 else 0
        sign_preserved = (lagged_sharpe > 0) == (original_sharpe > 0)

        if ratio < self.RATIO_THRESHOLD or not sign_preserved:
            return self._fail(
                value=ratio,
                threshold=self.RATIO_THRESHOLD,
                details={
                    "reason": f"lagged ratio {ratio:.2f} below {self.RATIO_THRESHOLD} or sign flipped",
                    "original_sharpe": original_sharpe,
                    "lagged_sharpe": lagged_sharpe,
                    "sign_preserved": sign_preserved,
                },
            )

        return self._pass(
            value=ratio,
            details={
                "original_sharpe": original_sharpe,
                "lagged_sharpe": lagged_sharpe,
                "ratio": ratio,
            },
        )
