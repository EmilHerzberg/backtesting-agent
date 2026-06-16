"""Centralized logging configuration for the trading platform."""
from __future__ import annotations

import logging
import sys

from backtesting_agent.shared.config import settings

_CONFIGURED = False


def setup_logging(level: str = "INFO") -> None:
    """Configure structured logging for the entire application.

    Call once at startup (e.g., in FastAPI lifespan).
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Console handler with structured format
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    # Clear existing handlers and add ours
    root.handlers.clear()
    root.addHandler(handler)

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("ib_async").setLevel(logging.WARNING)

    _CONFIGURED = True
    log = logging.getLogger(__name__)
    log.info("Logging initialized (level=%s)", level)

    # Security warning
    from backtesting_agent.shared.config import settings
    if settings.secret_key == "dev-secret-key-change-in-production":
        log.warning(
            "SECRET_KEY is using the default dev value! "
            "Set SECRET_KEY in .env for production."
        )
