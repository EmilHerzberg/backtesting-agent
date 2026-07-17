"""Draw the frozen Coverage-Calibration-V3 asset panel (pre-registration artifact).

Implements COVERAGE-CALIBRATION-V3-PROTOCOL.md §2 (stratified sample design) and the
§11 freeze list items that concern the panel:

- Eligible pools (living / early-death delisted / late-death delisted) with the
  protocol's SQL conditions, reconciled against the committed live counts
  (living 2142 / early 4684 / late 4179).
- Per-name features: realized vol (annualized stdev of daily adjusted log-returns,
  in-window 2000-2023) and PIT market cap (raw close x ffilled quarterly shares,
  median in-window).
- FIX-5:  cutpoints (vol median, cap tertiles, tail p75) on the COMBINED
  living+delisted eligible pool; living-only boundaries reported alongside.
- FIX-8:  living 132 = 6 (cap x vol) cells x 22, sector spread by largest-remainder
  proportional to each cell's observed composition, soft floor >=6 distinct sectors.
- FIX-9:  delisted sleeve 66 = 33 early-death + 33 late-death, era x vol stratified.
- FIX-10: >=50 names with vol >= combined-pool p75 (tail requirement, asserted).
- FIX-11: primary seed 20230701; alternate panels for seeds 20230702..20230705
  emitted to a side file (draw-level stability check input).
- FIX-1:  per-name adjustment fingerprint (c>0 assertion, adjc/c finite +
  piecewise-monotone, min/max ratio, jump count) on every drawn name; a name
  failing the guard is excluded with a logged reason and deterministically
  replaced from its stratum's permutation order.
- FIX-35: frame-content snapshot (both pools + features) committed with its own
  sha256, plus a warehouse-content fingerprint; cutpoints stored as literal
  constants in panel.json.
- FIX-37: OOS reserve = enumerated (S&P-100 as fetched 2026-07-17, Wikipedia list
  dated 2025-09-22) INTERSECT warehouse, UNION legacy-5 {AAPL,MSFT,NVDA,KO,PG};
  excluded from the living pool BEFORE allocation; the large-liquid x low-vol
  stratum is asserted to still fill its quota of 22.

Outputs (write-once; re-run must reproduce byte-identical panel or --rebuild
asserts the committed hash):
- docs/design/calibration-v3-panel.json
- docs/design/calibration-v3-frame-snapshot.json
- docs/design/calibration-v3-panel-altseeds.json
- docs/design/calibration-v3-panel-summary.md   (human-readable eyeball doc)

Usage:  python scripts/draw_calibration_panel.py [--db ../data/asset_prices.db]
        python scripts/draw_calibration_panel.py --rebuild   # assert committed hash
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# --------------------------------------------------------------------------- #
# Frozen constants (protocol section 11)
# --------------------------------------------------------------------------- #

PRIMARY_SEED = 20230701
SEEDS_K = [20230701, 20230702, 20230703, 20230704, 20230705]

WINDOW_LO, WINDOW_HI = 20000101, 20231231

LIVING_MIN_BARS = 1500      # in-window
EARLY_MIN_BARS = 250        # in-window (see reconciliation note in the manifest)
LATE_MIN_BARS = 750         # in-window
EARLY_VINTAGE_MAX_FIRST = "2000-06-30"
LATE_MIN_LAST = "2011-01-01"

LIVING_QUOTA_PER_CELL = 22  # 6 cells x 22 = 132
DELISTED_EARLY_QUOTA = 33
DELISTED_LATE_QUOTA = 33
SECTOR_SOFT_FLOOR = 6       # distinct sectors per living cell (soft)
TAIL_MIN_NAMES = 50         # FIX-10: names with vol >= combined p75

TRADING_DAYS = 252.0

# Committed reference counts from the protocol (re-verified live 2026-07-16).
REFERENCE_COUNTS = {"living": 2142, "early_delisted": 4684, "late_delisted": 4179}

# Canonical sector normalization map (protocol section 2.2). Raw -> canonical;
# raw values not present here (or mapping to None) are INELIGIBLE.
SECTOR_MAP = {
    "Financial Services": "Financials", "Financials": "Financials",
    "Financial": "Financials", "Banks": "Financials",
    "Consumer Finance": "Financials",
    "Technology": "Technology", "Information Technology": "Technology",
    "Electronic Equipment": "Technology",
    "Healthcare": "Healthcare", "Pharmaceuticals": "Healthcare",
    "Industrials": "Industrials", "Industrial Goods": "Industrials",
    "Machinery": "Industrials",
    "Consumer Cyclical": "Consumer Cyclical",
    "Consumer Discretionary": "Consumer Cyclical",
    "Consumer Goods": "Consumer Cyclical",
    "Consumer Defensive": "Consumer Defensive",
    "Consumer Staples": "Consumer Defensive",
    "Consumer Non-Cyclicals": "Consumer Defensive",
    "Communication Services": "Communication Services",
    "Wireless Telecommunication Services": "Communication Services",
    "Energy": "Energy",
    "Basic Materials": "Basic Materials", "Materials": "Basic Materials",
    "Real Estate": "Real Estate", "REITs": "Real Estate",
    "Utilities": "Utilities",
}

# FIX-37: enumerated OOS reserve. Wikipedia S&P-100 component list (dated
# 2025-09-22 on the page), fetched 2026-07-17. Frozen verbatim; symbols not
# found in the warehouse are logged, never silently dropped.
SP100_AS_FETCHED = [
    "AAPL", "ABBV", "ABT", "ACN", "ADBE", "AMAT", "AMD", "AMGN", "AMT", "AMZN",
    "AVGO", "AXP", "BA", "BAC", "BKNG", "BLK", "BMY", "BNY", "BRK.B", "C",
    "CAT", "CL", "CMCSA", "COF", "COP", "COST", "CRM", "CSCO", "CVS", "CVX",
    "DE", "DHR", "DIS", "DUK", "EMR", "FDX", "GD", "GE", "GEV", "GILD",
    "GM", "GOOG", "GOOGL", "GS", "HD", "HONA", "IBM", "INTC", "INTU", "ISRG",
    "JNJ", "JPM", "KO", "LIN", "LLY", "LMT", "LOW", "LRCX", "MA", "MCD",
    "MDLZ", "MDT", "META", "MMM", "MO", "MRK", "MS", "MSFT", "MU", "NEE",
    "NFLX", "NKE", "NOW", "NVDA", "ORCL", "PEP", "PFE", "PG", "PLTR", "PM",
    "QCOM", "RTX", "SBUX", "SCHW", "SO", "SPG", "T", "TMO", "TMUS", "TSLA",
    "TXN", "UBER", "UNH", "UNP", "UPS", "USB", "V", "VZ", "WFC", "WMT", "XOM",
]
LEGACY_RESERVE = ["AAPL", "MSFT", "NVDA", "KO", "PG"]
# Symbol variants tried when a reserve symbol is absent verbatim (share-class dots).
SYMBOL_VARIANTS = {"BRK.B": ["BRK-B", "BRK_B", "BRKB"], "HONA": ["HON"], "BNY": ["BK"]}

# Death-era buckets (by last_date, ISO string compare). Post-window deaths fold
# into the final bucket (they fully reach the late regimes).
EARLY_ERAS = [("dotcom_2000_2003", "", "2003-12-31"),
              ("gfc_cycle_2004_2009", "2004-01-01", "2009-12-31"),
              ("post_2010", "2010-01-01", "9999-12-31")]
LATE_ERAS = [("y2011_2015", "", "2015-12-31"),
             ("y2016_2019", "2016-01-01", "2019-12-31"),
             ("y2020_plus", "2020-01-01", "9999-12-31")]

# FIX-1 fingerprint thresholds. adjc and c are rounded independently in the
# warehouse, so r = adjc/c carries ~1e-4 relative noise — validity is judged on
# SPIKES (one-bar excursions that revert = data errors), never on tiny wiggles,
# and steps in EITHER direction are legitimate (dividends/splits step r up over
# time; reverse splits step it down).
RATIO_EVENT_PCT = 0.01      # |delta r|/r above this = an adjustment event (step)
RATIO_REVERT_PCT = 0.005    # a step that reverts to within this of the prior
                            # level on the next bar = a spike (data error)

# FIX-10 tail requirement: the panel must hold >= 50 names with vol >= combined
# p75; the draw tops up (era x origin round-robin, delisted cells first) to
# TAIL_TARGET = 50 + a 5-name margin against FIX-1 attrition.
TAIL_TARGET = 55

# Name-level DATA-QUALITY gates (pre-registered; applied to every pool name
# BEFORE features enter the cutpoints, per the protocol's section-0 discipline:
# strip ARTIFACTUAL fineness with quality gates before it can set the grid).
# All four target warehouse junk verified live 2026-07-17:
DQ_SENTINEL_HI = 100000.0   # EODHD placeholder bars (c=999999.9999: 19,029 bars/30 names)
DQ_SENTINEL_LO = 0.005      # EODHD placeholder bars (c=0.0001 family: 94,265 bars/269 names)
DQ_PENNY_MEDIAN = 0.50      # median in-window RAW close below this = the "vol" is
                            # tick-quantization noise (a $0.02 stock moves 50%/tick)
DQ_JUMP_LOGRET = np.log(8)  # |daily log-return| beyond 8x
DQ_JUMP_MAX = 1             # ...allowed at most once (a real crash), >=2 = data junk
DQ_GAP_DAYS = 90            # internal hole > 90 calendar days (e.g. IPL's 2000->2003
                            # ticker-collision gap) = unusable for continuous backtests

DESIGN_DIR = Path(__file__).resolve().parent.parent / "docs" / "design"
PANEL_PATH = DESIGN_DIR / "calibration-v3-panel.json"
FRAME_PATH = DESIGN_DIR / "calibration-v3-frame-snapshot.json"
ALTSEED_PATH = DESIGN_DIR / "calibration-v3-panel-altseeds.json"
SUMMARY_PATH = DESIGN_DIR / "calibration-v3-panel-summary.md"


# --------------------------------------------------------------------------- #
# Warehouse access
# --------------------------------------------------------------------------- #

def connect(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def warehouse_fingerprint(con: sqlite3.Connection) -> dict:
    fp = {}
    fp["prices_rows"] = con.execute("SELECT COUNT(*) c FROM prices").fetchone()["c"]
    fp["prices_last_d"] = con.execute("SELECT MAX(d) m FROM prices").fetchone()["m"]
    fp["tickers_rows"] = con.execute("SELECT COUNT(*) c FROM tickers").fetchone()["c"]
    fp["fundamentals_rows"] = con.execute(
        "SELECT COUNT(*) c FROM asset_fundamentals").fetchone()["c"]
    fp["shares_quarterly_rows"] = con.execute(
        "SELECT COUNT(*) c FROM asset_shares_quarterly").fetchone()["c"]
    return fp


def inwindow_bar_counts(con: sqlite3.Connection) -> dict[int, int]:
    """One pass over prices: in-window bar count per ticker_id."""
    rows = con.execute(
        "SELECT ticker_id, COUNT(*) c FROM prices WHERE d BETWEEN ? AND ? "
        "GROUP BY ticker_id", (WINDOW_LO, WINDOW_HI)).fetchall()
    return {r["ticker_id"]: r["c"] for r in rows}


def total_bar_counts(con: sqlite3.Connection) -> dict[int, int]:
    rows = con.execute(
        "SELECT ticker_id, COUNT(*) c FROM prices GROUP BY ticker_id").fetchall()
    return {r["ticker_id"]: r["c"] for r in rows}


def fetch_bars(con: sqlite3.Connection, ticker_id: int):
    """In-window (d, c, adjc) arrays, ordered by d."""
    rows = con.execute(
        "SELECT d, c, adjc FROM prices WHERE ticker_id=? AND d BETWEEN ? AND ? "
        "ORDER BY d", (ticker_id, WINDOW_LO, WINDOW_HI)).fetchall()
    if not rows:
        return None
    d = np.array([r["d"] for r in rows], dtype=np.int64)
    c = np.array([r["c"] for r in rows], dtype=np.float64)
    adjc = np.array([r["adjc"] for r in rows], dtype=np.float64)
    return d, c, adjc


def realized_vol(adjc: np.ndarray) -> float | None:
    """Annualized stdev of daily log-returns on the adjusted close."""
    pos = adjc[adjc > 0]
    if len(pos) < 30:
        return None
    lr = np.diff(np.log(pos))
    if len(lr) < 20:
        return None
    return float(np.std(lr, ddof=1) * np.sqrt(TRADING_DAYS))


def shares_series(con: sqlite3.Connection, ticker_id: int):
    """(as_of_d_int[], shares[]) sorted ascending; zero/negative shares dropped."""
    rows = con.execute(
        "SELECT date, shares FROM asset_shares_quarterly WHERE ticker_id=? "
        "AND shares > 0 ORDER BY date", (ticker_id,)).fetchall()
    if not rows:
        return None
    d = np.array([int(str(r["date"]).replace("-", "")[:8]) for r in rows],
                 dtype=np.int64)
    s = np.array([float(r["shares"]) for r in rows], dtype=np.float64)
    return d, s


def data_quality(bars) -> str | None:
    """Pre-registered name-level junk gates. Returns an exclusion reason or None.

    Verified warehouse pathologies these target: EODHD sentinel bars
    (999999.9999 / 0.0001), tick-quantization "vol" on sub-penny names,
    ticker-collision series with multi-year holes (IPL), and multi-8x
    jump-and-revert data errors. Removing them strips ARTIFACTUAL fineness
    from the vol feature before it can set cutpoints (protocol section 0).
    """
    d, c, adjc = bars
    if np.any((c >= DQ_SENTINEL_HI) | ((c > 0) & (c <= DQ_SENTINEL_LO))):
        return "sentinel_bars"
    if np.any(c <= 0):
        return "nonpositive_raw_close"
    if np.any(adjc <= 0):
        return "nonpositive_adjusted_close"
    if float(np.median(c)) < DQ_PENNY_MEDIAN:
        return "penny_median_raw_close"
    lr = np.abs(np.diff(np.log(adjc)))
    if int(np.sum(lr > DQ_JUMP_LOGRET)) > DQ_JUMP_MAX:
        return "extreme_jump_bars"
    dates = np.array([f"{x//10000:04d}-{x//100%100:02d}-{x%100:02d}" for x in d],
                     dtype="datetime64[D]")
    if len(dates) > 1 and int(np.max(np.diff(dates)).astype(int)) > DQ_GAP_DAYS:
        return "price_gap_gt_90d"
    return None


def median_cap(bars, shares) -> float | None:
    """Median in-window market cap: ADJUSTED close x forward-filled shares.

    The warehouse shares series is retroactively SPLIT-ADJUSTED to the current
    basis (verified: AAPL shows ~17B flat through the 2020 4:1 split), so raw
    close x shares double-counts splits; adjc x current-basis shares cancels
    the split factors. Residual known bias: adjc also folds in dividends, so
    early-period caps skew low by the cumulative yield — acceptable for
    TERTILE bucketing (documented in the manifest).
    """
    if bars is None or shares is None:
        return None
    d, _, adjc = bars
    sd, sv = shares
    idx = np.searchsorted(sd, d, side="right") - 1   # last shares row at/before d
    known = idx >= 0
    if known.sum() < 60:  # need some real overlap to call it a cap
        return None
    cap = adjc[known] * sv[idx[known]]
    cap = cap[cap > 0]
    if len(cap) == 0:
        return None
    return float(np.median(cap))


def fingerprint(bars) -> dict:
    """FIX-1 adjustment-validity fingerprint on in-window bars.

    r = adjc/c must be finite on positive raw closes, and piecewise-CONSTANT
    between adjustment events: steps (either direction — dividends/splits step
    up over time, reverse splits step down) are legitimate; a one-bar excursion
    that reverts is a SPIKE = data error = invalid. Sub-1% wiggles are rounding
    noise (adjc and c are rounded independently) and ignored.
    """
    d, c, adjc = bars
    out = {"bars": int(len(d))}
    if np.any(c <= 0):
        out["valid"] = False
        out["reason"] = f"nonpositive_raw_close({int(np.sum(c <= 0))} bars)"
        return out
    r = adjc / c
    if not np.all(np.isfinite(r)):
        out["valid"] = False
        out["reason"] = "nonfinite_adjustment_ratio"
        return out
    dr = np.diff(r)
    rel = dr / np.maximum(r[:-1], 1e-12)
    events = np.abs(rel) > RATIO_EVENT_PCT
    # Spike: an event at bar i whose level reverts to ~the pre-event level at
    # bar i+1 (i.e. the next relative move is ~equal and opposite).
    spikes = 0
    idx = np.flatnonzero(events)
    for i in idx:
        if i + 1 < len(rel):
            back = (r[i + 2] - r[i]) / max(abs(r[i]), 1e-12)
            if abs(back) < RATIO_REVERT_PCT and abs(rel[i + 1]) > RATIO_EVENT_PCT:
                spikes += 1
    out["ratio_min"] = float(np.min(r))
    out["ratio_max"] = float(np.max(r))
    out["ratio_jumps"] = int(events.sum())
    out["ratio_jumps_down"] = int(np.sum(rel < -RATIO_EVENT_PCT))
    out["ratio_spikes"] = spikes
    out["any_adjustment"] = bool(np.any(np.abs(r - 1.0) > RATIO_EVENT_PCT))
    out["valid"] = spikes == 0
    if not out["valid"]:
        out["reason"] = f"ratio_spikes({spikes})"
    return out


# --------------------------------------------------------------------------- #
# Pool construction
# --------------------------------------------------------------------------- #

def canonical_sector(raw) -> str | None:
    if raw is None:
        return None
    return SECTOR_MAP.get(str(raw).strip())


def build_pools(con: sqlite3.Connection, counts_iw: dict, counts_tot: dict) -> dict:
    """Return {'living': [...], 'early': [...], 'late': [...]} of feature dicts."""
    share_ids = {r["ticker_id"] for r in con.execute(
        "SELECT DISTINCT ticker_id FROM asset_shares_quarterly")}
    sectors = {r["ticker_id"]: canonical_sector(r["sector"]) for r in con.execute(
        "SELECT ticker_id, sector FROM asset_fundamentals")}

    tickers = con.execute(
        "SELECT ticker_id, symbol, name, delisted, fetch_state, first_date, last_date "
        "FROM tickers WHERE fetch_state='done' AND instr(symbol,'_old')=0").fetchall()

    living, early, late = [], [], []
    for t in tickers:
        tid = t["ticker_id"]
        iw = counts_iw.get(tid, 0)
        base = {
            "ticker_id": tid, "symbol": t["symbol"], "name": t["name"],
            "sector": sectors.get(tid), "first_date": t["first_date"],
            "last_date": t["last_date"], "bars_inwindow": iw,
            "bars_total": counts_tot.get(tid, 0),
        }
        if t["delisted"] == 0:
            if (base["sector"] is not None and tid in share_ids
                    and iw >= LIVING_MIN_BARS):
                living.append(base)
        else:
            is_late = (t["last_date"] is not None
                       and str(t["last_date"]) >= LATE_MIN_LAST
                       and iw >= LATE_MIN_BARS)
            is_early = (t["first_date"] is not None
                        and str(t["first_date"]) <= EARLY_VINTAGE_MAX_FIRST
                        and iw >= EARLY_MIN_BARS)
            # Overlap rule (deterministic, recorded): a name qualifying for both
            # sleeves goes to LATE — non-survivors reaching the late regimes are
            # the scarce resource the late sleeve exists for (FIX-4).
            if is_late:
                late.append(base)
            elif is_early:
                early.append(base)
    return {"living": living, "early": early, "late": late}


def literal_pool_reconciliation(con: sqlite3.Connection, counts_iw: dict,
                                counts_tot: dict) -> dict:
    """Reproduce the PROTOCOL-LITERAL pool definitions (no overlap dedup; early
    uses TOTAL bar count as written in §2.2) so the committed reference counts
    (living 2142 / early 4684 / late 4179) are auditable next to the refined
    definitions this draw actually uses."""
    rows = con.execute(
        "SELECT ticker_id, first_date, last_date FROM tickers "
        "WHERE fetch_state='done' AND delisted=1 AND instr(symbol,'_old')=0"
    ).fetchall()
    early_literal = early_inwindow = late_literal = overlap = 0
    for t in rows:
        tid = t["ticker_id"]
        e_lit = (t["first_date"] is not None
                 and str(t["first_date"]) <= EARLY_VINTAGE_MAX_FIRST
                 and counts_tot.get(tid, 0) >= EARLY_MIN_BARS)
        e_iw = (t["first_date"] is not None
                and str(t["first_date"]) <= EARLY_VINTAGE_MAX_FIRST
                and counts_iw.get(tid, 0) >= EARLY_MIN_BARS)
        l_lit = (t["last_date"] is not None
                 and str(t["last_date"]) >= LATE_MIN_LAST
                 and counts_iw.get(tid, 0) >= LATE_MIN_BARS)
        early_literal += e_lit
        early_inwindow += e_iw
        late_literal += l_lit
        overlap += e_iw and l_lit
    return {
        "reference_committed_2026_07_16": REFERENCE_COUNTS,
        "early_literal_total_bars_no_dedup": early_literal,
        "early_inwindow_bars_no_dedup": early_inwindow,
        "late_no_dedup": late_literal,
        "early_late_overlap_assigned_to_late": overlap,
        "note": ("draw uses in-window bar counts (usability) and assigns "
                 "early/late overlap to the late sleeve; the literal columns "
                 "exist to reproduce the committed reference counts"),
    }


def compute_features(con: sqlite3.Connection, pools: dict, log: list,
                     dq_stats: dict) -> None:
    """Data-quality-gate every name, then attach realized vol + median cap.

    Gated names leave the pools ENTIRELY (before cutpoints), with per-reason
    counts recorded in dq_stats and per-name entries in the log.
    """
    share_ids = {r["ticker_id"] for r in con.execute(
        "SELECT DISTINCT ticker_id FROM asset_shares_quarterly")}
    for pool_name, names in pools.items():
        kept = []
        for n in names:
            bars = fetch_bars(con, n["ticker_id"])
            if bars is None:
                log.append(f"exclude {n['symbol']} ({pool_name}): no in-window bars")
                continue
            reason = data_quality(bars)
            if reason is not None:
                dq_stats[reason] = dq_stats.get(reason, 0) + 1
                log.append(f"DQ exclude {n['symbol']} ({pool_name}): {reason}")
                continue
            vol = realized_vol(bars[2])
            if vol is None:
                log.append(f"exclude {n['symbol']} ({pool_name}): vol not computable")
                continue
            n["vol"] = round(vol, 6)
            cap = None
            if n["ticker_id"] in share_ids:
                cap = median_cap(bars, shares_series(con, n["ticker_id"]))
            n["median_pit_cap"] = round(cap, 2) if cap is not None else None
            kept.append(n)
        pools[pool_name] = kept


# --------------------------------------------------------------------------- #
# Cutpoints (FIX-5: combined pool) and bucketing
# --------------------------------------------------------------------------- #

def compute_cutpoints(pools: dict) -> dict:
    vols_living = np.array([n["vol"] for n in pools["living"]])
    vols_all = np.array([n["vol"] for p in pools.values() for n in p])
    caps_all = np.array([n["median_pit_cap"] for p in pools.values() for n in p
                         if n["median_pit_cap"] is not None])
    return {
        "vol_median_combined": round(float(np.median(vols_all)), 6),
        "vol_median_living_only": round(float(np.median(vols_living)), 6),
        "vol_p75_combined": round(float(np.percentile(vols_all, 75)), 6),
        "cap_tertiles_combined": [round(float(np.percentile(caps_all, q)), 2)
                                  for q in (100 / 3, 200 / 3)],
        "n_vol_combined": int(len(vols_all)),
        "n_cap_combined": int(len(caps_all)),
    }


def cap_bucket(cap: float, tertiles: list) -> str:
    if cap <= tertiles[0]:
        return "small"
    if cap <= tertiles[1]:
        return "mid"
    return "large_liquid"


def vol_bucket(vol: float, median: float) -> str:
    return "high" if vol >= median else "low"


def era_bucket(last_date: str, eras: list) -> str:
    ld = str(last_date)
    for name, lo, hi in eras:
        if lo <= ld <= hi:
            return name
    return eras[-1][0]


# --------------------------------------------------------------------------- #
# Deterministic draw
# --------------------------------------------------------------------------- #

def largest_remainder(weights: dict, total: int, tie_reverse: bool = False) -> dict:
    """Integer quotas proportional to weights summing to total (deterministic:
    ties broken by key sort; tie_reverse=True prefers the LAST keys — used for
    delisted era cells so the extra name lands in the most-recent era, the
    scarce late-regime resource, FIX-4)."""
    wsum = sum(weights.values())
    if wsum <= 0:
        return {k: 0 for k in weights}
    raw = {k: total * w / wsum for k, w in weights.items()}
    base = {k: int(np.floor(v)) for k, v in raw.items()}
    left = total - sum(base.values())
    order = sorted(weights, key=lambda k: (-(raw[k] - base[k]),
                                           _revkey(k) if tie_reverse else k))
    for k in order[:left]:
        base[k] += 1
    return base


def _revkey(k: str):
    """Sort key that inverts lexicographic order for strings."""
    return tuple(-ord(ch) for ch in k)


def draw_living_cell(cell_names: list, quota: int, rng, flags: list,
                     cell_key: str) -> list:
    """Sector largest-remainder + soft >=6-sector floor inside one cap x vol cell."""
    by_sector: dict[str, list] = {}
    for n in sorted(cell_names, key=lambda x: x["ticker_id"]):
        by_sector.setdefault(n["sector"], []).append(n)
    weights = {s: len(v) for s, v in by_sector.items()}
    quotas = largest_remainder(weights, quota)

    # Soft sector floor: promote unrepresented sectors (largest eligible first),
    # demoting from the currently-largest allocation (>1). Deterministic.
    def distinct():
        return sum(1 for q in quotas.values() if q > 0)
    while distinct() < min(SECTOR_SOFT_FLOOR, len(by_sector)):
        zero = [s for s, q in quotas.items() if q == 0 and weights[s] > 0]
        if not zero:
            break
        promote = sorted(zero, key=lambda s: (-weights[s], s))[0]
        donors = [s for s, q in quotas.items() if q > 1]
        if not donors:
            break
        demote = sorted(donors, key=lambda s: (-quotas[s], s))[0]
        quotas[promote] += 1
        quotas[demote] -= 1

    drawn = []
    for s in sorted(quotas):
        q = min(quotas[s], len(by_sector.get(s, [])))
        if len(by_sector.get(s, [])) < 4:
            flags.append(f"thin sector corner {cell_key}/{s}: "
                         f"{len(by_sector.get(s, []))} eligible")
        if q == 0:
            continue
        perm = rng.permutation(len(by_sector[s]))
        picked = [by_sector[s][i] for i in perm[:q]]
        # remainder of the permutation = deterministic replacement order (FIX-1)
        rest = [by_sector[s][i] for i in perm[q:]]
        for p in picked:
            p["_replacements"] = rest
        drawn.extend(picked)
    return drawn


def draw_delisted_sleeve(names: list, quota: int, eras: list, vol_median: float,
                         rng, flags: list, sleeve: str) -> list:
    """Era x vol stratification, equal-target largest-remainder."""
    cells: dict[str, list] = {}
    for n in sorted(names, key=lambda x: x["ticker_id"]):
        key = f"{era_bucket(n['last_date'], eras)}|{vol_bucket(n['vol'], vol_median)}"
        cells.setdefault(key, []).append(n)
    # Equal target per non-empty cell, capped by availability; redistribute.
    # tie_reverse: the 33/6=5.5 remainder seats go to the most-RECENT eras.
    quotas = largest_remainder({k: 1 for k in cells}, quota, tie_reverse=True)
    for _ in range(10):  # cap-and-redistribute to convergence
        over = {k: quotas[k] - len(cells[k]) for k in quotas
                if quotas[k] > len(cells[k])}
        if not over:
            break
        spare = sum(over.values())
        for k in over:
            quotas[k] = len(cells[k])
        room = {k: len(cells[k]) - quotas[k] for k in quotas
                if len(cells[k]) > quotas[k]}
        if not room:
            flags.append(f"{sleeve}: could not place {spare} names (pool too thin)")
            break
        add = largest_remainder(room, min(spare, sum(room.values())),
                                tie_reverse=True)
        for k, a in add.items():
            quotas[k] += a
    drawn = []
    for k in sorted(quotas):
        q = quotas[k]
        if q == 0:
            continue
        perm = rng.permutation(len(cells[k]))
        picked = [cells[k][i] for i in perm[:q]]
        rest = [cells[k][i] for i in perm[q:]]
        for p in picked:
            p["_replacements"] = rest
        drawn.extend(picked)
    if len(drawn) < quota:
        flags.append(f"{sleeve}: drew only {len(drawn)}/{quota}")
    return drawn


def draw_panel(pools: dict, cutpoints: dict, reserve_ids: set, seed: int,
               flags: list | None = None) -> dict:
    """Full deterministic draw for one seed. Returns {living, early, late}."""
    flags = flags if flags is not None else []
    rng = np.random.default_rng(seed)
    vmed = cutpoints["vol_median_combined"]
    tert = cutpoints["cap_tertiles_combined"]

    eligible_living = [n for n in pools["living"]
                       if n["ticker_id"] not in reserve_ids
                       and n["median_pit_cap"] is not None]
    cells: dict[str, list] = {}
    for n in eligible_living:
        key = f"{cap_bucket(n['median_pit_cap'], tert)}|{vol_bucket(n['vol'], vmed)}"
        n["cell"] = key
        cells.setdefault(key, []).append(n)

    living = []
    for key in sorted(cells):  # fixed stratum order
        got = draw_living_cell(cells[key], LIVING_QUOTA_PER_CELL, rng, flags, key)
        if len(got) < LIVING_QUOTA_PER_CELL:
            flags.append(f"living cell {key}: only {len(got)}/{LIVING_QUOTA_PER_CELL}")
        living.extend(got)

    early = draw_delisted_sleeve(pools["early"], DELISTED_EARLY_QUOTA, EARLY_ERAS,
                                 vmed, rng, flags, "early-death sleeve")
    late = draw_delisted_sleeve(pools["late"], DELISTED_LATE_QUOTA, LATE_ERAS,
                                vmed, rng, flags, "late-death sleeve")
    return {"living": living, "early": early, "late": late}


def topup_tail(pools: dict, drawn: dict, cutpoints: dict, reserve_ids: set,
               seed: int, flags: list) -> list:
    """FIX-10 pre-committed response: if the drawn panel holds fewer than
    TAIL_TARGET names with vol >= combined p75, top up deterministically from
    the not-yet-drawn tail — delisted names first (the finest-JND tail per the
    protocol), then living. Era-balanced via round-robin on a seeded
    permutation. Returns the top-up list (sleeve 'tail_topup')."""
    p75 = cutpoints["vol_p75_combined"]
    have = {n["symbol"] for names in drawn.values() for n in names}
    tail_now = sum(1 for names in drawn.values() for n in names
                   if n["vol"] >= p75)
    need = TAIL_TARGET - tail_now
    if need <= 0:
        return []
    rng = np.random.default_rng(seed ^ 0x7A11)  # documented top-up substream
    # Era x origin round-robin, delisted cells first then living, so the
    # top-up cannot concentrate in one death-era clique (the tail governs
    # Q=0.85, so its temporal diversity is load-bearing).
    cell_defs = ([("early", era) for era, _, _ in EARLY_ERAS]
                 + [("late", era) for era, _, _ in LATE_ERAS]
                 + [("living", None)])
    queues = {}
    for source, era in cell_defs:
        eras = {"early": EARLY_ERAS, "late": LATE_ERAS}.get(source)
        cands = [n for n in sorted(pools[source], key=lambda x: x["ticker_id"])
                 if n["vol"] >= p75 and n["symbol"] not in have
                 and n["ticker_id"] not in reserve_ids
                 and (era is None or era_bucket(n["last_date"], eras) == era)]
        queues[(source, era)] = [cands[i] for i in rng.permutation(len(cands))]
    picked = []
    while len(picked) < need and any(queues.values()):
        for key in cell_defs:
            if len(picked) >= need:
                break
            while queues[key] and queues[key][0]["symbol"] in have:
                queues[key].pop(0)
            if queues[key]:
                n = dict(queues[key].pop(0))
                n["topup_origin"] = key[0]
                n["_replacements"] = []
                picked.append(n)
                have.add(n["symbol"])
    if len(picked) < need:
        flags.append(f"FIX-10: tail top-up exhausted the pools, still "
                     f"{need - len(picked)} short of TAIL_TARGET={TAIL_TARGET}")
    return picked


def apply_fix1_guard(con: sqlite3.Connection, drawn: dict, log: list) -> None:
    """Fingerprint every drawn name; replace guard failures deterministically."""
    for sleeve, names in drawn.items():
        i = 0
        while i < len(names):
            n = names[i]
            fp = fingerprint(fetch_bars(con, n["ticker_id"]))
            if fp.pop("valid"):
                n["adjustment_fingerprint"] = fp
                n.pop("_replacements", None)
                i += 1
                continue
            log.append(f"FIX-1 exclude {n['symbol']} ({sleeve}): {fp.get('reason')}")
            repl = [r for r in n.get("_replacements", [])
                    if r["symbol"] not in {m["symbol"] for m in names}]
            if repl:
                sub = repl[0]
                sub["_replacements"] = repl[1:]
                sub["cell"] = n.get("cell")
                names[i] = sub
                log.append(f"FIX-1 replace -> {sub['symbol']}")
            else:
                log.append(f"FIX-1 no replacement available in stratum for "
                           f"{n['symbol']} — slot dropped")
                names.pop(i)


# --------------------------------------------------------------------------- #
# Reserve (FIX-37)
# --------------------------------------------------------------------------- #

def resolve_reserve(con: sqlite3.Connection) -> tuple[list, set, list]:
    want = sorted(set(SP100_AS_FETCHED) | set(LEGACY_RESERVE))
    found, missing = [], []
    for sym in want:
        cands = [sym] + SYMBOL_VARIANTS.get(sym, [])
        row = None
        for cand in cands:
            row = con.execute(
                "SELECT ticker_id, symbol FROM tickers WHERE symbol=? "
                "AND fetch_state='done' AND delisted=0", (cand,)).fetchone()
            if row:
                break
        if row:
            found.append({"requested": sym, "symbol": row["symbol"],
                          "ticker_id": row["ticker_id"]})
        else:
            missing.append(sym)
    return found, {f["ticker_id"] for f in found}, missing


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #

def sha256_of(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def panel_entry(n: dict, sleeve: str) -> dict:
    origin = n.get("topup_origin", sleeve)
    delisted_eras = {"early": EARLY_ERAS, "late": LATE_ERAS}
    return {
        "ticker_id": n["ticker_id"], "symbol": n["symbol"], "name": n["name"],
        "sector": n.get("sector"), "cap_bucket": (n.get("cell") or "|").split("|")[0]
        if origin == "living" else None,
        "vol_bucket": (n.get("cell") or "|").split("|")[1]
        if origin == "living" else None,
        "vol": n["vol"], "median_pit_cap": n.get("median_pit_cap"),
        "alive_flag": origin == "living",
        "era": era_bucket(n["last_date"], delisted_eras[origin])
        if origin in delisted_eras else None,
        "sleeve": sleeve, "topup_origin": n.get("topup_origin"),
        "first_date": n["first_date"], "last_date": n["last_date"],
        "bars_inwindow": n["bars_inwindow"],
        "adjustment_fingerprint": n.get("adjustment_fingerprint"),
    }


def write_outputs(pools, cutpoints, panel_list, alt_panels, reserve,
                  reserve_missing, wh_fp, flags, log, args, recon,
                  dq_stats) -> dict:
    panel_hash = sha256_of(panel_list)
    sleeve_sizes: dict[str, int] = {}
    for e in panel_list:
        sleeve_sizes[e["sleeve"]] = sleeve_sizes.get(e["sleeve"], 0) + 1

    frame = {
        "window": [WINDOW_LO, WINDOW_HI],
        "pools": {k: sorted(
            [{kk: n[kk] for kk in ("ticker_id", "symbol", "sector", "vol",
                                   "median_pit_cap", "first_date", "last_date",
                                   "bars_inwindow")} for n in v],
            key=lambda e: e["ticker_id"]) for k, v in pools.items()},
        "pool_counts": {k: len(v) for k, v in pools.items()},
        "reference_counts": REFERENCE_COUNTS,
        "warehouse_fingerprint": wh_fp,
    }
    frame_hash = sha256_of(frame)

    p75 = cutpoints["vol_p75_combined"]  # single frozen value, no re-derivation
    tail_count = sum(1 for e in panel_list if e["vol"] >= p75)

    manifest = {
        "protocol": "COVERAGE-CALIBRATION-V3-PROTOCOL.md",
        "grid_version_target": "v3",
        "seed": PRIMARY_SEED,
        "seeds_K": SEEDS_K,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "cutpoints": cutpoints,
        "tail_requirement": {"min_names": TAIL_MIN_NAMES, "vol_p75_combined": p75,
                             "panel_tail_count": tail_count,
                             "pass": tail_count >= TAIL_MIN_NAMES},
        "frame_snapshot_sha256": frame_hash,
        "panel_sha256": panel_hash,
        "panel_size": {**sleeve_sizes, "total": len(panel_list)},
        "pool_reconciliation": recon,
        "reserve": {"as_fetched_date": "2026-07-17",
                    "wikipedia_component_list_date": "2025-09-22",
                    "resolved": reserve, "not_in_warehouse": reserve_missing},
        "overlap_rule": "delisted qualifying for both sleeves -> late (FIX-4)",
        "early_min_bars_note": ("protocol text says COUNT(prices)>=250 without a "
                                "window; implemented as IN-WINDOW >=250 (usability); "
                                "both counts reported in reconciliation"),
        "early_sleeve_note": ("the early sleeve can contain post-2010 deaths that "
                              "failed the late sleeve's 750-in-window-bar gate; "
                              "the era column records the true death era"),
        "cap_basis_note": ("median cap = adjc x current-basis (retroactively "
                           "split-adjusted) shares; raw close would double-count "
                           "splits (verified on AAPL 2020 4:1); residual known "
                           "bias: dividend adjustment skews early-period caps low"),
        "data_quality_gates": {"sentinel_hi": DQ_SENTINEL_HI,
                               "sentinel_lo": DQ_SENTINEL_LO,
                               "penny_median_raw_close": DQ_PENNY_MEDIAN,
                               "jump_logret": round(float(DQ_JUMP_LOGRET), 6),
                               "jump_max_allowed": DQ_JUMP_MAX,
                               "gap_days": DQ_GAP_DAYS,
                               "excluded_by_reason": dq_stats},
        "fix1_fingerprint_rule": {
            "interpretation": ("piecewise-CONSTANT-with-steps (steps either "
                               "direction are legit adjustments; a >1% one-bar "
                               "excursion reverting within 0.5% = spike = invalid); "
                               "the protocol's literal piecewise-monotone check "
                               "false-fails on ~1e-4 rounding noise between the "
                               "independently-rounded adjc and c columns and on "
                               "reverse splits"),
            "event_pct": RATIO_EVENT_PCT, "revert_pct": RATIO_REVERT_PCT,
            "known_limits": ("multi-bar/first-bar/last-bar spikes are not "
                             "detected here; the extreme-jump data-quality gate "
                             "covers the multi-bar case")},
        "tail_topup_rule": {"target": TAIL_TARGET,
                            "requirement_min": TAIL_MIN_NAMES,
                            "margin_rationale": "+5 against FIX-1 attrition",
                            "substream": "numpy default_rng(seed ^ 0x7A11)",
                            "order": ("era x origin round-robin, delisted cells "
                                      "(early eras, late eras) first, living last"),
                            "retopup_loop_max": 3},
        "flags": flags,
        "exclusion_log": log,
        "panel": panel_list,
    }
    manifest["altseeds_sha256"] = sha256_of(alt_panels)
    # Freeze hash seals EVERYTHING except itself and the generation timestamp.
    manifest["freeze_sha256"] = sha256_of(
        {k: v for k, v in manifest.items()
         if k not in ("freeze_sha256", "generated_utc")})

    DESIGN_DIR.mkdir(parents=True, exist_ok=True)
    if args.rebuild:
        if not PANEL_PATH.exists():
            print("FATAL: --rebuild but no committed panel exists")
            sys.exit(2)
        committed = json.loads(PANEL_PATH.read_text())
        ok = committed.get("freeze_sha256") == manifest["freeze_sha256"]
        if not ok:
            print("FATAL: --rebuild freeze-hash mismatch: committed "
                  f"{committed.get('freeze_sha256', '?')[:16]} vs "
                  f"{manifest['freeze_sha256'][:16]}")
            sys.exit(2)
        print(f"--rebuild OK: freeze hash matches "
              f"({manifest['freeze_sha256'][:16]}...)")
        return manifest
    if PANEL_PATH.exists() and not args.force_redraw:
        print("REFUSED: a frozen panel already exists (write-once, FIX-32). "
              "Use --rebuild to verify it or --force-redraw to replace it "
              "(pre-registration event — record why).")
        sys.exit(3)

    PANEL_PATH.write_text(json.dumps(manifest, indent=1))
    FRAME_PATH.write_text(json.dumps(frame, indent=1))
    ALTSEED_PATH.write_text(json.dumps(alt_panels, indent=1))
    return manifest


def write_summary(manifest, pools, cutpoints):
    m = manifest
    rc = REFERENCE_COUNTS
    recon = m["pool_reconciliation"]
    pc = {k: len(v) for k, v in pools.items()}
    ok = ("✓" if recon["early_literal_total_bars_no_dedup"] == rc["early_delisted"]
          else "✗")
    lines = ["# Calibration V3 — Frozen Panel (eyeball summary)", "",
             f"Generated {m['generated_utc']} · seed {m['seed']} · "
             f"freeze sha256 `{m['freeze_sha256'][:16]}…`", "",
             "## Pool reconciliation", "",
             "The protocol's committed reference counts reproduce under the "
             "LITERAL definitions; the draw then uses documented refinements "
             "(in-window bars, early/late overlap→late, data-quality gates, "
             "reserve exclusion), giving the smaller draw pools.", "",
             "| pool | protocol (literal) | reproduced (literal) | draw pool |",
             "|---|---|---|---|",
             f"| living | {rc['living']} | {rc['living']} ✓ | {pc['living']} "
             f"(−reserve −DQ) |",
             f"| early-death delisted | {rc['early_delisted']} | "
             f"{recon['early_literal_total_bars_no_dedup']} {ok} | {pc['early']} "
             f"(in-window, −overlap {recon['early_late_overlap_assigned_to_late']}"
             f", −DQ) |",
             f"| late-death delisted | {rc['late_delisted']} | "
             f"{recon['late_no_dedup']} ✓ | {pc['late']} (−DQ) |", ""]
    dq = m["data_quality_gates"]["excluded_by_reason"]
    lines += ["## Data-quality gates (pre-registered, applied before cutpoints)",
              "",
              f"Excluded names by reason: {json.dumps(dq)} — sentinel bars, "
              f"sub-penny tick-noise, ≥2 extreme (>8×) jumps, >90-day internal "
              f"holes. These strip ARTIFACTUAL vol before it can set the grid.",
              ""]
    cp = cutpoints
    lines += ["## Frozen cutpoints (FIX-5: combined draw pool, reserve-disjoint)",
              "",
              f"- vol median combined **{cp['vol_median_combined']}** "
              f"(living-only {cp['vol_median_living_only']}; protocol's earlier "
              f"live-verified figure was ~0.576 on the literal, un-gated, "
              f"reserve-included pool — drift is explained by the documented "
              f"refinements and is refrozen here per §2.3)",
              f"- vol p75 combined {cp['vol_p75_combined']} · tail names in panel: "
              f"**{m['tail_requirement']['panel_tail_count']}** "
              f"(requirement ≥{TAIL_MIN_NAMES}: "
              f"{'PASS' if m['tail_requirement']['pass'] else 'FAIL'})",
              f"- cap tertiles combined: ${cp['cap_tertiles_combined'][0]:,.0f} / "
              f"${cp['cap_tertiles_combined'][1]:,.0f} (adjc-basis, see "
              f"cap_basis_note; protocol's earlier figures ~$0.38B/$2.68B used "
              f"the split-double-counting raw-close basis)", ""]
    lines += ["## Panel composition", "",
              " · ".join(f"{k} {v}" for k, v in m["panel_size"].items()), ""]
    # per-cell living table
    cells: dict[str, list] = {}
    sleeves: dict[str, list] = {"early": [], "late": [], "tail_topup": []}
    for e in m["panel"]:
        if e["sleeve"] == "living":
            cells.setdefault(f"{e['cap_bucket']}|{e['vol_bucket']}", []).append(e)
        else:
            sleeves.setdefault(e["sleeve"], []).append(e)
    lines += ["### Living cells (cap × vol)", "",
              "| cell | n | sectors | example names |", "|---|---|---|---|"]
    for k in sorted(cells):
        es = cells[k]
        secs = len({e["sector"] for e in es})
        ex = ", ".join(e["symbol"] for e in es[:6])
        lines.append(f"| {k} | {len(es)} | {secs} | {ex} … |")
    for sl, title in (("early", "Early-death sleeve"), ("late", "Late-death sleeve"),
                      ("tail_topup", "Tail top-up sleeve (FIX-10)")):
        if not sleeves.get(sl):
            continue
        lines += ["", f"### {title}", "", "| era | vol | symbols |", "|---|---|---|"]
        by: dict[str, list] = {}
        for e in sleeves[sl]:
            vb = "high" if e["vol"] >= cp["vol_median_combined"] else "low"
            by.setdefault(f"{e['era'] or 'living'}|{vb}", []).append(e["symbol"])
        for k in sorted(by):
            era, vb = k.split("|")
            lines.append(f"| {era} | {vb} | {', '.join(sorted(by[k]))} |")
    lines += ["", "## OOS reserve (FIX-37, excluded from the draw)", "",
              f"{len(m['reserve']['resolved'])} resolved; not in warehouse: "
              f"{', '.join(m['reserve']['not_in_warehouse']) or '—'}", ""]
    if m["flags"]:
        lines += ["## Flags", ""] + [f"- {f}" for f in m["flags"]] + [""]
    if m["exclusion_log"]:
        lines += ["## Exclusion / replacement log", ""] + \
                 [f"- {x}" for x in m["exclusion_log"]] + [""]
    lines += [f"## Full panel ({len(m['panel'])} rows)", "",
              "| # | symbol | sleeve | sector | cell/era | vol | cap ($M) | window |",
              "|---|---|---|---|---|---|---|---|"]
    for i, e in enumerate(sorted(m["panel"], key=lambda x: (x["sleeve"],
                                                            x["symbol"])), 1):
        cell = (f"{e['cap_bucket']}/{e['vol_bucket']}" if e["cap_bucket"]
                else e["era"] or "—")
        cap = f"{e['median_pit_cap'] / 1e6:,.0f}" if e["median_pit_cap"] else "—"
        lines.append(f"| {i} | {e['symbol']} | {e['sleeve']} | {e['sector'] or '—'} "
                     f"| {cell} | {e['vol']:.2f} | {cap} | "
                     f"{e['first_date']}→{e['last_date']} |")
    SUMMARY_PATH.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(Path(__file__).resolve().parent.parent.parent
                                        / "data" / "asset_prices.db"))
    ap.add_argument("--rebuild", action="store_true",
                    help="re-run the draw and assert the committed freeze hash")
    ap.add_argument("--force-redraw", action="store_true",
                    help="overwrite an existing frozen panel (records a "
                         "pre-registration event; use deliberately)")
    args = ap.parse_args()

    # Write-once (FIX-32 / AM-8): refuse a plain re-run up front, before any
    # compute — an existing frozen panel is only verified (--rebuild) or
    # deliberately replaced (--force-redraw).
    if PANEL_PATH.exists() and not args.rebuild and not args.force_redraw:
        print("REFUSED: a frozen panel already exists (write-once, FIX-32). "
              "Use --rebuild to verify it or --force-redraw to replace it "
              "(pre-registration event — record why).")
        sys.exit(3)

    con = connect(args.db)
    print("warehouse fingerprint...")
    wh_fp = warehouse_fingerprint(con)
    print("bar counts (one pass over 42.9M rows)...")
    counts_iw = inwindow_bar_counts(con)
    counts_tot = total_bar_counts(con)
    # FIX-35: fingerprint the in-window slice that actually determines the draw,
    # not just whole-table counts.
    wh_fp["prices_rows_inwindow"] = int(sum(counts_iw.values()))
    wh_fp["tickers_with_inwindow_bars"] = len(counts_iw)
    print("  ", wh_fp)

    print("building pools...")
    pools = build_pools(con, counts_iw, counts_tot)
    print({k: len(v) for k, v in pools.items()}, "(pre-feature counts)")

    # FIX-37: the OOS reserve leaves the living pool BEFORE features/cutpoints —
    # cutpoints are estimated on the disjoint remainder the draw sees.
    reserve, reserve_ids, reserve_missing = resolve_reserve(con)
    n_before = len(pools["living"])
    pools["living"] = [n for n in pools["living"]
                       if n["ticker_id"] not in reserve_ids]
    print(f"reserve resolved {len(reserve)} (removed "
          f"{n_before - len(pools['living'])} from living pool), "
          f"missing {reserve_missing}")

    log: list[str] = []
    dq_stats: dict[str, int] = {}
    print("computing features (DQ gates + vol + cap) for all pool names...")
    compute_features(con, pools, log, dq_stats)
    print({k: len(v) for k, v in pools.items()}, "(post-feature counts)")
    print("data-quality exclusions:", dq_stats)

    cutpoints = compute_cutpoints(pools)
    print("cutpoints:", cutpoints)

    recon = literal_pool_reconciliation(con, counts_iw, counts_tot)
    print("pool reconciliation:", recon)

    flags: list[str] = []
    drawn = draw_panel(pools, cutpoints, reserve_ids, PRIMARY_SEED, flags)
    print("applying FIX-1 adjustment guard to drawn names...")
    apply_fix1_guard(con, drawn, log)

    print("tail top-up (FIX-10)...")
    drawn["tail_topup"] = []
    for _ in range(3):  # re-top-up if the FIX-1 guard drops a top-up name
        topup = topup_tail(pools, drawn, cutpoints, reserve_ids, PRIMARY_SEED,
                           flags)
        if not topup:
            break
        apply_fix1_guard(con, {"tail_topup": topup}, log)
        drawn["tail_topup"].extend(topup)
    if not drawn["tail_topup"]:
        del drawn["tail_topup"]

    # FIX-37 assertion: large_liquid|low cell still fills after reserve removal.
    ll = [n for n in drawn["living"] if n.get("cell") == "large_liquid|low"]
    if len(ll) < LIVING_QUOTA_PER_CELL:
        flags.append(f"FIX-37 WARNING: large_liquid|low filled only {len(ll)}/22 "
                     "after reserve exclusion")

    # Snapshot the primary panel BEFORE the alt-seed draws (they touch the same
    # pool dicts; the panel serialization must not depend on later draws).
    panel_list = [panel_entry(n, sleeve) for sleeve, names in drawn.items()
                  for n in names]
    panel_list.sort(key=lambda e: e["ticker_id"])

    print("drawing alternate-seed panels (FIX-11), FIX-1-guarded like the "
          "primary...")
    alt_panels = {}
    for s in SEEDS_K[1:]:
        alt = draw_panel(pools, cutpoints, reserve_ids, s, [])
        alt_log: list[str] = []
        apply_fix1_guard(con, alt, alt_log)
        alt["tail_topup"] = []
        for _ in range(3):
            t = topup_tail(pools, alt, cutpoints, reserve_ids, s, [])
            if not t:
                break
            apply_fix1_guard(con, {"tail_topup": t}, alt_log)
            alt["tail_topup"].extend(t)
        if not alt["tail_topup"]:
            del alt["tail_topup"]
        alt_panels[str(s)] = {
            **{k: sorted(n["symbol"] for n in v) for k, v in alt.items()},
            "_fix1_exclusions": sum(1 for x in alt_log if "exclude" in x),
        }

    manifest = write_outputs(pools, cutpoints, panel_list, alt_panels, reserve,
                             reserve_missing, wh_fp, flags, log, args, recon,
                             dq_stats)
    if not args.rebuild:
        write_summary(manifest, pools, cutpoints)
        print(f"\nwrote {PANEL_PATH.name}, {FRAME_PATH.name}, {ALTSEED_PATH.name}, "
              f"{SUMMARY_PATH.name}")
    print(f"panel: {manifest['panel_size']} · tail "
          f"{manifest['tail_requirement']['panel_tail_count']} "
          f"(pass={manifest['tail_requirement']['pass']}) · "
          f"hash {manifest['panel_sha256'][:16]}...")
    if flags:
        print("FLAGS:")
        for f in flags:
            print("  -", f)


if __name__ == "__main__":
    main()
