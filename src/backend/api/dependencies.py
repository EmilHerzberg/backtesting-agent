from __future__ import annotations

# NOTE (Modularisation Phase 1): the auth dependencies were moved to the kernel
# `auth` module to break the api <-> ai import cycle. They are re-exported here so
# existing `from src.backend.api.dependencies import ...` call sites keep working.
# New code should import from `src.backend.auth.dependencies` directly.
from src.backend.auth.dependencies import get_current_user_id, oauth2_scheme

__all__ = ["get_current_user_id", "oauth2_scheme"]
