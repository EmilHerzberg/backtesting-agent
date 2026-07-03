"""Backward-compatible shim — schema bootstrap moved to ``src.backend.bootstrap``.

The model-registration + migration logic now lives in the composition root
:mod:`src.backend.bootstrap` (Modularisation Phase 2c), so the ``db`` kernel
(``db.base`` / ``db.models`` / ``db.engine``) imports no feature module. This
module re-exports the public API unchanged so the existing
``from src.backend.db.init_db import create_tables, drop_tables`` call sites
(app startup, tests, scripts) keep working.
"""
from __future__ import annotations

from src.backend.bootstrap import (
    _MIGRATIONS,
    _run_migrations,
    create_tables,
    drop_tables,
)

__all__ = ["create_tables", "drop_tables", "_run_migrations", "_MIGRATIONS"]
