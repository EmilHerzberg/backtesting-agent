"""ATS-1777/1778/1779 — Lineage tracking for strategy families.

Lineage groups related strategy searches. New hypothesis = new lineage root.
Mutation of existing strategy = child lineage (shares OOS budget).
Lineage does NOT affect strategy_hash.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Lineage:
    """A research lineage — groups related strategy searches."""

    lineage_id: str
    root_strategy_hash: str | None = None
    parent_lineage_id: str | None = None
    declared_by: str = "system"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_root(self) -> bool:
        return self.parent_lineage_id is None


class LineageTracker:
    """Manages strategy research lineages.

    New hypothesis = new root lineage.
    Parameter mutation = child lineage (inherits parent's OOS budget).
    """

    def __init__(self) -> None:
        self._lineages: dict[str, Lineage] = {}

    def create_root(self, strategy_hash: str | None = None, declared_by: str = "system") -> Lineage:
        """Create a new root lineage (new hypothesis)."""
        lineage = Lineage(
            lineage_id=f"lin_{uuid.uuid4().hex[:12]}",
            root_strategy_hash=strategy_hash,
            parent_lineage_id=None,
            declared_by=declared_by,
        )
        self._lineages[lineage.lineage_id] = lineage
        return lineage

    def create_child(self, parent_lineage_id: str, strategy_hash: str | None = None, declared_by: str = "system") -> Lineage:
        """Create a child lineage (mutation of existing)."""
        if parent_lineage_id not in self._lineages:
            raise ValueError(f"Parent lineage {parent_lineage_id} not found")

        lineage = Lineage(
            lineage_id=f"lin_{uuid.uuid4().hex[:12]}",
            root_strategy_hash=strategy_hash,
            parent_lineage_id=parent_lineage_id,
            declared_by=declared_by,
        )
        self._lineages[lineage.lineage_id] = lineage
        return lineage

    def get(self, lineage_id: str) -> Lineage | None:
        return self._lineages.get(lineage_id)

    def get_root(self, lineage_id: str) -> Lineage | None:
        """Walk up to the root lineage."""
        current = self._lineages.get(lineage_id)
        while current and current.parent_lineage_id:
            current = self._lineages.get(current.parent_lineage_id)
        return current

    def children_of(self, lineage_id: str) -> list[Lineage]:
        """Get all direct children of a lineage."""
        return [
            l for l in self._lineages.values()
            if l.parent_lineage_id == lineage_id
        ]

    def family_size(self, lineage_id: str) -> int:
        """Count all lineages in the same family (root + all descendants)."""
        root = self.get_root(lineage_id)
        if not root:
            return 0
        count = 1
        queue = [root.lineage_id]
        while queue:
            parent = queue.pop(0)
            children = self.children_of(parent)
            count += len(children)
            queue.extend(c.lineage_id for c in children)
        return count

    def serialize(self) -> list[dict]:
        """Flat list of all lineage nodes for the lineage-graph view (ATSX-26)."""
        return [
            {
                "lineage_id": lin.lineage_id,
                "parent_lineage_id": lin.parent_lineage_id,
                "root_strategy_hash": lin.root_strategy_hash,
                "declared_by": lin.declared_by,
                "created_at": lin.created_at.isoformat() if lin.created_at else None,
            }
            for lin in self._lineages.values()
        ]
