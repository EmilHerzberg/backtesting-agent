"""Tests for AggregatedDataProvider DB-key resolution (ATS-1592)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.backend.marketdata.provider import (
    AggregatedDataProvider,
    AlphaVantageProvider,
    create_aggregated_provider,
    create_aggregated_provider_for_user,
)
from src.backend.db.init_db import create_tables, drop_tables
from src.backend.db.models import DataProviderDB


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await create_tables(engine)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await drop_tables(engine)
    await engine.dispose()


def _provider_names(agg: AggregatedDataProvider) -> list[str]:
    return [type(p).__name__ for p in agg._providers]


class TestApiKeysParam:
    def test_passing_av_key_via_api_keys_includes_av_provider(self, monkeypatch):
        # Make sure no env key leaks into the test
        from src.backend.shared.config import settings
        monkeypatch.setattr(settings, "alpha_vantage_api_key", "", raising=False)

        agg = create_aggregated_provider(api_keys={"alpha_vantage": "from-db-key"})
        names = _provider_names(agg)
        assert "AlphaVantageProvider" in names
        # And the constructed AV provider has the supplied key
        av = next(p for p in agg._providers if isinstance(p, AlphaVantageProvider))
        assert av._api_key == "from-db-key"

    def test_no_keys_anywhere_excludes_av(self, monkeypatch):
        from src.backend.shared.config import settings
        monkeypatch.setattr(settings, "alpha_vantage_api_key", "", raising=False)

        agg = create_aggregated_provider()
        assert "AlphaVantageProvider" not in _provider_names(agg)

    def test_db_key_overrides_env(self, monkeypatch):
        from src.backend.shared.config import settings
        monkeypatch.setattr(settings, "alpha_vantage_api_key", "env-key", raising=False)

        agg = create_aggregated_provider(api_keys={"alpha_vantage": "db-key"})
        av = next(p for p in agg._providers if isinstance(p, AlphaVantageProvider))
        assert av._api_key == "db-key"  # DB wins, not env

    def test_env_used_when_api_keys_lacks_entry(self, monkeypatch):
        from src.backend.shared.config import settings
        monkeypatch.setattr(settings, "alpha_vantage_api_key", "env-only-key", raising=False)

        agg = create_aggregated_provider(api_keys={"polygon": "poly-db-key"})
        av = next(p for p in agg._providers if isinstance(p, AlphaVantageProvider))
        assert av._api_key == "env-only-key"  # falls through to env


class TestForUserAsyncWrapper:
    async def test_resolves_db_key_when_present(self, session_factory, monkeypatch):
        from src.backend.shared.config import settings
        monkeypatch.setattr(settings, "alpha_vantage_api_key", "env-key", raising=False)

        async with session_factory() as session:
            session.add(DataProviderDB(
                user_id=1,
                provider_type="alpha_vantage",
                api_key="user-1-db-key",
                is_active=True,
            ))
            await session.commit()
            agg = await create_aggregated_provider_for_user(session, user_id=1)
            av = next(p for p in agg._providers if isinstance(p, AlphaVantageProvider))
            assert av._api_key == "user-1-db-key"

    async def test_falls_back_to_env_without_db_key(self, session_factory, monkeypatch):
        from src.backend.shared.config import settings
        monkeypatch.setattr(settings, "alpha_vantage_api_key", "env-fallback", raising=False)

        async with session_factory() as session:
            agg = await create_aggregated_provider_for_user(session, user_id=99)
            av = next(p for p in agg._providers if isinstance(p, AlphaVantageProvider))
            assert av._api_key == "env-fallback"

    async def test_other_users_keys_are_isolated(self, session_factory, monkeypatch):
        from src.backend.shared.config import settings
        monkeypatch.setattr(settings, "alpha_vantage_api_key", "", raising=False)

        async with session_factory() as session:
            session.add(DataProviderDB(
                user_id=1,
                provider_type="alpha_vantage",
                api_key="user-1-secret",
                is_active=True,
            ))
            await session.commit()
            # User 2 must not see user 1's key
            agg = await create_aggregated_provider_for_user(session, user_id=2)
            assert "AlphaVantageProvider" not in _provider_names(agg)

    async def test_userid_none_only_uses_env(self, session_factory, monkeypatch):
        from src.backend.shared.config import settings
        monkeypatch.setattr(settings, "alpha_vantage_api_key", "env-key", raising=False)

        async with session_factory() as session:
            # Even with a DB key for user 1, user_id=None must skip DB
            session.add(DataProviderDB(
                user_id=1,
                provider_type="alpha_vantage",
                api_key="user-1-db",
                is_active=True,
            ))
            await session.commit()
            agg = await create_aggregated_provider_for_user(session, user_id=None)
            av = next(p for p in agg._providers if isinstance(p, AlphaVantageProvider))
            assert av._api_key == "env-key"
