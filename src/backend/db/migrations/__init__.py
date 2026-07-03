"""Schema migrations for cross-cutting tables (ATS-2002 onward).

Each migration is a tiny module exposing two functions:

    def upgrade(conn) -> None:
        # sync SQLAlchemy connection, called via conn.run_sync(...)

    def downgrade(conn) -> None:
        ...

Migrations live here (not under ``event_context.migrations``) when they
touch tables outside a single bounded context, or when the V3.2 ticket
spec explicitly places them here. Migrations under
``src.backend.event_context.migrations`` remain for context-local
data migrations (e.g. ``from_ec_data``).
"""

from __future__ import annotations
