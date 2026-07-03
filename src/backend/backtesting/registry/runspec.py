"""ATS-1708 — RunSpec model binding a strategy to a concrete evaluation context.

A RunSpec pairs a strategy_hash with its evaluation window, data snapshot,
benchmark set, gate config, and pipeline version.  The run_spec_hash enables
idempotent execution — if a run with the same hash already exists in the
registry, it can be skipped.
"""

from __future__ import annotations

import hashlib
from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, computed_field, field_validator

from src.backend.backtesting.registry.definition import canonical_json


class EvaluationRole(StrEnum):
    """Which data window this run targets."""

    IS = "IS"
    VALIDATION = "VALIDATION"
    OOS_INTERNAL = "OOS_INTERNAL"


class RunSpec(BaseModel):
    """Binds a strategy to a concrete evaluation context (V2 §2.2 / §5.4).

    The ``run_spec_hash`` uniquely identifies the *what + where* of a run:
    same strategy on a different window, or same window with different gate
    config, will produce a different hash.
    """

    run_spec_version: Literal["2.0"] = "2.0"
    strategy_hash: str
    evaluation_role: EvaluationRole
    window_start: date
    window_end: date
    data_snapshot_hash: str
    benchmark_set_id: str = "default"
    benchmark_snapshot_hash: str = ""
    gate_config_hash: str = ""
    pipeline_version: int = 1

    @field_validator("strategy_hash")
    @classmethod
    def _strategy_hash_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("strategy_hash must not be empty")
        return v

    @field_validator("window_end")
    @classmethod
    def _window_end_after_start(cls, v: date, info: Any) -> date:
        start = info.data.get("window_start")
        if start and v <= start:
            raise ValueError(
                f"window_end ({v}) must be after window_start ({start})"
            )
        return v

    @computed_field  # type: ignore[prop-decorator]
    @property
    def run_spec_hash(self) -> str:
        """SHA-256 hex digest of the canonical JSON representation."""
        payload = self.model_dump(exclude={"run_spec_hash"}, mode="json")
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
