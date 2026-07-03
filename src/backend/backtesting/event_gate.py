"""ATS-2080 — Backtest event-gate consumer.

Pulls ``event_gate_decisions`` rows for a (symbol, date_range) window
into a flat ``pandas.DataFrame`` that the strategy can consult per bar
without round-tripping to the DB on each decision.

Design notes
------------

* **Pre-load model.** The :class:`~src.backend.backtesting.engine.runner`
  fetches every active gate for the backtest window *before* iterating
  bars. ATS-2080 §Risks: "Gate-Lookup pro Bar kann teuer sein bei vielen
  Events. Mitigation: pre-load alle Gates für (asset, date_range) am
  Start des Backtests in Memory." This module is that mitigation.
* **Available-at honoured.** A gate is only active from
  ``max(available_at, event_date - window_before_days)``. This enforces
  the Look-ahead-Bias guard from ATS-2002 / V3.2 §K5: we never gate a
  trade that happened before the market plausibly knew about the event.
* **Strictest-wins overlap.** When multiple gates are active on the same
  bar for the same asset, BLOCK beats REDUCE beats NO_GATE; within an
  action class, the higher ``risk_severity`` wins. Mirrors
  :func:`src.backend.event_context.gate.aggregate_overlapping_gates`
  semantics but stays in pure-pandas land so the backtest path has no
  async dependency.
* **No DB writes.** This module is read-only. The GateDeriver (ATS-2042)
  is the only writer for ``event_gate_decisions``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pandas as pd
from sqlalchemy import select

if TYPE_CHECKING:  # pragma: no cover -- typing only
    from src.backend.event_context import EventDBClient

logger = logging.getLogger(__name__)


# Strictness ordering — strictest first. Mirrors gate.aggregate_overlapping_gates.
_ACTION_STRICTNESS: dict[str, int] = {
    "BLOCK_NEW_ENTRIES": 2,
    "REDUCE_POSITION_SIZE": 1,
    "NO_GATE": 0,
}


@dataclass
class AppliedGate:
    """One gate that was active on a decision bar and is being applied.

    Returned from :func:`apply_gate_at_decision` so the strategy can
    persist the decision in its blocked/reduced log for the result.
    """

    event_id: str
    gate_action: str
    multiplier: float
    reason: str
    risk_severity: float = 0.0


def _extract_importance(specifics_json: str | None) -> float:
    """Mirror of :meth:`GateDeriver._extract_importance` for the backtest path.

    Pulls ``importance`` from a v1/v2 ``specifics_json`` blob. Any parse
    error returns ``1.0`` — never silently downgrade a gate.
    """
    if not specifics_json:
        return 1.0
    try:
        data = json.loads(specifics_json)
    except (json.JSONDecodeError, TypeError, ValueError):
        return 1.0
    if isinstance(data, dict):
        inner = data.get("specifics")
        if isinstance(inner, dict) and "importance" in inner:
            try:
                return float(inner["importance"])
            except (TypeError, ValueError):
                return 1.0
        if "importance" in data:
            try:
                return float(data["importance"])
            except (TypeError, ValueError):
                return 1.0
    return 1.0


async def load_gates_for_backtest(
    db_client: "EventDBClient",
    asset_symbol: str,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """Pre-load every gate that could be active for the backtest window.

    Returns a DataFrame with one row per persisted ``event_gate_decisions``
    entry where the underlying event's ``time_start_utc.date()`` falls
    within ``[start_date - max_window, end_date + max_window]`` (so
    bars near the boundaries still see overlapping gates) and the
    ``asset.symbol`` matches *asset_symbol*. Columns:

        * ``event_id``
        * ``event_date`` — ``time_start_utc.date()``
        * ``available_at_date`` — ``available_at.date()`` or ``None``
        * ``gate_action``
        * ``multiplier`` — ``position_size_multiplier``
        * ``window_before_days``
        * ``window_after_days``
        * ``risk_severity``
        * ``reason_text``
        * ``event_importance`` — extracted from ``specifics_json``

    An empty DataFrame is returned when no gates match (still has all
    columns so downstream code can rely on them).

    Args:
        db_client: an :class:`EventDBClient` with an active async session.
        asset_symbol: ticker symbol, matched case-sensitive against
            ``assets.symbol``.
        start_date: inclusive lower bound on event date.
        end_date: inclusive upper bound on event date.
    """
    from src.backend.event_context import EventDB, EventGateDecisionDB

    # Resolve asset → id. Empty result short-circuits the query.
    asset = await db_client.get_asset(asset_symbol)
    if asset is None:
        return _empty_gates_df()

    # We grow the date filter by the largest plausible window on each
    # side. The gate rows have their own window_before/after_days, but
    # we have to broaden the *event_date* filter so any gate whose
    # window OVERLAPS the backtest range is included even if the event
    # itself is outside the range. 30 days is comfortably wider than
    # the V3.2 default (2 days) and the longest known event-type window.
    pad = timedelta(days=30)
    lower_dt = datetime.combine(start_date - pad, datetime.min.time())
    upper_dt = datetime.combine(end_date + pad, datetime.max.time())

    stmt = (
        select(EventGateDecisionDB, EventDB)
        .join(EventDB, EventDB.id == EventGateDecisionDB.event_id)
        .where(
            EventGateDecisionDB.asset_id == asset.id,
            EventDB.time_start_utc >= lower_dt,
            EventDB.time_start_utc <= upper_dt,
        )
        .order_by(EventDB.time_start_utc.asc())
    )
    rows = (await db_client.session.execute(stmt)).all()

    if not rows:
        return _empty_gates_df()

    records: list[dict[str, Any]] = []
    for gate, event in rows:
        records.append(
            {
                "event_id": event.id,
                "event_date": event.time_start_utc.date(),
                "available_at_date": (
                    event.available_at.date()
                    if event.available_at is not None
                    else None
                ),
                "gate_action": gate.gate_action,
                "multiplier": gate.position_size_multiplier,
                "window_before_days": gate.window_before_days,
                "window_after_days": gate.window_after_days,
                "risk_severity": gate.risk_severity,
                "reason_text": gate.reason_text or "",
                "event_importance": _extract_importance(event.specifics_json),
            }
        )
    return pd.DataFrame.from_records(records)


def _empty_gates_df() -> pd.DataFrame:
    """Schema-stable empty DataFrame so downstream code can rely on columns."""
    return pd.DataFrame(
        columns=[
            "event_id",
            "event_date",
            "available_at_date",
            "gate_action",
            "multiplier",
            "window_before_days",
            "window_after_days",
            "risk_severity",
            "reason_text",
            "event_importance",
        ]
    )


def apply_gate_at_decision(
    gates_df: pd.DataFrame | None,
    decision_date: date,
    asset_symbol: str,  # kept for symmetry / future multi-asset extension
    allowed_actions: list[str],
    min_severity: float,
    min_importance: float = 0.0,
) -> AppliedGate | None:
    """Return the active gate (if any) for *decision_date* + *asset_symbol*.

    A gate row is **active on** ``decision_date`` when all of:

    * ``decision_date >= max(available_at_date, event_date - window_before_days)``
      — the asymmetric lower bound enforces ATS-2002 look-ahead: if the
      market did not yet know about the event, we cannot gate trades
      ahead of it.
    * ``decision_date <= event_date + window_after_days`` — gate expires
      after the post-window.
    * ``gate_action in allowed_actions`` — configurable per backtest.
    * ``risk_severity >= min_severity`` — actionable filter.
    * ``event_importance >= min_importance`` — secondary filter.

    When multiple gates qualify, the strictest wins (BLOCK > REDUCE >
    NO_GATE); within an action, the higher ``risk_severity`` wins.

    Args:
        gates_df: result of :func:`load_gates_for_backtest`. ``None`` or
            empty is treated as "no gates" — returns ``None``.
        decision_date: the bar date the strategy is about to act on.
        asset_symbol: ticker — currently passes through (the DataFrame is
            already pre-filtered to one asset) but kept in the signature
            for the multi-asset extension.
        allowed_actions: which ``gate_action`` values the strategy honors.
        min_severity: minimum ``risk_severity`` for a gate to be actionable.
        min_importance: minimum ``event_importance`` for a gate to be
            actionable. Defaults to 0.0 (no extra filter).

    Returns:
        :class:`AppliedGate` for the strictest active gate, or ``None``
        when no gate qualifies.
    """
    if gates_df is None or gates_df.empty:
        return None

    # Row-wise filter — gates_df is small per asset (weeks of events at
    # most). Pandas can't subtract a Timedelta column from a date-typed
    # Series without a costly cast back and forth, and the loop overhead
    # is negligible against the cost of the backtest's per-bar logic.
    candidates: list[AppliedGate] = []
    for row in gates_df.itertuples(index=False):
        event_date: date = row.event_date
        avail_date: date | None = row.available_at_date
        win_before: int = int(row.window_before_days)
        win_after: int = int(row.window_after_days)
        # Effective "known" date — fall back to event_date when
        # available_at is missing (conservative; cannot pre-gate).
        effective_known = avail_date if avail_date is not None else event_date
        pre_window_start = event_date - timedelta(days=win_before)
        # Asymmetric lower bound — the LATER of (known-date, pre-window-start).
        lower = max(effective_known, pre_window_start)
        upper = event_date + timedelta(days=win_after)
        if not (lower <= decision_date <= upper):
            continue
        if row.gate_action not in allowed_actions:
            continue
        if row.risk_severity < min_severity:
            continue
        if row.event_importance < min_importance:
            continue
        candidates.append(
            AppliedGate(
                event_id=str(row.event_id),
                gate_action=str(row.gate_action),
                multiplier=float(row.multiplier),
                reason=str(row.reason_text),
                risk_severity=float(row.risk_severity),
            )
        )

    if not candidates:
        return None

    # Strictest-wins. Sort by (action_strictness desc, risk_severity desc).
    candidates.sort(
        key=lambda g: (_ACTION_STRICTNESS.get(g.gate_action, 0), g.risk_severity),
        reverse=True,
    )
    return candidates[0]
