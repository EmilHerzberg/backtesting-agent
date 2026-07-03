"""CRUD service for AI providers and models."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.ai.keycrypto import decrypt_key, encrypt_key, is_encrypted
from src.backend.ai.models import ModelInfo, ProviderConfig
from src.backend.ai.registry import create_provider, get_all_models, remove_provider
from src.backend.db.models import AIModelDB, AIProviderDB


async def create_ai_provider(
    session: AsyncSession,
    *,
    name: str,
    provider_type: str,
    api_key: str,
    base_url: str,
    user_id: int | None = None,
) -> AIProviderDB:
    """Create a provider in DB and register it in the runtime registry.

    The key is stored **encrypted-at-rest** (``encrypt_key``); the plaintext ``api_key`` is used only
    to build the live runtime provider below.
    """
    row = AIProviderDB(
        name=name,
        provider_type=provider_type,
        api_key=encrypt_key(api_key),   # encrypted at rest (Phase 1)
        base_url=base_url,
        user_id=user_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    # Register in runtime
    config = ProviderConfig(
        name=name,
        provider_type=provider_type,
        api_key=api_key,
        base_url=base_url,
    )
    provider = create_provider(config)

    # Sync models to DB
    for model in provider.list_models():
        existing = await session.execute(
            select(AIModelDB).where(
                AIModelDB.provider_id == row.id,
                AIModelDB.model_id == model.model_id,
            )
        )
        if existing.scalar_one_or_none() is None:
            session.add(AIModelDB(
                provider_id=row.id,
                model_id=model.model_id,
                display_name=model.display_name,
                description=model.description,
                context_window=model.context_window,
                input_price_per_m=model.input_price_per_m,
                output_price_per_m=model.output_price_per_m,
                supports_streaming=model.supports_streaming,
                supports_tools=model.supports_tools,
                supports_vision=model.supports_vision,
            ))
    await session.commit()

    return row


async def get_all_ai_providers(
    session: AsyncSession, user_id: int | None = None,
) -> list[AIProviderDB]:
    query = select(AIProviderDB)
    if user_id is not None:
        # User's own providers + system (shared) providers
        query = query.where(
            (AIProviderDB.user_id == user_id) | (AIProviderDB.user_id.is_(None))
        )
    result = await session.execute(query.order_by(AIProviderDB.created_at.desc()))
    return list(result.scalars().all())


async def get_ai_provider(session: AsyncSession, provider_id: int) -> AIProviderDB | None:
    result = await session.execute(
        select(AIProviderDB).where(AIProviderDB.id == provider_id)
    )
    return result.scalar_one_or_none()


async def toggle_ai_provider(
    session: AsyncSession, provider_id: int, is_active: bool,
    user_id: int | None = None,
) -> AIProviderDB | None:
    row = await get_ai_provider(session, provider_id)
    if row is None:
        return None
    # Ownership check: can only toggle own or system providers
    if user_id is not None and row.user_id is not None and row.user_id != user_id:
        return None
    row.is_active = is_active
    await session.commit()
    await session.refresh(row)
    return row


async def delete_ai_provider(
    session: AsyncSession, provider_id: int, user_id: int | None = None,
) -> bool:
    row = await get_ai_provider(session, provider_id)
    if row is None:
        return False
    # Can only delete own providers, not system ones
    if row.user_id is None:
        return False
    if user_id is not None and row.user_id != user_id:
        return False
    remove_provider(row.name)
    # Delete models
    models = await session.execute(
        select(AIModelDB).where(AIModelDB.provider_id == provider_id)
    )
    for m in models.scalars().all():
        session.delete(m)
    session.delete(row)
    await session.commit()
    return True


async def get_all_ai_models(session: AsyncSession) -> list[AIModelDB]:
    result = await session.execute(
        select(AIModelDB).where(AIModelDB.is_active == True).order_by(AIModelDB.display_name)
    )
    return list(result.scalars().all())


async def restore_providers_from_db(session: AsyncSession) -> int:
    """Restore provider instances from DB on startup. Returns count."""
    providers = await get_all_ai_providers(session)
    count = 0
    for row in providers:
        if not row.is_active:
            continue
        try:
            config = ProviderConfig(
                name=row.name,
                provider_type=row.provider_type,
                api_key=decrypt_key(row.api_key),   # decrypt-at-rest → runtime uses plaintext
                base_url=row.base_url,
            )
            create_provider(config)
            count += 1
        except ValueError:
            pass
    return count


async def migrate_encrypt_keys(session: AsyncSession) -> int:
    """Boot migration: encrypt any AI provider keys still stored in plaintext (idempotent).

    No-op when encryption is disabled (no key). Returns the number of rows encrypted.
    """
    result = await session.execute(select(AIProviderDB))
    n = 0
    for row in result.scalars().all():
        if row.api_key and not is_encrypted(row.api_key):
            enc = encrypt_key(row.api_key)
            if enc != row.api_key:          # only when encryption actually applied
                row.api_key = enc
                n += 1
    if n:
        await session.commit()
    return n
