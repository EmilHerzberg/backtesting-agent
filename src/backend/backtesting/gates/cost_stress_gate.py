"""ATS-1742 — 2x cost stress gate.

Re-evaluate metrics under doubled costs. Strategy must still be profitable.
"""

from __future__ import annotations

from src.backend.backtesting.gates.pipeline import (
    Gate,
    GateContext,
    GateResult,
    GateSeverity,
)


class CostStressGate(Gate):
    """Gate 7: Strategy must survive doubled transaction costs."""

    gate_id = "cost_stress"
    gate_version = 1
    cost_rank = 7
    severity = GateSeverity.HARD

    COST_MULTIPLIER = 2.0
    MIN_STRESSED_SHARPE = 0.5
    MIN_STRESSED_RETURN = 0.0

    def check(self, ctx: GateContext) -> GateResult:
        # Approximate stressed metrics from trade count and original metrics.
        # Full re-run is ideal but expensive; this is the fast approximation.
        original_return = ctx.metrics.get("total_return", 0.0)
        original_sharpe = ctx.metrics.get("sharpe_annual", 0.0)
        n_trades = ctx.metrics.get("n_trades", 0)
        commission = ctx.metrics.get("commission", 0.001)

        # Each trade incurs commission twice (entry + exit).
        # Additional cost = n_trades * 2 * commission * multiplier_delta
        additional_cost = n_trades * 2 * commission * (self.COST_MULTIPLIER - 1)
        stressed_return = original_return - additional_cost

        # Rough Sharpe adjustment: proportional to return reduction.
        if abs(original_return) > 1e-9:
            ratio = stressed_return / original_return
            stressed_sharpe = original_sharpe * max(ratio, 0)
        else:
            stressed_sharpe = 0.0

        if stressed_return <= self.MIN_STRESSED_RETURN:
            return self._fail(
                value=stressed_return,
                threshold=self.MIN_STRESSED_RETURN,
                details={
                    "reason": f"stressed return {stressed_return:.2%} not positive",
                    "stressed_sharpe": stressed_sharpe,
                    "additional_cost": additional_cost,
                    "cost_multiplier": self.COST_MULTIPLIER,
                },
            )

        if stressed_sharpe < self.MIN_STRESSED_SHARPE:
            return self._fail(
                value=stressed_sharpe,
                threshold=self.MIN_STRESSED_SHARPE,
                details={
                    "reason": f"stressed Sharpe {stressed_sharpe:.2f} below floor",
                    "stressed_return": stressed_return,
                    "cost_multiplier": self.COST_MULTIPLIER,
                },
            )

        return self._pass(
            value=stressed_return,
            details={
                "stressed_return": stressed_return,
                "stressed_sharpe": stressed_sharpe,
                "additional_cost": additional_cost,
                "cost_multiplier": self.COST_MULTIPLIER,
            },
        )
