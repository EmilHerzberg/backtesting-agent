"""ATS-1712 — SQLAlchemy models for the event-sourced trial registry.

Tables: strategy_definitions, run_specs, runs, run_events, gate_results.
The run_events table is append-only — no UPDATE or DELETE.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    event,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class RegistryBase(DeclarativeBase):
    """Separate declarative base for the quantbt registry tables.

    Keeps registry tables independent of the main app's Base so they
    can be created/migrated separately.
    """
    pass


class StrategyDefinitionRow(RegistryBase):
    __tablename__ = "strategy_definitions"

    strategy_hash = Column(String(64), primary_key=True)
    definition_json = Column(Text, nullable=False)
    template_id = Column(String(128), nullable=False)
    template_version = Column(Integer, nullable=False)
    template_hash = Column(String(64), nullable=False)
    security_id = Column(String(32), nullable=False)
    cost_profile_id = Column(String(64), nullable=False)
    cost_profile_hash = Column(String(64), nullable=False)
    strategy_family = Column(String(64), nullable=False)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class RunSpecRow(RegistryBase):
    __tablename__ = "run_specs"

    run_spec_hash = Column(String(64), primary_key=True)
    strategy_hash = Column(
        String(64),
        ForeignKey("strategy_definitions.strategy_hash"),
        nullable=False,
    )
    evaluation_role = Column(String(16), nullable=False)
    window_start = Column(String(10), nullable=False)
    window_end = Column(String(10), nullable=False)
    data_snapshot_hash = Column(String(64), nullable=False)
    benchmark_set_id = Column(String(64), nullable=False, default="default")
    benchmark_snapshot_hash = Column(String(64), nullable=False, default="")
    gate_config_hash = Column(String(64), nullable=False, default="")
    pipeline_version = Column(Integer, nullable=False, default=1)
    run_spec_json = Column(Text, nullable=False)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class RunRow(RegistryBase):
    __tablename__ = "runs"

    run_id = Column(String(64), primary_key=True)
    run_spec_hash = Column(
        String(64),
        ForeignKey("run_specs.run_spec_hash"),
        nullable=False,
    )
    strategy_hash = Column(
        String(64),
        ForeignKey("strategy_definitions.strategy_hash"),
        nullable=False,
    )
    lineage_id = Column(String(64), nullable=True)
    hypothesis_id = Column(String(64), nullable=True)
    created_by = Column(String(128), nullable=False, default="system")
    git_sha = Column(String(40), nullable=False, default="unknown")
    git_dirty = Column(Integer, nullable=False, default=0)
    env_hash = Column(String(64), nullable=False, default="")
    seeds_json = Column(Text, nullable=False, default="{}")
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    events = relationship("RunEventRow", back_populates="run", lazy="dynamic")


class RunEventRow(RegistryBase):
    """Append-only lifecycle events for a run."""

    __tablename__ = "run_events"

    event_id = Column(String(64), primary_key=True)
    run_id = Column(
        String(64), ForeignKey("runs.run_id"), nullable=False
    )
    event_type = Column(String(32), nullable=False)
    payload_json = Column(Text, nullable=False, default="{}")
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    run = relationship("RunRow", back_populates="events")

    __table_args__ = (
        Index("idx_run_events_run", "run_id"),
        Index("idx_run_events_type", "event_type"),
    )


class GateResultRow(RegistryBase):
    __tablename__ = "gate_results"

    run_id = Column(
        String(64), ForeignKey("runs.run_id"), nullable=False, primary_key=True
    )
    gate_id = Column(String(64), nullable=False, primary_key=True)
    gate_version = Column(Integer, nullable=False)
    cost_rank = Column(Integer, nullable=False)
    severity = Column(String(8), nullable=False)
    status = Column(String(16), nullable=False)
    value = Column(Float, nullable=True)
    threshold = Column(Float, nullable=True)
    details_json = Column(Text, nullable=True)
    evaluated_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class MetricsIndexRow(RegistryBase):
    __tablename__ = "metrics_index"

    run_id = Column(
        String(64), ForeignKey("runs.run_id"), primary_key=True
    )
    strategy_hash = Column(String(64), nullable=False)
    evaluation_role = Column(String(16), nullable=False)
    sharpe_perbar = Column(Float, nullable=True)
    sharpe_annual = Column(Float, nullable=True)
    return_total = Column(Float, nullable=True)
    max_drawdown = Column(Float, nullable=True)
    n_trades = Column(Integer, nullable=True)
    exposure_time = Column(Float, nullable=True)
    buy_hold_return = Column(Float, nullable=True)
    buy_hold_sharpe = Column(Float, nullable=True)
    excess_return_vs_buy_hold = Column(Float, nullable=True)
    alpha_vs_market = Column(Float, nullable=True)
    beta_vs_market = Column(Float, nullable=True)
    residual_sharpe = Column(Float, nullable=True)
    deflated_sharpe = Column(Float, nullable=True)
    valid_research_trial = Column(Integer, nullable=False, default=1)
    metrics_blob_ref = Column(String(64), nullable=False, default="")
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        Index("idx_metrics_sharpe", "sharpe_perbar"),
        Index("idx_metrics_strategy", "strategy_hash"),
        Index("idx_metrics_role", "evaluation_role"),
    )


# ── Append-only guard for run_events ─────────────────────────────────

def _block_run_event_update(mapper, connection, target):
    raise RuntimeError("run_events is append-only — UPDATE is forbidden")


def _block_run_event_delete(mapper, connection, target):
    raise RuntimeError("run_events is append-only — DELETE is forbidden")


event.listen(RunEventRow, "before_update", _block_run_event_update)
event.listen(RunEventRow, "before_delete", _block_run_event_delete)
