"""Frozen, deterministic OHLCV for the verification harness (ATS-1794).

Produces the exact shape the DataProvider contract returns — a tz-naive DatetimeIndex named "Date"
with capitalized Open/High/Low/Close/Volume columns — as a seeded geometric random walk with enough
trend and noise to trigger crossovers. `frozen_fetch()` returns a `fetch_fn(security_id, start, end)`
usable directly as `run_research(..., fetch_fn=...)`, so backtests are offline and bit-reproducible
(RUN-6). No network, no golden file needed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def make_ohlcv(
    *,
    days: int = 900,
    start: str = "2015-01-01",
    start_price: float = 100.0,
    seed: int = 7,
    drift: float = 0.0004,
    vol: float = 0.013,
) -> pd.DataFrame:
    """Deterministic synthetic daily OHLCV. Same args → identical frame (bit-for-bit)."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start=start, periods=days)  # business days, tz-naive
    rets = rng.normal(drift, vol, size=days)
    close = start_price * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[start_price], close[:-1]])  # open = prior close
    hi_noise = np.abs(rng.normal(0.0, vol / 3.0, days))
    lo_noise = np.abs(rng.normal(0.0, vol / 3.0, days))
    high = np.maximum(open_, close) * (1.0 + hi_noise)
    low = np.minimum(open_, close) * (1.0 - lo_noise)
    volume = rng.integers(500_000, 5_000_000, days)
    df = pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=idx,
    )
    df.index.name = "Date"
    return df[OHLCV_COLUMNS]


def frozen_fetch(data: dict[str, pd.DataFrame] | None = None, **make_kwargs):
    """Return a `fetch_fn(security_id, window_start, window_end)` serving frozen OHLCV offline.

    A frozen snapshot ignores the requested window (returns the full series) so tests never hit an
    empty slice; per-symbol frames are generated once and cached for stability across calls/runs.
    Pass `data={"AAPL": df}` to pin exact frames, or rely on the seeded generator.
    """
    store: dict[str, pd.DataFrame] = dict(data or {})

    def _fetch(security_id: str, window_start=None, window_end=None) -> pd.DataFrame:  # noqa: ARG001
        if security_id not in store:
            store[security_id] = make_ohlcv(**make_kwargs)
        return store[security_id]

    return _fetch
