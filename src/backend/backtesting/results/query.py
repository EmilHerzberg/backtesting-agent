"""Filtering, ranking, and export utilities for backtest trials."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.backend.backtesting.results.models import BTStrategy, BTTrial
from src.backend.backtesting.results.store import ResultStore


@dataclass
class FilterCriteria:
    """Declarative filter for querying backtest trials.

    All fields are optional.  ``None`` means "no constraint".
    """

    strategy_name: str | None = None
    symbol: str | None = None
    min_sharpe: float | None = None
    max_drawdown: float | None = None  # e.g. -0.2 means max 20% dd
    min_trades: int | None = None
    min_profit_factor: float | None = None
    is_validated: bool | None = None
    interval: str | None = None
    is_simulation: bool | None = None  # SIM-S2-T3 / ATS-1131


class ResultQuery:
    """High-level query interface on top of :class:`ResultStore`."""

    def __init__(self, store: ResultStore) -> None:
        self._store = store

    # ------------------------------------------------------------------ #
    # Filtering
    # ------------------------------------------------------------------ #

    def filter(self, criteria: FilterCriteria) -> list[BTTrial]:
        """Return trials matching *all* non-``None`` criteria."""
        with self._store._session() as session:
            query = session.query(BTTrial).join(BTStrategy)

            if criteria.strategy_name is not None:
                query = query.filter(BTStrategy.name == criteria.strategy_name)

            if criteria.symbol is not None:
                query = query.filter(BTTrial.symbol == criteria.symbol)

            if criteria.interval is not None:
                query = query.filter(BTTrial.interval == criteria.interval)

            if criteria.min_sharpe is not None:
                query = query.filter(BTTrial.sharpe_ratio >= criteria.min_sharpe)

            if criteria.max_drawdown is not None:
                # max_drawdown stored as positive value; filter means
                # "drawdown must not exceed X%".  A criteria value of -20
                # means we accept trials with max_drawdown <= 20.
                try:
                    limit = abs(float(criteria.max_drawdown))
                    query = query.filter(BTTrial.max_drawdown <= limit)
                except (TypeError, ValueError):
                    pass

            if criteria.min_trades is not None:
                query = query.filter(BTTrial.trade_count >= criteria.min_trades)

            if criteria.min_profit_factor is not None:
                query = query.filter(
                    BTTrial.profit_factor >= criteria.min_profit_factor
                )

            if criteria.is_validated is not None:
                query = query.filter(BTTrial.is_validated == criteria.is_validated)

            if criteria.is_simulation is not None:
                query = query.filter(BTTrial.is_simulation == criteria.is_simulation)

            trials = query.all()
            _eager_load(trials)
            session.expunge_all()
            return trials

    # ------------------------------------------------------------------ #
    # Ranking
    # ------------------------------------------------------------------ #

    def rank(
        self,
        trials: list[BTTrial],
        metric: str = "sharpe_ratio",
        ascending: bool = False,
    ) -> list[BTTrial]:
        """Sort *in-memory* trial list by the given metric column."""
        return sorted(
            trials,
            key=lambda t: getattr(t, metric, 0.0) or 0.0,
            reverse=not ascending,
        )

    # ------------------------------------------------------------------ #
    # Top-N helpers
    # ------------------------------------------------------------------ #

    def top_n(
        self,
        n: int = 10,
        metric: str = "sharpe_ratio",
        criteria: FilterCriteria | None = None,
    ) -> list[BTTrial]:
        """Return the top *n* trials by *metric*, with optional pre-filtering."""
        if criteria is not None:
            trials = self.filter(criteria)
        else:
            trials = self._store.get_all_trials()
        ranked = self.rank(trials, metric=metric)
        return ranked[:n]

    def top_per_symbol(
        self,
        n: int = 3,
        metric: str = "sharpe_ratio",
    ) -> dict[str, list[BTTrial]]:
        """Return top *n* strategies per symbol."""
        all_trials = self._store.get_all_trials()
        by_symbol: dict[str, list[BTTrial]] = {}
        for t in all_trials:
            by_symbol.setdefault(t.symbol, []).append(t)

        result: dict[str, list[BTTrial]] = {}
        for symbol, trials in by_symbol.items():
            ranked = self.rank(trials, metric=metric)
            result[symbol] = ranked[:n]
        return result

    # ------------------------------------------------------------------ #
    # Export
    # ------------------------------------------------------------------ #

    def export_top_n(
        self,
        n: int = 10,
        metric: str = "sharpe_ratio",
        criteria: FilterCriteria | None = None,
        format: str = "dict",
    ) -> list[dict] | str:
        """Export top *n* results.

        Args:
            n: Number of results.
            metric: Ranking metric.
            criteria: Optional pre-filter.
            format: ``"dict"`` (list of plain dicts), ``"json"`` (string),
                or ``"csv"`` (string with header row + one row per trial).

        Returns:
            ``list[dict]`` for ``format="dict"``, otherwise a serialized string.

        Raises:
            ValueError: if *format* is unknown.
        """
        trials = self.top_n(n=n, metric=metric, criteria=criteria)
        rows: list[dict] = []
        for t in trials:
            row = {
                "trial_id": t.id,
                "strategy": t.strategy.name if t.strategy else None,
                "symbol": t.symbol,
                "interval": t.interval,
                "parameters": t.parameters,
                "total_return": t.total_return,
                "sharpe_ratio": t.sharpe_ratio,
                "max_drawdown": t.max_drawdown,
                "sortino_ratio": t.sortino_ratio,
                "win_rate": t.win_rate,
                "trade_count": t.trade_count,
                "profit_factor": t.profit_factor,
                "calmar_ratio": t.calmar_ratio,
                "buy_hold_return": t.buy_hold_return,
                "exposure_time": t.exposure_time,
                "is_train": t.is_train,
                "overfitting_score": t.overfitting_score,
                "is_validated": t.is_validated,
                "created_at": str(t.created_at) if t.created_at else None,
            }
            rows.append(row)

        fmt = format.lower().strip()
        if fmt == "dict":
            return rows
        if fmt == "json":
            import json
            return json.dumps(rows, default=str, indent=2)
        if fmt == "csv":
            import csv
            import io
            buf = io.StringIO()
            # Use a stable column order matching the dict above; serialize
            # nested values (parameters dict) via JSON so the CSV cell stays
            # one logical column.
            fieldnames = list(rows[0].keys()) if rows else [
                "trial_id", "strategy", "symbol", "interval", "parameters",
                "total_return", "sharpe_ratio", "max_drawdown", "sortino_ratio",
                "win_rate", "trade_count", "profit_factor", "calmar_ratio",
                "buy_hold_return", "exposure_time", "is_train",
                "overfitting_score", "is_validated", "created_at",
            ]
            writer = csv.DictWriter(buf, fieldnames=fieldnames)
            writer.writeheader()
            import json as _json
            for row in rows:
                flat = {
                    k: (_json.dumps(v, default=str) if isinstance(v, (dict, list)) else v)
                    for k, v in row.items()
                }
                writer.writerow(flat)
            return buf.getvalue()
        raise ValueError(f"Unknown format '{format}'. Allowed: dict, json, csv")


# ------------------------------------------------------------------ #
# Internal
# ------------------------------------------------------------------ #


def _eager_load(trials: list[BTTrial]) -> None:
    """Touch lazy-loaded relationships so they survive session close."""
    for t in trials:
        _ = t.strategy
        _ = t.equity_curve
        _ = t.trade_log
