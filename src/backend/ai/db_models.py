"""Persistence models owned by the ai / research-orchestration module
(Modularisation Phase 2).

Holds AI providers/models, prompt templates, tool-call audit log, the experiment
budget/queue, research reports/sessions, backtest plans, auto-research goals and
agent rationales. Imports ``Base`` from ``db.base``; db/models.py re-exports these
for back-compat.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.backend.db.base import Base, _utc_now


class PromptTemplateDB(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # NULL = system template
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class AIProviderDB(Base):
    __tablename__ = "ai_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # NULL = system/shared provider
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)  # minimax, openai, anthropic
    api_key: Mapped[str] = mapped_column(String(500), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    __table_args__ = (
        Index("ix_provider_user", "user_id"),
    )


class AIModelDB(Base):
    __tablename__ = "ai_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(Integer, nullable=False)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    context_window: Mapped[int] = mapped_column(Integer, default=0)
    input_price_per_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    output_price_per_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    supports_streaming: Mapped[bool] = mapped_column(Boolean, default=True)
    supports_tools: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_vision: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        Index("ix_aimodel_provider", "provider_id"),
    )


class ToolCallLogDB(Base):
    __tablename__ = "tool_call_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_name: Mapped[str] = mapped_column(String(50), nullable=False)
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    response_size: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    __table_args__ = (
        Index("ix_tool_call_log_tool", "tool_name"),
        Index("ix_tool_call_log_created", "created_at"),
    )


class ExperimentBudgetDB(Base):
    __tablename__ = "experiment_budgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    runs_today: Mapped[int] = mapped_column(Integer, default=0)
    max_runs: Mapped[int] = mapped_column(Integer, default=20)

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_budget_user_date"),
    )


class ExperimentQueueDB(Base):
    __tablename__ = "experiment_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    strategy: Mapped[str] = mapped_column(String(100), nullable=False)
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    hypothesis: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(10), default="medium")
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed, approved, rejected, completed
    result_trial_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_experiment_queue_user", "user_id"),
        Index("ix_experiment_queue_status", "status"),
    )


class ResearchReportDB(Base):
    __tablename__ = "research_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    provider_used: Mapped[str] = mapped_column(String(100), default="")
    model_used: Mapped[str] = mapped_column(String(100), default="")
    executive_summary: Mapped[str] = mapped_column(Text, default="")
    technical_analysis: Mapped[str] = mapped_column(Text, default="")
    ai_reasoning: Mapped[str] = mapped_column(Text, default="")
    recommendation: Mapped[str] = mapped_column(Text, default="")
    indicators_json: Mapped[str] = mapped_column(Text, default="{}")
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    __table_args__ = (
        Index("ix_research_user", "user_id"),
        Index("ix_research_symbol", "symbol"),
    )


class ResearchSessionDB(Base):
    __tablename__ = "research_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # uuid4 hex
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="Untitled Session")
    goal: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|paused|archived
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    __table_args__ = (
        Index("ix_research_session_user", "user_id"),
        Index("ix_research_session_status", "status"),
    )


class ResearchSessionEventDB(Base):
    __tablename__ = "research_session_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # F-015 fix: CASCADE delete so events can't linger as orphans after
    # the parent research session is deleted.
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("research_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)  # prompt|plan|batch|trial|insight|question
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    __table_args__ = (
        Index("ix_session_event_session", "session_id"),
        Index("ix_session_event_created", "created_at"),
    )


class ResearchSessionInsightDB(Base):
    __tablename__ = "research_session_insights"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # F-015 fix: CASCADE delete same as events.
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("research_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    refs_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    __table_args__ = (
        Index("ix_session_insight_session", "session_id"),
    )


class BacktestPlanDB(Base):
    __tablename__ = "backtest_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    # proposed | approved | rejected | expired | edited

    scope_json: Mapped[str] = mapped_column(Text, default="{}")
    cost_estimate_json: Mapped[str] = mapped_column(Text, default="{}")
    rationale_text: Mapped[str] = mapped_column(Text, default="")
    rationale_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    batch_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_plan_user", "user_id"),
        Index("ix_plan_status", "status"),
    )


class AutoResearchGoalDB(Base):
    __tablename__ = "auto_research_goals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    # draft|pending_approval|running|paused|completed|stopped|failed|cancelled

    limits_json: Mapped[str] = mapped_column(Text, default="{}")  # max_runs, max_seconds, max_eur
    stop_conditions_json: Mapped[str] = mapped_column(Text, default="{}")
    criteria_json: Mapped[str] = mapped_column(Text, default="[]")
    target_count: Mapped[int] = mapped_column(Integer, default=1)

    usage_json: Mapped[str] = mapped_column(Text, default="{}")  # runs, seconds, eur
    candidates_json: Mapped[str] = mapped_column(Text, default="[]")
    next_action_json: Mapped[str] = mapped_column(Text, default="{}")
    last_sharpe_history_json: Mapped[str] = mapped_column(Text, default="[]")  # for plateau detection

    # F-034 v2: autonomous batch planning columns
    active_batches_json: Mapped[str] = mapped_column(Text, default="[]")
    plateau_history_json: Mapped[str] = mapped_column(Text, default="[]")
    interpreted_scope_json: Mapped[str] = mapped_column(Text, default="{}")
    cost_preview_json: Mapped[str] = mapped_column(Text, default="{}")
    scope_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_tick_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_goal_user", "user_id"),
        Index("ix_goal_status", "status"),
    )


class AgentRationaleDB(Base):
    __tablename__ = "agent_rationales"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    # plan_symbol_choice | top_rank | cluster_membership | discard_reason
    # | next_step | goal_step | devils_advocate
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(50), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    inputs_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    __table_args__ = (
        Index("ix_rationale_subject", "subject_type", "subject_id"),
        Index("ix_rationale_kind", "kind"),
    )


class NotificationDB(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="info")
    # info|success|warning|error|critical
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    __table_args__ = (
        Index("ix_notif_user", "user_id"),
        Index("ix_notif_read", "read"),
    )
