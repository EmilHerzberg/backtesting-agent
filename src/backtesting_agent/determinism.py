"""Backtest-Determinismus-Hash (ATS-2004) — Two-Tier Run-Fingerprint.

The Event-Context-System needs reproducible baselines to measure event-gate
effects.  Two runs of the same backtest config must, given a frozen data
snapshot and proper single-threaded BLAS / seeded RNG, produce *bit-identical*
trade sequences and equity curves.  Without this guarantee, every effect
measurement is against noisy baselines.

This module provides a Two-Tier hash scheme plus a small helper to assemble a
:class:`RunFingerprint` from any :class:`BacktestResult` + ``BacktestConfig``:

* ``h_strict`` — blake2b over canonical-sorted trade tuples.  Bit-exact.
* ``h_loose``  — blake2b over rounded equity curve (atol=1e-9) + rounded
                 metrics.  Tolerant to last-bit FP jitter.
* ``h_config`` — blake2b over canonical config + data-snapshot-SHA.  Note:
                 git SHA is *not* part of this hash — it would force a
                 golden-hash rewrite on every unrelated commit.  The SHA is
                 recorded separately in the ``git_sha`` field of the
                 fingerprint for traceability.
* ``h_agent``  — informational only, reserved for future LLM-agent suggestions.

The module is intentionally dependency-light: only ``numpy`` is used beyond
the stdlib.  ``hashlib.blake2b`` is the workhorse — fast, fixed-length, and
collision-resistant for our scale (a few hundred trades per run).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Project root — used to scope ``git rev-parse`` to the right repo.
_ROOT = Path(__file__).resolve().parents[3]

# Default golden snapshot location — must match
# :func:`scripts/freeze_yfinance_snapshot.py`.
GOLDEN_SNAPSHOT_NAME = "yfinance_snapshot_2026-05-21.parquet"
GOLDEN_SNAPSHOT_PATH = _ROOT / "data" / "golden" / GOLDEN_SNAPSHOT_NAME


@dataclass(frozen=True)
class RunFingerprint:
    """Two-Tier fingerprint of a single backtest run.

    Attributes:
        h_strict: blake2b over canonical-sorted trade tuples (bit-exact).
        h_loose: blake2b over np.round(equity_curve, 9) + rounded metrics
            (tolerant to 1e-9 FP jitter).
        h_config: blake2b over canonical config + data snapshot SHA.  Note:
            git SHA is *not* in the hash — see module docstring.
        h_agent: optional LLM-agent suggestion hash (informational only).
        git_sha: current git HEAD SHA (informational, recorded for
            traceability — not part of any hash).
    """

    h_strict: str
    h_loose: str
    h_config: str
    h_agent: str | None = None
    git_sha: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "h_strict": self.h_strict,
            "h_loose": self.h_loose,
            "h_config": self.h_config,
            "h_agent": self.h_agent,
            "git_sha": self.git_sha,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _blake2b_hex(payload: bytes) -> str:
    """Return the blake2b hexdigest of *payload* using the default 64-byte digest."""
    return hashlib.blake2b(payload).hexdigest()


def _canonical_json(obj: Any) -> str:
    """Serialise *obj* to canonical JSON (sorted keys, no whitespace)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def canonical_serialize_config(config: Any) -> str:
    """Return a stable, canonical-JSON serialisation of any backtest config.

    Accepts:
        * Pydantic ``BaseModel`` (uses ``.model_dump()``)
        * :class:`BacktestConfig` dataclass-like objects from
          ``backtesting_agent.engine.runner``
        * Plain ``dict``

    Non-serialisable attributes (DataFrames, strategy classes) are reduced to
    their class name / shape so they still contribute to the hash without
    forcing JSON to choke on arbitrary objects.
    """
    if isinstance(config, dict):
        return _canonical_json(config)

    # Pydantic
    if hasattr(config, "model_dump"):
        return _canonical_json(config.model_dump())

    # Dataclass / generic — collect public attrs by introspection.
    payload: dict[str, Any] = {}
    for key in sorted(vars(config)) if hasattr(config, "__dict__") else []:
        if key.startswith("_"):
            continue
        val = getattr(config, key)
        # Avoid heavy / non-serialisable objects but still hash *something*
        # representative so identical configs hash identically.
        try:
            if hasattr(val, "shape") and hasattr(val, "columns"):
                # pandas DataFrame: record shape + columns + index range
                shape = tuple(val.shape)
                cols = list(val.columns)
                try:
                    idx_first = str(val.index.min())
                    idx_last = str(val.index.max())
                except Exception:
                    idx_first, idx_last = "", ""
                payload[key] = {
                    "_df": True,
                    "shape": shape,
                    "columns": cols,
                    "index_first": idx_first,
                    "index_last": idx_last,
                }
            elif isinstance(val, type):
                # Strip the ``_<id(params)>`` suffix that
                # StrategyBase.create_with_params bakes into the dynamically
                # generated class name — it varies between identical runs
                # because the dict's id() is process-local.  Also capture
                # class-level params (which is what backtesting.py actually
                # consumes) so they contribute to the hash.
                cls_name = val.__name__
                if "_" in cls_name and cls_name.rsplit("_", 1)[-1].isdigit():
                    cls_name = cls_name.rsplit("_", 1)[0]
                class_payload: dict[str, Any] = {
                    "_class": cls_name,
                    "_module": val.__module__,
                }
                # Collect public class-level params (e.g. fast_period,
                # slow_period) so different parametrisations hash differently.
                for attr in dir(val):
                    if attr.startswith("_") or attr in {"mro"}:
                        continue
                    try:
                        attr_val = getattr(val, attr)
                    except Exception:
                        continue
                    if callable(attr_val) or isinstance(attr_val, (classmethod, staticmethod)):
                        continue
                    if isinstance(attr_val, (int, float, str, bool)):
                        class_payload[f"param_{attr}"] = attr_val
                payload[key] = class_payload
            else:
                # Round-trip through json to detect serialisability.
                json.dumps(val, default=str)
                payload[key] = val
        except (TypeError, ValueError):
            payload[key] = repr(val)
    return _canonical_json(payload)


