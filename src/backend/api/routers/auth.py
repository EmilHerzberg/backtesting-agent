from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.auth.schemas import (
    ChangePasswordRequest,
    DeleteAccountRequest,
    MessageResponse,
    RegisterResponse,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from src.backend.auth.service import (
    InvalidCredentialsError,
    InvalidTokenError,
    UserAlreadyExistsError,
    UserNotVerifiedError,
    change_password,
    get_user_by_id,
    login_user,
    register_user,
    verify_user,
)
from src.backend.auth.dependencies import get_current_user_id
from src.backend.auth.security import verify_password
from src.backend.db.engine import get_session

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(
    req: UserRegisterRequest,
    session: AsyncSession = Depends(get_session),
):
    try:
        user, token = await register_user(session, req.email, req.password)
    except UserAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    # Q3: optionally store an AI provider key at registration (encrypted at rest).
    if req.provider_type and req.api_key:
        try:
            from src.backend.ai.ai_service import create_ai_provider
            from src.backend.api.routers.ai import _default_url
            await create_ai_provider(
                session, name=f"{req.provider_type} key", provider_type=req.provider_type,
                api_key=req.api_key, base_url=_default_url(req.provider_type), user_id=user.id,
            )
        except Exception:  # noqa: BLE001 — a bad key must not fail the registration itself
            import logging
            logging.getLogger(__name__).warning("registration provider key not stored (invalid?)")
    # In production: send email instead of returning URL
    return RegisterResponse(
        message="Registrierung erfolgreich. Bitte E-Mail verifizieren.",
        verify_url=f"/verify/{token}",
    )


@router.post("/change-password", response_model=MessageResponse)
async def change_password_ep(
    req: ChangePasswordRequest,
    user_id: int = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """Change the current user's password (current password required, F-2)."""
    try:
        await change_password(session, user_id, req.current_password, req.new_password)
    except InvalidCredentialsError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    return MessageResponse(message="Password changed")


@router.delete("/account", response_model=MessageResponse)
async def delete_account_ep(
    req: DeleteAccountRequest,
    user_id: int = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """Permanently delete the current user + ALL their data after re-auth (F-4/F-7, hard delete)."""
    user = await get_user_by_id(session, user_id)
    if user is None or not verify_password(req.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password is incorrect")
    from src.backend.auth.account_service import purge_user
    await purge_user(session, user_id)
    return MessageResponse(message="Account deleted")


@router.get("/verify/{token}", response_model=MessageResponse)
async def verify(
    token: str,
    session: AsyncSession = Depends(get_session),
):
    try:
        await verify_user(session, token)
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification token",
        )
    return MessageResponse(message="Email verified successfully")


@router.post("/login", response_model=TokenResponse)
async def login(
    req: UserLoginRequest,
    session: AsyncSession = Depends(get_session),
):
    try:
        access_token = await login_user(session, req.email, req.password)
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    except UserNotVerifiedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email first",
        )
    return TokenResponse(access_token=access_token)


@router.post("/token", response_model=TokenResponse, include_in_schema=False)
async def token_form(
    form: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session),
):
    """OAuth2-compatible token endpoint for Swagger UI."""
    try:
        access_token = await login_user(session, form.username, form.password)
    except (InvalidCredentialsError, UserNotVerifiedError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    return TokenResponse(access_token=access_token)
