from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.backend.shared.config import settings
from src.backend.api.routers.auth import router as auth_router
from src.backend.api.routers.ai import router as ai_router
from src.backend.ai.research.router import router as research_router  # autonomous research engine — /api/research
from src.backend.db.engine import async_session, engine
from src.backend.db.init_db import create_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    from src.backend.shared.logging import setup_logging
    setup_logging()
    await create_tables(engine)   # create_all + idempotent _MIGRATIONS

    # Research runs still 'running' after a restart lost their task → mark interrupted.
    from src.backend.ai.research.persistence import mark_orphaned_runs_interrupted
    await mark_orphaned_runs_interrupted()

    # Encrypt any plaintext AI-provider keys at rest (idempotent), then restore the provider registry.
    from src.backend.ai.ai_service import migrate_encrypt_keys, restore_providers_from_db
    async with async_session() as session:
        await migrate_encrypt_keys(session)
    async with async_session() as session:
        await restore_providers_from_db(session)

    yield
    # No broker / scheduler to tear down in the standalone research agent.


app = FastAPI(
    title="Backtesting Agent",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)       # /api/auth
app.include_router(ai_router)         # /api/ai — providers/models/chat
app.include_router(research_router)   # /api/research — the autonomous research loop
