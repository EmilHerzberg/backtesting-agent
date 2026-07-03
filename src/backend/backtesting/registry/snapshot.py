"""ATS-1709 + ATS-1784 — Content-hash OHLCV data + snapshot creation.

Given a pandas DataFrame of OHLCV data, compute a stable SHA-256 hash
of the content so that any change in price/volume data produces a
different hash. Also provides DataSnapshotCreator for the research loop.
"""

from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def compute_data_snapshot_hash(df: pd.DataFrame) -> str:
    """SHA-256 hex digest of OHLCV DataFrame content.

    The DataFrame is sorted by index before hashing so that row order
    doesn't affect the result.  NaN values are filled with a sentinel
    string to ensure consistent hashing.
    """
    # Sort by index for stability regardless of insertion order.
    sorted_df = df.sort_index()

    # Write to CSV bytes — deterministic, no index name variance.
    buf = io.StringIO()
    sorted_df.to_csv(buf, index=True, lineterminator="\n")
    csv_bytes = buf.getvalue().encode("utf-8")

    return hashlib.sha256(csv_bytes).hexdigest()


@dataclass
class DataSnapshot:
    """Immutable snapshot of OHLCV data for a backtest run."""

    snapshot_hash: str
    security_id: str
    provider: str
    window_start: str
    window_end: str
    n_bars: int
    bias_flags: dict[str, bool] = field(default_factory=dict)
    df: pd.DataFrame = field(default=None, repr=False)


class DataSnapshotCreator:
    """ATS-1784 — Build content-addressed snapshots for the research loop.

    Caches snapshots so identical requests return the same hash without
    re-fetching.
    """

    def __init__(self, fetch_fn: Any = None, provider_name: str = "yfinance"):
        """
        Args:
            fetch_fn: Callable(security_id, start, end) → pd.DataFrame.
                If None, caller must provide data directly.
            provider_name: Used for bias_flags lookup.
        """
        self._fetch = fetch_fn
        self._provider = provider_name
        self._cache: dict[str, DataSnapshot] = {}

    def create(
        self,
        security_id: str,
        window_start: str,
        window_end: str,
        data: pd.DataFrame | None = None,
    ) -> DataSnapshot:
        """Create or retrieve a cached snapshot.

        Args:
            security_id: Ticker symbol.
            window_start: Start date string.
            window_end: End date string.
            data: Pre-fetched OHLCV data, or None to use fetch_fn.

        Returns:
            DataSnapshot with deterministic hash.
        """
        cache_key = f"{security_id}:{window_start}:{window_end}"

        if cache_key in self._cache:
            return self._cache[cache_key]

        if data is None and self._fetch is not None:
            data = self._fetch(security_id, window_start, window_end)

        if data is None or len(data) == 0:
            raise ValueError(f"No data available for {security_id} [{window_start}, {window_end}]")

        snapshot_hash = compute_data_snapshot_hash(data)

        # Get bias flags — fallback to conservative defaults on import error.
        try:
            from src.backend.backtesting.registry.capabilities import get_bias_flags
            bias_flags = get_bias_flags(self._provider)
        except (ImportError, ModuleNotFoundError):
            bias_flags = {"survivorship_bias": True, "research_conclusion_allowed": False}
        except Exception:
            logger.warning("Failed to load bias flags for %s, using conservative defaults", self._provider, exc_info=True)
            bias_flags = {"survivorship_bias": True, "research_conclusion_allowed": False}

        snapshot = DataSnapshot(
            snapshot_hash=snapshot_hash,
            security_id=security_id,
            provider=self._provider,
            window_start=window_start,
            window_end=window_end,
            n_bars=len(data),
            bias_flags=bias_flags,
            df=data,
        )

        self._cache[cache_key] = snapshot
        return snapshot
