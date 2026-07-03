import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.backend.auth.security import decode_access_token
from src.backend.auth.service import (
    InvalidCredentialsError,
    InvalidTokenError,
    UserAlreadyExistsError,
    UserNotVerifiedError,
    get_user_by_id,
    login_user,
    register_user,
    verify_user,
)
from src.backend.db.init_db import create_tables, drop_tables


@pytest.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    await create_tables(engine)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await drop_tables(engine)
    await engine.dispose()


class TestRegister:
    async def test_register_success(self, db_session):
        user, token = await register_user(db_session, "test@example.com", "password123")
        assert user.email == "test@example.com"
        assert user.is_verified is False
        assert token is not None

    async def test_duplicate_email_raises(self, db_session):
        await register_user(db_session, "dup@example.com", "pass1234")
        with pytest.raises(UserAlreadyExistsError):
            await register_user(db_session, "dup@example.com", "pass5678")


class TestVerify:
    async def test_verify_success(self, db_session):
        user, token = await register_user(db_session, "test@example.com", "password123")
        verified = await verify_user(db_session, token)
        assert verified.is_verified is True
        assert verified.verification_token is None

    async def test_invalid_token_raises(self, db_session):
        with pytest.raises(InvalidTokenError):
            await verify_user(db_session, "invalid-token")


class TestLogin:
    async def test_login_success(self, db_session):
        user, token = await register_user(db_session, "test@example.com", "password123")
        await verify_user(db_session, token)
        jwt_token = await login_user(db_session, "test@example.com", "password123")
        payload = decode_access_token(jwt_token)
        assert payload is not None
        assert payload["email"] == "test@example.com"

    async def test_wrong_password_raises(self, db_session):
        user, token = await register_user(db_session, "test@example.com", "password123")
        await verify_user(db_session, token)
        with pytest.raises(InvalidCredentialsError):
            await login_user(db_session, "test@example.com", "wrongpassword")

    async def test_nonexistent_user_raises(self, db_session):
        with pytest.raises(InvalidCredentialsError):
            await login_user(db_session, "noone@example.com", "pass1234")

    async def test_unverified_user_raises(self, db_session):
        await register_user(db_session, "test@example.com", "password123")
        with pytest.raises(UserNotVerifiedError):
            await login_user(db_session, "test@example.com", "password123")


class TestGetUser:
    async def test_get_by_id(self, db_session):
        user, _ = await register_user(db_session, "test@example.com", "password123")
        found = await get_user_by_id(db_session, user.id)
        assert found is not None
        assert found.email == "test@example.com"

    async def test_get_nonexistent(self, db_session):
        found = await get_user_by_id(db_session, 999)
        assert found is None
