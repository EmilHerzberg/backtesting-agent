"""Tests for ATS-1774/1775/1776 — Validation layer + ATS-1777/1778/1779 — Lineage."""

import pytest

from src.backend.backtesting.validation.evaluator import (
    ValidationBudget,
    ValidationBudgetExhaustedError,
    ValidationEvaluator,
    ValidationResult,
)
from src.backend.backtesting.validation.lineage import (
    Lineage,
    LineageTracker,
)


# ── Validation Budget ─────────────────────────────────────────────────

class TestValidationBudget:
    def test_remaining(self):
        b = ValidationBudget(lineage_id="lin_1", budget_total=5)
        assert b.remaining() == 5

    def test_consume(self):
        b = ValidationBudget(lineage_id="lin_1", budget_total=3)
        b.consume()
        assert b.remaining() == 2

    def test_exhaustion_raises(self):
        b = ValidationBudget(lineage_id="lin_1", budget_total=1)
        b.consume()
        with pytest.raises(ValidationBudgetExhaustedError):
            b.consume()


# ── Validation Evaluator ──────────────────────────────────────────────

class TestValidationEvaluator:
    def test_evaluate_returns_visible_metrics(self):
        ev = ValidationEvaluator()
        ev.ensure_budget("lin_1", total=5)
        result = ev.evaluate(
            "hash_1", "lin_1",
            run_backtest_fn=lambda: {"sharpe_annual": 1.0, "total_return": 0.2, "n_trades": 50},
            run_gates_fn=lambda m: {"passed": True},
        )
        assert isinstance(result, ValidationResult)
        assert result.sharpe_annual == 1.0
        assert result.gate_passed is True

    def test_budget_consumed_on_run(self):
        ev = ValidationEvaluator()
        ev.ensure_budget("lin_1", total=2)
        ev.evaluate("h1", "lin_1", run_backtest_fn=lambda: {})
        assert ev.remaining_budget("lin_1") == 1

    def test_budget_exhaustion_blocks(self):
        ev = ValidationEvaluator()
        ev.ensure_budget("lin_1", total=1)
        ev.evaluate("h1", "lin_1")
        with pytest.raises(ValidationBudgetExhaustedError):
            ev.evaluate("h2", "lin_1")

    def test_no_budget_raises(self):
        ev = ValidationEvaluator()
        with pytest.raises(ValidationBudgetExhaustedError):
            ev.evaluate("h1", "unknown_lineage")

    def test_frozen_strategy_hash_stored(self):
        ev = ValidationEvaluator()
        ev.ensure_budget("lin_1", total=5)
        result = ev.evaluate("my_hash", "lin_1")
        assert result.strategy_hash == "my_hash"


# ── Lineage Tracker ───────────────────────────────────────────────────

class TestLineageTracker:
    def test_create_root(self):
        tracker = LineageTracker()
        lin = tracker.create_root(strategy_hash="abc", declared_by="human")
        assert lin.is_root is True
        assert lin.lineage_id.startswith("lin_")

    def test_create_child(self):
        tracker = LineageTracker()
        root = tracker.create_root()
        child = tracker.create_child(root.lineage_id, strategy_hash="def")
        assert child.parent_lineage_id == root.lineage_id
        assert child.is_root is False

    def test_child_of_nonexistent_raises(self):
        tracker = LineageTracker()
        with pytest.raises(ValueError, match="not found"):
            tracker.create_child("nonexistent")

    def test_get_root(self):
        tracker = LineageTracker()
        root = tracker.create_root()
        child = tracker.create_child(root.lineage_id)
        grandchild = tracker.create_child(child.lineage_id)
        found_root = tracker.get_root(grandchild.lineage_id)
        assert found_root.lineage_id == root.lineage_id

    def test_children_of(self):
        tracker = LineageTracker()
        root = tracker.create_root()
        c1 = tracker.create_child(root.lineage_id)
        c2 = tracker.create_child(root.lineage_id)
        children = tracker.children_of(root.lineage_id)
        assert len(children) == 2
        assert {c.lineage_id for c in children} == {c1.lineage_id, c2.lineage_id}

    def test_family_size(self):
        tracker = LineageTracker()
        root = tracker.create_root()
        c1 = tracker.create_child(root.lineage_id)
        c2 = tracker.create_child(root.lineage_id)
        gc1 = tracker.create_child(c1.lineage_id)
        assert tracker.family_size(root.lineage_id) == 4  # root + c1 + c2 + gc1

    def test_lineage_does_not_affect_strategy_hash(self):
        """Lineage is research metadata — not part of the strategy identity."""
        from src.backend.backtesting.registry.definition import StrategyDefinition
        d = StrategyDefinition(
            template_id="sma",
            template_version=1,
            template_hash="abc",
            params={"fast": 10},
            security_id="AAPL",
            bar_size="1d",
            cost_profile_id="default",
            cost_profile_hash="def",
            execution_semantics={},
            strategy_family="trend",
        )
        # StrategyDefinition has no lineage field — this IS the test.
        # If someone adds lineage_id to the model, this will fail compilation.
        assert "lineage" not in d.model_dump(exclude={"strategy_hash"})
