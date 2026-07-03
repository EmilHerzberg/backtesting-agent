"""Tests for ATS-1711/1712/1713 — Event-sourced trial registry."""

import json

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.backend.backtesting.registry.event_registry import (
    EventType,
    TrialEventRegistry,
)
from src.backend.backtesting.registry.models import (
    RegistryBase,
    RunEventRow,
)


@pytest.fixture
def session():
    """In-memory SQLite session with all registry tables."""
    engine = create_engine("sqlite:///:memory:")
    RegistryBase.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def registry(session):
    return TrialEventRegistry(session)


def _seed_run(registry: TrialEventRegistry, session: Session, run_id: str = "run_001", **kw):
    """Helper: register a strategy + spec + run."""
    strategy_hash = kw.get("strategy_hash", "a" * 64)
    run_spec_hash = kw.get("run_spec_hash", "b" * 64)

    registry.register_strategy(
        definition_json="{}",
        strategy_hash=strategy_hash,
        template_id="sma",
        template_version=1,
        template_hash="t" * 64,
        security_id="AAPL",
        cost_profile_id="default",
        cost_profile_hash="c" * 64,
        strategy_family="trend",
    )
    registry.register_run_spec(
        run_spec_json="{}",
        run_spec_hash=run_spec_hash,
        strategy_hash=strategy_hash,
        evaluation_role="IS",
        window_start="2010-01-01",
        window_end="2020-12-31",
        data_snapshot_hash="d" * 64,
    )
    return registry.register_run(
        run_id=run_id,
        run_spec_hash=run_spec_hash,
        strategy_hash=strategy_hash,
        lineage_id=kw.get("lineage_id"),
    )


# ── Table creation ───────────────────────────────────────────────────

class TestTableCreation:
    def test_create_tables(self, session):
        """All tables exist after create_all."""
        tables = RegistryBase.metadata.tables.keys()
        assert "strategy_definitions" in tables
        assert "run_specs" in tables
        assert "runs" in tables
        assert "run_events" in tables
        assert "gate_results" in tables
        assert "metrics_index" in tables

    def test_insert_strategy_definition(self, registry, session):
        registry.register_strategy(
            definition_json="{}",
            strategy_hash="x" * 64,
            template_id="test",
            template_version=1,
            template_hash="h" * 64,
            security_id="AAPL",
            cost_profile_id="default",
            cost_profile_hash="c" * 64,
            strategy_family="test",
        )
        session.commit()
        from src.backend.backtesting.registry.models import StrategyDefinitionRow
        row = session.get(StrategyDefinitionRow, "x" * 64)
        assert row is not None
        assert row.template_id == "test"

    def test_duplicate_strategy_ignored(self, registry, session):
        """Inserting the same strategy_hash twice is a no-op."""
        for _ in range(2):
            registry.register_strategy(
                definition_json="{}",
                strategy_hash="x" * 64,
                template_id="test",
                template_version=1,
                template_hash="h" * 64,
                security_id="AAPL",
                cost_profile_id="default",
                cost_profile_hash="c" * 64,
                strategy_family="test",
            )
        session.commit()


# ── Append-only guard ────────────────────────────────────────────────

class TestAppendOnly:
    def test_update_run_event_blocked(self, registry, session):
        run_id = _seed_run(registry, session)
        evt_id = registry.append_event(run_id, EventType.RUN_QUEUED)
        session.commit()

        row = session.get(RunEventRow, evt_id)
        row.event_type = "HACKED"
        with pytest.raises(RuntimeError, match="append-only.*UPDATE"):
            session.flush()

    def test_delete_run_event_blocked(self, registry, session):
        run_id = _seed_run(registry, session)
        evt_id = registry.append_event(run_id, EventType.RUN_QUEUED)
        session.commit()

        row = session.get(RunEventRow, evt_id)
        session.delete(row)
        with pytest.raises(RuntimeError, match="append-only.*DELETE"):
            session.flush()


# ── Event lifecycle ──────────────────────────────────────────────────

