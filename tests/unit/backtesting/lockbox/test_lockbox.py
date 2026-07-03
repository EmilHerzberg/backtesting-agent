"""Tests for ATS-1780/1781/1782/1783 — OOS Lockbox."""

import os
import tempfile

import pytest

from src.backend.backtesting.lockbox.service import (
    AlreadyEvaluatedError,
    BudgetExhaustedError,
    OOSLockboxService,
    OOSOutcome,
    PromotionToken,
)


@pytest.fixture
def lockbox(tmp_path):
    db_path = str(tmp_path / "test_lockbox.db")
    svc = OOSLockboxService(db_path=db_path)
    svc.ensure_budget("lin_001", total=3)
    return svc


@pytest.fixture
def token():
    return PromotionToken(
        approver="human_tester",
        strategy_hash="a" * 64,
        lineage_id="lin_001",
    )


class TestOOSLockbox:
    def test_evaluate_returns_pass(self, lockbox, token):
        result = lockbox.evaluate(token, run_oos_backtest=lambda: True)
        assert result == OOSOutcome.PASS

    def test_evaluate_returns_fail(self, lockbox, token):
        result = lockbox.evaluate(token, run_oos_backtest=lambda: False)
        assert result == OOSOutcome.FAIL

    def test_no_metrics_in_response(self, lockbox, token):
        """OOS returns ONLY PASS/FAIL — no Sharpe, drawdown, etc."""
        result = lockbox.evaluate(token, run_oos_backtest=lambda: True)
        assert isinstance(result, OOSOutcome)
        assert result in (OOSOutcome.PASS, OOSOutcome.FAIL)
        # No additional data — just the enum.

    def test_terminal_cannot_overwrite(self, lockbox, token):
        lockbox.evaluate(token, run_oos_backtest=lambda: True)
        with pytest.raises(AlreadyEvaluatedError):
            lockbox.evaluate(token, run_oos_backtest=lambda: False)

    def test_budget_consumed(self, lockbox, token):
        assert lockbox.remaining_budget("lin_001") == 3
        lockbox.evaluate(token, run_oos_backtest=lambda: True)
        assert lockbox.remaining_budget("lin_001") == 2

    def test_budget_exhaustion_blocks(self, lockbox):
        for i in range(3):
            t = PromotionToken("human", f"{'a' * 60}{i:04d}", "lin_001")
            lockbox.evaluate(t, run_oos_backtest=lambda: True)

        t4 = PromotionToken("human", "b" * 64, "lin_001")
        with pytest.raises(BudgetExhaustedError):
            lockbox.evaluate(t4, run_oos_backtest=lambda: True)

    def test_separate_db_file(self, tmp_path):
        db_path = str(tmp_path / "separate_lockbox.db")
        svc = OOSLockboxService(db_path=db_path)
        svc.ensure_budget("lin_x", total=1)
        assert os.path.exists(db_path)

    def test_promotion_token_fields(self):
        t = PromotionToken("alice", "x" * 64, "lin_42")
        assert t.approver == "alice"
        assert t.strategy_hash == "x" * 64
        assert t.lineage_id == "lin_42"
        assert t.token_id.startswith("promo_")

    def test_no_budget_entry_returns_zero(self, lockbox):
        assert lockbox.remaining_budget("nonexistent") == 0

    def test_no_budget_blocks_evaluation(self, lockbox):
        t = PromotionToken("human", "c" * 64, "no_budget_lineage")
        with pytest.raises(BudgetExhaustedError):
            lockbox.evaluate(t, run_oos_backtest=lambda: True)
