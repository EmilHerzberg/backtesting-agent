"""SQLAlchemy models for persisting backtest results."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String, ForeignKey
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.backend.db.models import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ #
# Strategy registry
# ------------------------------------------------------------------ #


class BTStrategy(Base):
    """Registered backtesting strategy."""

    __tablename__ = "bt_strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    class_name: Mapped[str] = mapped_column(String(200), nullable=False)
    parameter_space: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now
    )

    trials: Mapped[list[BTTrial]] = relationship("BTTrial", back_populates="strategy")


# ------------------------------------------------------------------ #
# Trial (single backtest run)
# ------------------------------------------------------------------ #


class BTTrial(Base):
    """Single backtest trial with full metrics."""

    __tablename__ = "bt_trials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("bt_strategies.id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    interval: Mapped[str] = mapped_column(String(10), default="1d")
    train_start: Mapped[str | None] = mapped_column(String(50), nullable=True)
    train_end: Mapped[str | None] = mapped_column(String(50), nullable=True)
    test_start: Mapped[str | None] = mapped_column(String(50), nullable=True)
    test_end: Mapped[str | None] = mapped_column(String(50), nullable=True)
    parameters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cash: Mapped[float] = mapped_column(Float, default=10_000.0)
    commission: Mapped[float] = mapped_column(Float, default=0.001)

    # Core metrics
    total_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    sharpe_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)
    sortino_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    trade_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    calmar_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    buy_hold_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    exposure_time: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Walk-forward metadata
    is_train: Mapped[bool] = mapped_column(Boolean, default=True)
    overfitting_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_validated: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Distinguishes /api/simulation forward-test runs from /api/backtesting trials.
    # Simulation = single user-driven replay; backtest = optimization / WF / batch.
    is_simulation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # F-001 fix: Link trial back to its batch job (nullable for trials from
    # CLI / single-run / pre-V3 data without a batch context)
    batch_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # Run lineage / reproducibility
    engine_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    data_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cost_config_json: Mapped[str | None] = mapped_column(String(500), nullable=True)
    fill_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Extended risk metrics
    max_drawdown_duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_drawdown_recovery: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_holding_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    turnover: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now
    )

    # Relationships
    strategy: Mapped[BTStrategy] = relationship("BTStrategy", back_populates="trials")
    equity_curve: Mapped[BTEquityCurve | None] = relationship(
        "BTEquityCurve", back_populates="trial", uselist=False
    )
    trade_log: Mapped[list[BTTradeLog]] = relationship(
        "BTTradeLog", back_populates="trial"
    )


# ------------------------------------------------------------------ #
# Equity curve (stored as JSON array)
# ------------------------------------------------------------------ #


class BTEquityCurve(Base):
    """Equity curve values for a trial, stored as a JSON array of floats."""

    __tablename__ = "bt_equity_curves"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trial_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("bt_trials.id"), unique=True, nullable=False
    )
    values: Mapped[list | None] = mapped_column(JSON, nullable=True)
    drawdown_values: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Bar timestamps aligned 1:1 with `values`. Populated for simulation
    # trials so the chart can be re-rendered without re-fetching prices.
    # Optional for backtest/WF trials.
    bar_timestamps: Mapped[list | None] = mapped_column(JSON, nullable=True)

    trial: Mapped[BTTrial] = relationship("BTTrial", back_populates="equity_curve")


# ------------------------------------------------------------------ #
# Trade log
# ------------------------------------------------------------------ #


class BTTradeLog(Base):
    """Individual trade record within a trial."""

    __tablename__ = "bt_trade_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trial_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("bt_trials.id"), nullable=False
    )
    entry_time: Mapped[str | None] = mapped_column(String(50), nullable=True)
    exit_time: Mapped[str | None] = mapped_column(String(50), nullable=True)
    side: Mapped[str | None] = mapped_column(String(10), nullable=True)
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    size: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    trial: Mapped[BTTrial] = relationship("BTTrial", back_populates="trade_log")