class TestEventLifecycle:
    def test_lifecycle_queued_started_completed(self, registry, session):
        run_id = _seed_run(registry, session)
        registry.append_event(run_id, EventType.RUN_QUEUED)
        registry.append_event(run_id, EventType.RUN_STARTED)
        registry.append_event(run_id, EventType.RUN_COMPLETED)
        session.commit()

        status = registry.get_current_status(run_id)
        assert status == EventType.RUN_COMPLETED

    def test_lifecycle_failed_gate(self, registry, session):
        run_id = _seed_run(registry, session)
        registry.append_event(run_id, EventType.RUN_QUEUED)
        registry.append_event(run_id, EventType.RUN_STARTED)
        registry.append_event(run_id, EventType.RUN_COMPLETED)
        registry.append_event(run_id, EventType.GATE_FAILED)
        session.commit()

        status = registry.get_current_status(run_id)
        assert status == EventType.GATE_FAILED

    def test_lifecycle_passed_is(self, registry, session):
        run_id = _seed_run(registry, session)
        registry.append_event(run_id, EventType.RUN_QUEUED)
        registry.append_event(run_id, EventType.RUN_COMPLETED)
        registry.append_event(run_id, EventType.PASSED_IS)
        session.commit()

        assert registry.get_current_status(run_id) == EventType.PASSED_IS

    def test_nonexistent_run_returns_none(self, registry, session):
        assert registry.get_current_status("nonexistent") is None


# ── Trial counts ─────────────────────────────────────────────────────

class TestTrialCounts:
    def test_audit_count_includes_everything(self, registry, session):
        for i in range(5):
            _seed_run(
                registry, session,
                run_id=f"run_{i}",
                run_spec_hash=f"{'b' * 60}{i:04d}",
            )
        session.commit()
        assert registry.audit_trial_count() == 5

    def test_valid_count_excludes_infra_failures(self, registry, session):
        # 3 runs with metrics, 2 without (infra failures)
        for i in range(5):
            rid = _seed_run(
                registry, session,
                run_id=f"run_{i}",
                run_spec_hash=f"{'b' * 60}{i:04d}",
            )
            if i < 3:
                registry.record_metrics(
                    run_id=rid,
                    strategy_hash="a" * 64,
                    evaluation_role="IS",
                    sharpe_perbar=0.02 * (i + 1),
                    valid_research_trial=1,
                )
        session.commit()

        assert registry.audit_trial_count() == 5
        assert registry.valid_research_trial_count() == 3

    def test_lineage_scoped_count(self, registry, session):
        for i in range(3):
            _seed_run(
                registry, session,
                run_id=f"run_{i}",
                run_spec_hash=f"{'b' * 60}{i:04d}",
                lineage_id="lin_A" if i < 2 else "lin_B",
            )
        session.commit()

        assert registry.audit_trial_count("lineage", "lin_A") == 2
        assert registry.audit_trial_count("lineage", "lin_B") == 1

    def test_sharpe_distribution(self, registry, session):
        sharpes = [0.01, 0.03, -0.02, 0.05]
        for i, sr in enumerate(sharpes):
            rid = _seed_run(
                registry, session,
                run_id=f"run_{i}",
                run_spec_hash=f"{'b' * 60}{i:04d}",
            )
            registry.record_metrics(
                run_id=rid,
                strategy_hash="a" * 64,
                evaluation_role="IS",
                sharpe_perbar=sr,
                valid_research_trial=1,
            )
        session.commit()

        dist = registry.sharpe_distribution()
        assert isinstance(dist, np.ndarray)
        assert len(dist) == 4
        np.testing.assert_allclose(sorted(dist), sorted(sharpes))


# ── Idempotency (ATS-1710) ──────────────────────────────────────────

class TestIdempotency:
    def test_run_exists_check(self, registry, session):
        _seed_run(registry, session, run_spec_hash="b" * 64)
        session.commit()

        assert registry.run_exists("b" * 64) is True
        assert registry.run_exists("c" * 64) is False
