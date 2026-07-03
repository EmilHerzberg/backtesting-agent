"""ATS-1774/1775 — Validation evaluator.

Runs a frozen strategy on a validation window. Metrics are visible
(returned to caller), but budget is consumed per evaluation.
Validation is NOT final OOS — it's a pre-OOS selection step.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ValidationBudgetExhaustedError(Exception):
    pass


@dataclass
class ValidationBudget:
    """Per-lineage validation budget (ATS-1776)."""

    lineage_id: str
    budget_total: int = 5
    budget_used: int = 0

    def remaining(self) -> int:
        return max(0, self.budget_total - self.budget_used)

    def consume(self) -> None:
        if self.budget_used >= self.budget_total:
            raise ValidationBudgetExhaustedError(
                f"Validation budget exhausted for lineage {self.lineage_id}: "
                f"{self.budget_used}/{self.budget_total}"
            )
        self.budget_used += 1


@dataclass
class ValidationResult:
    """Visible validation metrics — unlike OOS, these are returned."""

    strategy_hash: str
    lineage_id: str
    sharpe_annual: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    n_trades: int = 0
    gate_passed: bool = False
    gate_summary: dict[str, Any] | None = None


class ValidationEvaluator:
    """Run a frozen strategy on the validation window.

    Consumes validation budget. Returns visible metrics + gate results.
    """

    def __init__(self) -> None:
        self._budgets: dict[str, ValidationBudget] = {}

    def ensure_budget(self, lineage_id: str, total: int = 5) -> None:
        if lineage_id not in self._budgets:
            self._budgets[lineage_id] = ValidationBudget(lineage_id=lineage_id, budget_total=total)

    def remaining_budget(self, lineage_id: str) -> int:
        if lineage_id not in self._budgets:
            return 0
        return self._budgets[lineage_id].remaining()

    def evaluate(
        self,
        strategy_hash: str,
        lineage_id: str,
        *,
        run_backtest_fn: Any = None,
        run_gates_fn: Any = None,
    ) -> ValidationResult:
        """Run validation backtest + gates, consuming budget.

        Args:
            strategy_hash: Frozen strategy identity.
            lineage_id: Research lineage for budget tracking.
            run_backtest_fn: Callable() → dict of metrics.
            run_gates_fn: Callable(metrics) → dict with 'passed' key.

        Returns:
            ValidationResult with visible metrics.
        """
        if lineage_id not in self._budgets:
            raise ValidationBudgetExhaustedError(
                f"No validation budget for lineage {lineage_id}"
            )

        budget = self._budgets[lineage_id]
        budget.consume()  # raises if exhausted

        # Run backtest.
        metrics = {}
        if run_backtest_fn:
            metrics = run_backtest_fn()

        # Run gates.
        gate_result = {"passed": False}
        if run_gates_fn and metrics:
            gate_result = run_gates_fn(metrics)

        return ValidationResult(
            strategy_hash=strategy_hash,
            lineage_id=lineage_id,
            sharpe_annual=metrics.get("sharpe_annual", 0.0),
            total_return=metrics.get("total_return", 0.0),
            max_drawdown=metrics.get("max_drawdown", 0.0),
            n_trades=metrics.get("n_trades", 0),
            gate_passed=gate_result.get("passed", False),
            gate_summary=gate_result,
        )
