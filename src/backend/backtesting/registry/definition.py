"""ATS-1704 — StrategyDefinition model with content-addressed hashing.

A StrategyDefinition captures the *executable* strategy identity,
independent of research metadata (notes, lineage, author, windows).
Two definitions with the same fields produce the same strategy_hash.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, computed_field, field_validator


# Allowed bar sizes — extend as needed.
ALLOWED_BAR_SIZES = frozenset({"1d", "1h", "4h", "15m", "5m", "1m", "1w"})


def canonical_json(obj: dict[str, Any]) -> str:
    """Produce a deterministic JSON string from a dict.

    Keys are sorted recursively, separators are compact, and ASCII is
    enforced so the output is byte-stable across platforms.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class StrategyDefinition(BaseModel):
    """Frozen executable strategy identity (V2 §2.1 / §5.3).

    The ``strategy_hash`` is a sha256 hex digest of the canonical JSON
    representation of all fields.  It uniquely identifies *what* the
    strategy does — not *why* it was proposed or *when* it was run.
    """

    definition_version: Literal["2.0"] = "2.0"
    template_id: str
    template_version: int
    template_hash: str
    params: dict[str, Any]
    security_id: str
    bar_size: str
    cost_profile_id: str
    cost_profile_hash: str
    execution_semantics: dict[str, Any]
    strategy_family: str

    # --- validators ---

    @field_validator("template_id")
    @classmethod
    def _template_id_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("template_id must not be empty")
        return v

    @field_validator("bar_size")
    @classmethod
    def _bar_size_allowed(cls, v: str) -> str:
        if v not in ALLOWED_BAR_SIZES:
            raise ValueError(
                f"bar_size must be one of {sorted(ALLOWED_BAR_SIZES)}, got {v!r}"
            )
        return v

    @field_validator("params")
    @classmethod
    def _params_is_dict(cls, v: Any) -> dict[str, Any]:
        if not isinstance(v, dict):
            raise ValueError("params must be a dict")
        return v

    # --- hashing ---

    @computed_field  # type: ignore[prop-decorator]
    @property
    def strategy_hash(self) -> str:
        """SHA-256 hex digest of the canonical JSON representation."""
        # Exclude the hash itself from the computation.
        payload = self.model_dump(exclude={"strategy_hash"})
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
