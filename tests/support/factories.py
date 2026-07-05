"""Test factories for the verification harness (ATS-1794).

- `register_mock_provider` — put the MockProvider class+instance in the runtime registry so
  `agent_mode='full_ai'/'ai_assisted'` with `provider=<name>` routes to it (returns the live
  instance so a test can inspect `.calls`).
- `seed_verified_user` / `mint_token` / `seed_provider` — DB seeding + JWT for the later API-layer
  tests (auth, key vault, isolation). Kept here so every phase shares one set of helpers.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.ai.models import ProviderConfig
from src.backend.ai.registry import create_provider, register_provider_type
from tests.support.mock_provider import MockProvider


def register_mock_provider(name: str = "mock-provider", *, response=None) -> MockProvider:
    """Register MockProvider (class + a named instance) in the runtime registry. Returns the instance."""
    register_provider_type(MockProvider.PROVIDER_TYPE, MockProvider)
    cfg = ProviderConfig(name=name, provider_type=MockProvider.PROVIDER_TYPE, api_key="", base_url="")
    inst = create_provider(cfg)  # type: ignore[assignment]
    if response is not None:
        inst._response = response  # noqa: SLF001 — test double, deliberate override
    assert isinstance(inst, MockProvider)
    return inst


async def seed_verified_user(
    session: AsyncSession,
    *,
    email: str = "ravi@example.com",
    password: str = "password123",
):
    """Register + verify a user; returns the UserDB row (login-ready)."""
    from src.backend.auth.service import register_user, verify_user

    user, token = await register_user(session, email, password)
    await verify_user(session, token)
    return user


def mint_token(user) -> str:
    """Mint a valid access token for a seeded user (for Authorization: Bearer …)."""
    from src.backend.auth.security import create_access_token

    return create_access_token({"sub": str(user.id), "email": user.email})


async def seed_provider(
    session: AsyncSession,
    *,
    user_id: int,
    name: str = "ravi-deepseek",
    provider_type: str = "deepseek",
    api_key: str = "sk-testtesttesttest",
    base_url: str = "https://api.deepseek.com",
):
    """Seed a provider row (encrypted at rest) + register it in the runtime registry."""
    from src.backend.ai.ai_service import create_ai_provider

    return await create_ai_provider(
        session,
        name=name,
        provider_type=provider_type,
        api_key=api_key,
        base_url=base_url,
        user_id=user_id,
    )