def _git_sha() -> str:
    """Return the current git HEAD SHA, or ``"unknown"`` on failure."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(_ROOT),
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return out.decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        logger.debug("git rev-parse failed — falling back to 'unknown'")
        return "unknown"


def _data_snapshot_sha(snapshot_path: Path | None = None) -> str:
    """Return blake2b of the data snapshot file, or ``"missing"`` if absent.

    We deliberately do **not** raise here — production runs may not have the
    golden snapshot.  Only the determinism CI check (which knows it requires
    the snapshot) should treat ``"missing"`` as a failure.
    """
    path = Path(snapshot_path) if snapshot_path else GOLDEN_SNAPSHOT_PATH
    if not path.exists():
        return "missing"
    try:
        return _blake2b_hex(path.read_bytes())
    except OSError:
        return "unreadable"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_h_strict(trades: list[Any]) -> str:
    """Bit-exact hash over canonical-sorted trade tuples.

    Each :class:`TradeDetail` is reduced to a stable tuple of
    ``(entry_time, exit_time, side, entry_price, exit_price, size)`` and
    sorted lexicographically before hashing.  This means a swap in trade
    ordering — common when parallel workers race — does not change the hash.
    """
    tuples: list[list[Any]] = []
    for t in trades:
        # TradeDetail dataclass attributes
        entry_time = getattr(t, "entry_time", "")
        exit_time = getattr(t, "exit_time", "")
        side = getattr(t, "side", "")
        entry_price = float(getattr(t, "entry_price", 0.0))
        exit_price = float(getattr(t, "exit_price", 0.0))
        size = float(getattr(t, "size", 0.0))
        tuples.append([
            str(entry_time),
            str(exit_time),
            str(side),
            entry_price,
            exit_price,
            size,
        ])
    # Sort lex by stringified representation so order is deterministic
    tuples.sort(key=lambda row: json.dumps(row, default=str))
    payload = _canonical_json(tuples).encode("utf-8")
    return _blake2b_hex(payload)


def compute_h_loose(
    equity_curve: list[float] | np.ndarray,
    metrics: dict[str, float],
    *,
    equity_decimals: int = 9,
    metric_decimals: int = 6,
) -> str:
    """Tolerant hash: rounded equity curve + rounded metrics.

    With ``equity_decimals=9`` (atol=1e-9), runs that differ only in the
    last-bit FP jitter from BLAS or summation-order shuffling will still
    produce the same ``h_loose``.  This is the metric the CI check uses for
    its ``np.allclose`` assertion.
    """
    arr = np.asarray(list(equity_curve), dtype=np.float64)
    if arr.size == 0:
        eq_bytes = b""
    else:
        eq_q = np.round(arr, equity_decimals)
        eq_bytes = eq_q.tobytes()

    metrics_q: dict[str, float] = {}
    for key in sorted(metrics):
        val = metrics[key]
        if val is None:
            metrics_q[key] = None  # type: ignore[assignment]
            continue
        try:
            fval = float(val)
        except (TypeError, ValueError):
            metrics_q[key] = str(val)  # type: ignore[assignment]
            continue
        if np.isnan(fval) or np.isinf(fval):
            metrics_q[key] = "nan" if np.isnan(fval) else ("inf" if fval > 0 else "-inf")  # type: ignore[assignment]
        else:
            metrics_q[key] = round(fval, metric_decimals)

    payload = eq_bytes + _canonical_json(metrics_q).encode("utf-8")
    return _blake2b_hex(payload)


def compute_h_config(
    config: Any,
    *,
    snapshot_path: Path | None = None,
) -> str:
    """Hash the canonical config + data snapshot SHA.

    Same config + same data snapshot => identical h_config.  Git SHA is
    deliberately excluded — including it would invalidate every stored
    golden hash on every unrelated commit.  The current SHA is captured on
    the fingerprint's ``git_sha`` field for traceability.
    """
    config_canon = canonical_serialize_config(config)
    snap = _data_snapshot_sha(snapshot_path)
    payload = f"{config_canon}|snap={snap}".encode("utf-8")
    return _blake2b_hex(payload)


def compute_run_fingerprint(
    result: Any,
    config: Any,
    *,
    snapshot_path: Path | None = None,
    h_agent: str | None = None,
) -> RunFingerprint:
    """Assemble a :class:`RunFingerprint` from a backtest result + config.

    Args:
        result: A :class:`BacktestResult` (must expose ``trades``,
            ``equity_curve``, and metric attributes).
        config: A :class:`BacktestConfig` or :class:`BacktestFullConfig`.
        snapshot_path: Override path to the data snapshot file.  Defaults to
            :data:`GOLDEN_SNAPSHOT_PATH`.
        h_agent: Optional informational hash of an LLM-agent suggestion.

    Returns:
        A frozen :class:`RunFingerprint`.
    """
    trades = getattr(result, "trades", []) or []
    equity_curve = getattr(result, "equity_curve", []) or []
    metrics = {
        "total_return": getattr(result, "total_return", 0.0),
        "sharpe_ratio": getattr(result, "sharpe_ratio", 0.0),
        "max_drawdown": getattr(result, "max_drawdown", 0.0),
        "sortino_ratio": getattr(result, "sortino_ratio", 0.0),
        "win_rate": getattr(result, "win_rate", 0.0),
        "trade_count": getattr(result, "trade_count", 0),
        "profit_factor": getattr(result, "profit_factor", 0.0),
        "calmar_ratio": getattr(result, "calmar_ratio", 0.0),
        "buy_hold_return": getattr(result, "buy_hold_return", 0.0),
        "exposure_time": getattr(result, "exposure_time", 0.0),
    }

    h_strict = compute_h_strict(trades)
    h_loose = compute_h_loose(equity_curve, metrics)
    h_config = compute_h_config(config, snapshot_path=snapshot_path)

    return RunFingerprint(
        h_strict=h_strict,
        h_loose=h_loose,
        h_config=h_config,
        h_agent=h_agent,
        git_sha=_git_sha(),
    )


# ---------------------------------------------------------------------------
# Determinism-mode helpers
# ---------------------------------------------------------------------------


def is_determinism_mode() -> bool:
    """Return ``True`` when env var ``BACKTEST_DETERMINISM_MODE`` is truthy.

    A truthy value is ``"1"``, ``"true"``, ``"yes"`` (case-insensitive).
    """
    raw = os.environ.get("BACKTEST_DETERMINISM_MODE", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def apply_determinism_env() -> dict[str, str]:
    """Set process-level env vars for determinism and return the applied map.

    Idempotent.  Callers should invoke this *before* importing numpy / scipy
    so that BLAS threading is honoured.  Returns the env vars that were set
    (existing values are not overwritten — caller may pre-pin).
    """
    targets = {
        "BACKTEST_DETERMINISM_MODE": "true",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "BLIS_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "PYTHONHASHSEED": "0",
    }
    applied: dict[str, str] = {}
    for key, val in targets.items():
        if os.environ.get(key) != val:
            os.environ.setdefault(key, val)
        applied[key] = os.environ[key]
    return applied
