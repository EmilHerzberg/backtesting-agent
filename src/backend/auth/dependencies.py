from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.auth.security import decode_access_token
from src.backend.db.engine import get_session

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


async def get_current_user_id(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> int:
    """Extract + validate the current user ID from the JWT, and confirm the user still exists (F-8).

    The existence check (one indexed PK lookup) makes a **deleted** user's still-unexpired token stop
    authenticating server-side — negligible cost at bt-site scale.
    """
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    from src.backend.auth.service import get_user_by_id
    if await get_user_by_id(session, int(user_id)) is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )
    return int(user_id)
