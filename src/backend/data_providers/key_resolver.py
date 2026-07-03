"""Resolve a data-provider API key for the current user (ATS-1589).

Resolution order:
    1. data_providers row for (user_id, provider_type) — user-managed key
       set via the /setup UI. Wins over the .env value.
    2. settings.<provider>_api_key — legacy / system-wide fallback set by
       whoever deployed the server.
    3. None — feature simply not configured for this user.

This indirection lets data-fetching code stay user-agnostic at call sites:
they pass a session + user_id, and get back whichever key applies.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.db.models import DataProviderDB
from src.backend.shared.config import settings

KeySource = Literal["db", "env", None]

# Maps provider_type IDs to the corresponding settings attribute on the
# legacy .env-based config. Keep this list in sync with
# api/routers/data_providers.PROVIDER_TYPES.
_ENV_ATTR: dict[str, str] = {
    "alpha_vantage": "alpha_vantage_api_key",
    "polygon": "polygon_api_key",
    "finnhub": "finnhub_api_key",
    "twelve_data": "twelve_data_api_key",
    "tiingo": "tiingo_api_key",
}


async def resolve_data_provider_key(
    session: AsyncSession,
    user_id: int | None,
    provider_type: str,
) -> tuple[str | None, KeySource]:
    """Return ``(api_key, source)`` for *provider_type*.

    Args:
        session: Async DB session.
        user_id: The current user. ``None`` skips the DB lookup and only
            consults env (useful for system-level callers like the
            scheduler before a user is in scope).
        provider_type: Provider id, e.g. ``"alpha_vantage"``.

    Returns:
        ``(key, "db"|"env"|None)``. Key is None when nothing is configured.
    """
    if user_id is not None:
        stmt = select(DataProviderDB).where(
            DataProviderDB.user_id == user_id,
            DataProviderDB.provider_type == provider_type,
            DataProviderDB.is_active.is_(True),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row and row.api_key:
            return row.api_key, "db"

    env_attr = _ENV_ATTR.get(provider_type)
    if env_attr:
        value = getattr(settings, env_attr, "") or ""
        if value:
            return value, "env"

    return None, None


def resolve_data_provider_key_sync(
    user_id: int | None,
    provider_type: str,
) -> tuple[str | None, KeySource]:
    """Sync variant for callers outside the async stack.

    DB lookup is skipped — returns env value or None. Callers that need
    the DB key must use the async version with a live session.
    """
    env_attr = _ENV_ATTR.get(provider_type)
    if env_attr:
        value = getattr(settings, env_attr, "") or ""
        if value:
            return value, "env"
    return None, None
