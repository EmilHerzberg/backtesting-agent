"""Account-settings Phase 1 — change-password + hard delete-account cascade."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.backend.ai import keycrypto
from src.backend.ai.ai_service import create_ai_provider
from src.backend.auth.account_service import count_user_rows, purge_user, user_id_tables
from src.backend.auth.security import verify_password
from src.backend.auth.service import (
    InvalidCredentialsError,
    change_password,
    get_user_by_id,
    register_user,
)
from src.backend.db.init_db import create_tables, drop_tables


@pytest.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    await create_tables(engine)
    sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sf() as session:
        yield session
    await drop_tables(engine)
    await engine.dispose()


class TestChangePassword:
    async def test_wrong_current_rejected(self, db_session):
        user, _ = await register_user(db_session, "a@b.com", "password123")
        with pytest.raises(InvalidCredentialsError):
            await change_password(db_session, user.id, "wrong-pass", "newpassword1")

    async def test_change_updates_hash(self, db_session):
        user, _ = await register_user(db_session, "a@b.com", "password123")
        old = user.password_hash
        await change_password(db_session, user.id, "password123", "newpassword1")
        u = await get_user_by_id(db_session, user.id)
        assert u.password_hash != old
        assert verify_password("newpassword1", u.password_hash)


class TestDeleteCascade:
    async def test_user_id_tables_are_discovered(self, db_session):
        tables = await user_id_tables(db_session)
        # Base-agnostic schema scan (PS-1) — the tables we rely on for the cascade.
        assert "ai_providers" in tables
        assert "research_runs" in tables

    async def test_purge_removes_user_data_and_isolates_others(self, db_session, monkeypatch):
        monkeypatch.setattr(keycrypto, "_fernet", Fernet(Fernet.generate_key()))
        u1, _ = await register_user(db_session, "u1@b.com", "password123")
        u2, _ = await register_user(db_session, "u2@b.com", "password123")
        await create_ai_provider(db_session, name="k1", provider_type="deepseek",
                                 api_key="sk-1111111111", base_url="https://api.deepseek.com", user_id=u1.id)
        await create_ai_provider(db_session, name="k2", provider_type="deepseek",
                                 api_key="sk-2222222222", base_url="https://api.deepseek.com", user_id=u2.id)
        assert await count_user_rows(db_session, u1.id) >= 1

        await purge_user(db_session, u1.id)

        # u1 fully gone (zero rows in any user_id table + no user row)
        assert await count_user_rows(db_session, u1.id) == 0
        assert await get_user_by_id(db_session, u1.id) is None
        # u2 untouched
        assert await count_user_rows(db_session, u2.id) >= 1
        assert await get_user_by_id(db_session, u2.id) is not None
