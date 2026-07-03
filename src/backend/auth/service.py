from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.auth.security import (
    create_access_token,
    generate_verification_token,
    hash_password,
    verify_password,
)
from src.backend.auth.db_models import UserDB


class AuthError(Exception):
    pass


class UserAlreadyExistsError(AuthError):
    pass


class InvalidCredentialsError(AuthError):
    pass


class UserNotVerifiedError(AuthError):
    pass


class InvalidTokenError(AuthError):
    pass


async def register_user(
    session: AsyncSession, email: str, password: str
) -> tuple[UserDB, str]:
    """Register a new user.

    Returns:
        Tuple of (user, verification_token).

    Raises:
        UserAlreadyExistsError if email already registered.
    """
    existing = await session.execute(
        select(UserDB).where(UserDB.email == email)
    )
    if existing.scalar_one_or_none() is not None:
        raise UserAlreadyExistsError(f"Email {email} already registered")

    token = generate_verification_token()
    user = UserDB(
        email=email,
        password_hash=hash_password(password),
        is_verified=False,
        verification_token=token,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user, token


async def verify_user(session: AsyncSession, token: str) -> UserDB:
    """Verify a user by their verification token.

    Raises:
        InvalidTokenError if token is invalid.
    """
    result = await session.execute(
        select(UserDB).where(UserDB.verification_token == token)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise InvalidTokenError("Invalid verification token")

    user.is_verified = True
    user.verification_token = None
    await session.commit()
    await session.refresh(user)
    return user


async def login_user(
    session: AsyncSession, email: str, password: str
) -> str:
    """Authenticate and return a JWT access token.

    Raises:
        InvalidCredentialsError if email/password wrong.
        UserNotVerifiedError if user not verified.
    """
    result = await session.execute(
        select(UserDB).where(UserDB.email == email)
    )
    user = result.scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError("Invalid email or password")

    if not user.is_verified:
        raise UserNotVerifiedError("Please verify your email first")

    token = create_access_token({"sub": str(user.id), "email": user.email})
    return token


async def get_user_by_id(session: AsyncSession, user_id: int) -> UserDB | None:
    result = await session.execute(
        select(UserDB).where(UserDB.id == user_id)
    )
    return result.scalar_one_or_none()


async def change_password(
    session: AsyncSession, user_id: int, current: str, new: str
) -> None:
    """Change a user's password after verifying the current one (F-2).

    Raises InvalidCredentialsError if the current password is wrong.
    """
    user = await get_user_by_id(session, user_id)
    if user is None or not verify_password(current, user.password_hash):
        raise InvalidCredentialsError("Current password is incorrect")
    if len(new) < 8:
        raise AuthError("New password must be at least 8 characters")
    user.password_hash = hash_password(new)
    await session.commit()
