"""Persistence models owned by the marketdata module (Modularisation Phase 2/4).

Imports ``Base`` from ``db.base``; db/models.py re-exports these for back-compat.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.backend.db.base import Base, _utc_now


class PriceCacheDB(Base):
    __tablename__ = "price_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    isin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    interval: Mapped[str] = mapped_column(String(10), nullable=False)  # 1min, 5min, 1h, 1d
    open: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # yahoo, ibkr, alphavantage
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    __table_args__ = (
        UniqueConstraint("symbol", "timestamp", "interval", "source", name="uq_price_point"),
        Index("ix_price_symbol_ts", "symbol", "timestamp"),
        Index("ix_price_source", "source"),
    )


class DataProviderDB(Base):
    """Per-user API keys for market-data providers (ATS-1587 / DATA-PROV-S1-T1).

    Mirrors :class:`AIProviderDB` but for data sources (Alpha Vantage,
    Polygon, Finnhub, Twelve Data, Tiingo). One row per (user, provider_type)
    — a user has at most one active key per provider. Resolution order in
    consumers is DB > .env (see key_resolver.py).
    """

    __tablename__ = "data_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)
    api_key: Mapped[str] = mapped_column(String(500), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )

    __table_args__ = (
        UniqueConstraint("user_id", "provider_type", name="uq_data_provider_user_type"),
        Index("ix_data_provider_user", "user_id"),
    )
