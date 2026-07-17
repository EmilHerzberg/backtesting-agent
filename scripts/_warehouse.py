"""Shared read-only loader for the monorepo price warehouse (asset_prices.db).

Used by the V3 calibration harness (and any future warehouse consumer in this
repo). Implements the protocol's data-access guards:

- Adjustment convention (CRITICAL): Close = adjc (split+dividend adjusted);
  O/H/L are scaled by adjc/c. Raw c injects fake crash-days on splits.
- FIX-1: per-name adjustment-validity assertion (positive raw closes, finite
  ratio, no one-bar spike excursions) — raises WarehouseDataError.
- FIX-2: hard pre-2000 assertion for calibration fetches (no returned bar may
  precede 2000-01-01 — keeps the 1995-99 partial-survivorship era out).
- Quality layer: if the warehouse carries the `asset_data_quality` table
  (scan_asset_price_quality.py in the monorepo), names with verdict != 'ok'
  are refused by default. The calibration harness passes
  enforce_quality=False because its panel was already gated by the FROZEN
  pre-registered AM-2 rules at draw time (same thresholds, in-window scope);
  everything else should keep the default.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

WAREHOUSE_PATH = (Path(__file__).resolve().parent.parent.parent
                  / "data" / "asset_prices.db")

RATIO_EVENT_PCT = 0.01
RATIO_REVERT_PCT = 0.005


class WarehouseDataError(RuntimeError):
    """A name failed a data-validity guard; calibration must skip it loudly."""


def connect(db_path: str | Path = WAREHOUSE_PATH) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def resolve_ticker(con: sqlite3.Connection, symbol: str) -> int:
    row = con.execute("SELECT ticker_id FROM tickers WHERE symbol=?",
                      (symbol,)).fetchone()
    if row is None:
        raise WarehouseDataError(f"{symbol}: not in warehouse")
    return int(row[0])


def _quality_verdict(con: sqlite3.Connection, ticker_id: int) -> str | None:
    try:
        row = con.execute(
            "SELECT verdict FROM asset_data_quality WHERE ticker_id=?",
            (ticker_id,)).fetchone()
    except sqlite3.OperationalError:   # table absent (scan never run)
        return None
    return row[0] if row else None


def _assert_ratio_valid(symbol: str, c: np.ndarray, adjc: np.ndarray) -> None:
    """FIX-1: spike rule — identical to the frozen panel-draw fingerprint."""
    if np.any(c <= 0):
        raise WarehouseDataError(f"{symbol}: nonpositive raw close")
    r = adjc / c
    if not np.all(np.isfinite(r)):
        raise WarehouseDataError(f"{symbol}: nonfinite adjustment ratio")
    rel = np.diff(r) / np.maximum(r[:-1], 1e-12)
    for i in np.flatnonzero(np.abs(rel) > RATIO_EVENT_PCT):
        if i + 1 < len(rel):
            back = (r[i + 2] - r[i]) / max(abs(r[i]), 1e-12)
            if abs(back) < RATIO_REVERT_PCT and abs(rel[i + 1]) > RATIO_EVENT_PCT:
                raise WarehouseDataError(f"{symbol}: adjustment-ratio spike at "
                                         f"index {i}")


def warehouse_fetch(symbol: str, start: str, end: str, *,
                    adjusted: bool = True, con: sqlite3.Connection | None = None,
                    enforce_quality: bool = True,
                    assert_post2000: bool = True) -> pd.DataFrame:
    """OHLCV DataFrame (DatetimeIndex; Open/High/Low/Close/Volume) as
    run_backtest(BacktestConfig(data=...)) consumes it."""
    own = con is None
    con = con or connect()
    try:
        tid = resolve_ticker(con, symbol)
        if enforce_quality:
            v = _quality_verdict(con, tid)
            if v is not None and v != "ok":
                raise WarehouseDataError(f"{symbol}: asset_data_quality "
                                         f"verdict={v}")
        lo = int(start.replace("-", "")[:8])
        hi = int(end.replace("-", "")[:8])
        rows = con.execute(
            "SELECT d,o,h,l,c,adjc,v FROM prices WHERE ticker_id=? AND "
            "d BETWEEN ? AND ? ORDER BY d", (tid, lo, hi)).fetchall()
    finally:
        if own:
            con.close()
    if not rows:
        raise WarehouseDataError(f"{symbol}: no bars in [{start}, {end}]")
    arr = np.asarray(rows, dtype=np.float64)
    d = arr[:, 0].astype(np.int64)
    if assert_post2000 and int(d.min()) < 20000101:
        raise WarehouseDataError(f"{symbol}: pre-2000 bar leaked into a "
                                 f"calibration fetch (d={int(d.min())})")
    o, h, lo_, c, adjc, vol = (arr[:, i] for i in range(1, 7))
    _assert_ratio_valid(symbol, c, adjc)
    if adjusted:
        scale = adjc / c
        o, h, lo_, close = o * scale, h * scale, lo_ * scale, adjc
    else:
        close = c
    idx = pd.to_datetime(d.astype(str), format="%Y%m%d")
    return pd.DataFrame({"Open": o, "High": h, "Low": lo_, "Close": close,
                         "Volume": vol}, index=idx)
