"""Persistence models owned by the backtesting module (Modularisation Phase 2).

Holds the batch/orchestration tables (``batch_jobs``, ``waterfall_reports``).
The per-trial ORM tables (``bt_*``) live in ``backtesting/results/models.py``.
Imports ``Base`` from ``db.base``; db/models.py re-exports these for back-compat.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backtesting_agent.db.base import Base, _utc_now


class BatchJobDB(Base):
    __tablename__ = "batch_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    total_combinations: Mapped[int] = mapped_column(Integer, default=0)
    completed_combinations: Mapped[int] = mapped_column(Integer, default=0)
    failed_combinations: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    __table_args__ = (
        Index("ix_batch_job_user", "user_id"),
    )


class WaterfallReportDB(Base):
    __tablename__ = "waterfall_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_job_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    executive_summary: Mapped[str] = mapped_column(Text, default="")
    headline_kpis_json: Mapped[str] = mapped_column(Text, default="{}")
    top_candidates_json: Mapped[str] = mapped_column(Text, default="[]")
    clusters_json: Mapped[str] = mapped_column(Text, default="[]")
    discards_json: Mapped[str] = mapped_column(Text, default="[]")
    devils_advocate: Mapped[str] = mapped_column(Text, default="")
    next_steps_json: Mapped[str] = mapped_column(Text, default="[]")
    raw_trial_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    __table_args__ = (
        Index("ix_waterfall_batch", "batch_job_id"),
        Index("ix_waterfall_user", "user_id"),
    )
