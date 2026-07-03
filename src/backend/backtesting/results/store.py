"""Persistence layer for backtest results using synchronous SQLAlchemy."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.backend.backtesting.engine.metrics import TradeDetail
from src.backend.backtesting.engine.optimizer import OptimizationResult
from src.backend.backtesting.engine.runner import BacktestResult
from src.backend.backtesting.engine.walk_forward import WalkForwardResult
from src.backend.backtesting.results.models import (
    BTEquityCurve,
    BTStrategy,
    BTTradeLog,
    BTTrial,
    Base,
)

logger = logging.getLogger(__name__)


# ── Helper functions for extended metrics ────────────────────────────

_CACHED_ENGINE_VERSION: str | None = None

def _get_engine_version() -> str:
    """Get current git commit hash for reproducibility (cached)."""
    global _CACHED_ENGINE_VERSION
    if _CACHED_ENGINE_VERSION is not None:
        return _CACHED_ENGINE_VERSION
    try:
        import subprocess, os
        _CACHED_ENGINE_VERSION = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        import os
        _CACHED_ENGINE_VERSION = os.environ.get("GIT_COMMIT", "unknown")
    return _CACHED_ENGINE_VERSION


def _compute_drawdown_series(equity: list[float]) -> list[float]:
    """Compute drawdown percentage at each point."""
    if not equity:
        return []
    peak = equity[0]
    dd = []
    for v in equity:
        if v > peak:
            peak = v
        dd.append(round((v - peak) / peak * 100, 4) if peak > 0 else 0.0)
    return dd


def _compute_drawdown_metrics(equity: list[float]) -> tuple[int | None, int | None]:
    """Compute max drawdown duration (bars) and recovery time (bars)."""
    if not equity or len(equity) < 2:
        return None, None
    peak = equity[0]
    max_duration = 0
    max_recovery = 0
    dd_start = 0
    in_dd = False

    for i, v in enumerate(equity):
        if v >= peak:
            if in_dd:
                recovery = i - dd_start
                if recovery > max_recovery:
                    max_recovery = recovery
                in_dd = False
            peak = v
        else:
            if not in_dd:
                dd_start = i
                in_dd = True
            duration = i - dd_start + 1
            if duration > max_duration:
                max_duration = duration

    return max_duration if max_duration > 0 else None, max_recovery if max_recovery > 0 else None


def _compute_avg_holding_days(trades: list) -> float | None:
    """Compute average trade holding time in days."""
    if not trades:
        return None
    from datetime import datetime as dt
    durations = []
    for t in trades:
        try:
            entry = dt.fromisoformat(str(t.entry_time).replace("Z", "+00:00")) if t.entry_time else None
            exit_ = dt.fromisoformat(str(t.exit_time).replace("Z", "+00:00")) if t.exit_time else None
            if entry and exit_:
                days = (exit_ - entry).total_seconds() / 86400
                if days > 0:
                    durations.append(days)
        except Exception:
            continue
    return round(sum(durations) / len(durations), 2) if durations else None


def _compute_max_concurrent_positions(trades: list) -> int | None:
    """Compute max number of overlapping trades."""
    if not trades:
        return None
    from datetime import datetime as dt
    events = []
    for t in trades:
        try:
            entry = dt.fromisoformat(str(t.entry_time).replace("Z", "+00:00")) if t.entry_time else None
            exit_ = dt.fromisoformat(str(t.exit_time).replace("Z", "+00:00")) if t.exit_time else None
            if entry:
                events.append((entry, 1))
            if exit_:
                events.append((exit_, -1))
        except Exception:
            continue
    if not events:
        return None
    events.sort(key=lambda x: x[0])
    current = 0
    max_pos = 0
    for _, delta in events:
        current += delta
        max_pos = max(max_pos, current)
    return max_pos if max_pos > 0 else None


def _compute_turnover(trades: list, cash: float) -> float | None:
    """Compute turnover as total traded value / capital."""
    if not trades or cash <= 0:
        return None
    total_value = 0.0
    for t in trades:
        try:
            price = t.entry_price or 0
            size = abs(t.size or 0)
            total_value += price * size
        except Exception:
            continue
    return round(total_value / cash, 4) if total_value > 0 else None


class ResultStore:
    """Read/write interface for persisting backtest results to SQLite.

    F-024 fix: konsolidiert auf die Haupt-DB ``data/trading.db`` (vorher
    eigene ``data/backtesting.db``) damit Waterfall-Generator + Goal-
    Orchestrator + alle anderen Module die Trials auch sehen koennen.
    """

    def __init__(self, db_url: str = "sqlite:///data/trading.db") -> None:
        self.engine = create_engine(db_url, echo=False)
        Base.metadata.create_all(self.engine)
        self._run_bt_migrations()
        self._session_factory = sessionmaker(bind=self.engine)

    def _run_bt_migrations(self) -> None:
        """Add new columns to existing backtesting tables (F-023 fix).

        Idempotent: ALTER TABLE ADD COLUMN nur wenn Spalte fehlt.
        """
        from sqlalchemy import inspect, text
        with self.engine.connect() as conn:
            insp = inspect(conn)
            migrations = [
                ("bt_trials", "engine_version", "VARCHAR(50)"),
                ("bt_trials", "data_source", "VARCHAR(50)"),
                ("bt_trials", "cost_config_json", "VARCHAR(500)"),
                ("bt_trials", "fill_mode", "VARCHAR(20)"),
                ("bt_trials", "max_drawdown_duration", "INTEGER"),
                ("bt_trials", "max_drawdown_recovery", "INTEGER"),
                ("bt_trials", "avg_holding_days", "FLOAT"),
                ("bt_trials", "turnover", "FLOAT"),
                ("bt_trials", "batch_job_id", "INTEGER"),  # F-001 fix
                ("bt_trials", "is_simulation", "BOOLEAN DEFAULT 0"),  # SIM-S2-T1 / ATS-1129
                ("bt_equity_curves", "drawdown_values", "TEXT"),
                ("bt_equity_curves", "bar_timestamps", "TEXT"),  # SIM-S2-T4 / ATS-1132
            ]
            for table, col, col_type in migrations:
                if not insp.has_table(table):
                    continue
                existing = {c["name"] for c in insp.get_columns(table)}
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                    logger.info("BT migration: added %s.%s", table, col)
            conn.commit()

    def _session(self) -> Session:
        """Create a new session."""
        return self._session_factory()

    # ------------------------------------------------------------------ #
    # Strategy helpers
    # ------------------------------------------------------------------ #

    def _get_or_create_strategy(
        self,
        session: Session,
        strategy_name: str,
        class_name: str,
        parameter_space: dict[str, Any] | None = None,
    ) -> BTStrategy:
        """Return existing strategy row or create a new one."""
        strategy = (
            session.query(BTStrategy)
            .filter_by(name=strategy_name, class_name=class_name)
            .first()
        )
        if strategy is None:
            strategy = BTStrategy(
                name=strategy_name,
                class_name=class_name,
                parameter_space=parameter_space,
            )
            session.add(strategy)
            session.flush()
        return strategy

    # ------------------------------------------------------------------ #
    # Save a single trial
    # ------------------------------------------------------------------ #

    def save_trial(
        self,
        strategy_name: str,
        class_name: str,
        symbol: str,
        params: dict[str, Any],
        result: BacktestResult,
        interval: str = "1d",
        train_start: str | None = None,
        train_end: str | None = None,
        test_start: str | None = None,
        test_end: str | None = None,
        cash: float = 10_000.0,
        commission: float = 0.001,
        is_train: bool = True,
        overfitting_score: float | None = None,
        is_validated: bool | None = None,
        batch_job_id: int | None = None,  # F-001 fix
        is_simulation: bool = False,  # SIM-S2 / ATS-1129
        bar_timestamps: list[str] | None = None,  # SIM-S2-T4 / ATS-1132
    ) -> int:
        """Persist a single backtest trial and return the trial id."""
        with self._session() as session:
            strategy = self._get_or_create_strategy(
                session, strategy_name, class_name
            )

            # Compute extended metrics
            dd_duration, dd_recovery = _compute_drawdown_metrics(result.equity_curve)
            avg_holding = None
            turnover = None
            try:
                if isinstance(result.trades, list) and result.trades:
                    avg_holding = _compute_avg_holding_days(result.trades)
                    turnover = _compute_turnover(result.trades, cash)
            except Exception as exc:
                logger.warning("Could not compute trade metrics: %s", exc)
            engine_ver = _get_engine_version()

            trial = BTTrial(
                strategy_id=strategy.id,
                symbol=symbol,
                interval=interval,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                parameters=params,
                cash=cash,
                commission=commission,
                total_return=result.total_return,
                sharpe_ratio=result.sharpe_ratio,
                max_drawdown=result.max_drawdown,
                sortino_ratio=result.sortino_ratio,
                win_rate=result.win_rate,
                trade_count=result.trade_count,
                profit_factor=result.profit_factor,
                calmar_ratio=result.calmar_ratio,
                buy_hold_return=result.buy_hold_return,
                exposure_time=result.exposure_time,
                is_train=is_train,
                overfitting_score=overfitting_score,
                is_validated=is_validated,
                batch_job_id=batch_job_id,  # F-001 fix
                is_simulation=is_simulation,
                # Run lineage
                engine_version=engine_ver,
                data_source="aggregated",
                fill_mode="close",
                # Extended risk metrics
                max_drawdown_duration=dd_duration,
                max_drawdown_recovery=dd_recovery,
                avg_holding_days=avg_holding,
                turnover=turnover,
            )
            session.add(trial)
            session.flush()

            # Equity curve + drawdown series
            if result.equity_curve:
                dd_series = _compute_drawdown_series(result.equity_curve)
                # Trim timestamps to match values length if both provided.
                ts_persist: list[str] | None = None
                if bar_timestamps:
                    n = min(len(bar_timestamps), len(result.equity_curve))
                    ts_persist = list(bar_timestamps[:n])
                eq = BTEquityCurve(
                    trial_id=trial.id,
                    values=result.equity_curve,
                    drawdown_values=dd_series,
                    bar_timestamps=ts_persist,
                )
                session.add(eq)

            # Trade log
            for t in result.trades:
                session.add(
                    BTTradeLog(
                        trial_id=trial.id,
                        entry_time=t.entry_time,
                        exit_time=t.exit_time,
                        side=t.side,
                        entry_price=t.entry_price,
                        exit_price=t.exit_price,
                        size=t.size,
                        pnl=t.pnl,
                        pnl_pct=t.pnl_pct,
                    )
                )

            session.commit()
            trial_id: int = trial.id

        logger.info(
            "Saved trial %d for %s/%s on %s", trial_id, strategy_name, symbol, interval
        )
        return trial_id

    # ------------------------------------------------------------------ #
    # Save optimization results
    # ------------------------------------------------------------------ #

    def save_optimization(
        self,
        strategy_name: str,
        class_name: str,
        symbol: str,
        opt_result: OptimizationResult,
        interval: str = "1d",
        cash: float = 10_000.0,
        commission: float = 0.001,
    ) -> list[int]:
        """Save all completed trials from an Optuna optimization run.

        Only the best trial stores full equity curve and trade log; the
        remaining trials store parameter/metric summaries only.

        Returns:
            List of trial ids created.
        """
        trial_ids: list[int] = []

        # Save the best trial with full detail
        best_id = self.save_trial(
            strategy_name=strategy_name,
            class_name=class_name,
            symbol=symbol,
            params=opt_result.best_params,
            result=opt_result.best_result,
            interval=interval,
            cash=cash,
            commission=commission,
        )
        trial_ids.append(best_id)

        # Save summary rows for other completed trials
        with self._session() as session:
            strategy = self._get_or_create_strategy(
                session, strategy_name, class_name
            )

            for t in opt_result.all_trials:
                if t["state"] != "COMPLETE":
                    continue
                if t["params"] == opt_result.best_params:
                    continue  # already saved above

                trial = BTTrial(
                    strategy_id=strategy.id,
                    symbol=symbol,
                    interval=interval,
                    parameters=t["params"],
                    cash=cash,
                    commission=commission,
                    sharpe_ratio=t.get("value"),
                    is_train=True,
                )
                session.add(trial)
                session.flush()
                trial_ids.append(trial.id)

            session.commit()

        logger.info(
            "Saved %d optimization trials for %s/%s",
            len(trial_ids),
            strategy_name,
            symbol,
        )
        return trial_ids

    # ------------------------------------------------------------------ #
    # Save walk-forward results
    # ------------------------------------------------------------------ #

    def save_walk_forward(
        self,
        strategy_name: str,
        class_name: str,
        symbol: str,
        wf_result: WalkForwardResult,
        interval: str = "1d",
        cash: float = 10_000.0,
        commission: float = 0.001,
    ) -> list[int]:
        """Save all walk-forward windows (train + test trials).

        Returns:
            List of trial ids created (train and test interleaved).
        """
        trial_ids: list[int] = []

        for window in wf_result.windows:
            # Train trial
            train_id = self.save_trial(
                strategy_name=strategy_name,
                class_name=class_name,
                symbol=symbol,
                params=window.best_params,
                result=window.train_result,
                interval=interval,
                train_start=window.train_start,
                train_end=window.train_end,
                test_start=window.test_start,
                test_end=window.test_end,
                cash=cash,
                commission=commission,
                is_train=True,
                overfitting_score=window.overfitting_score,
                is_validated=window.is_valid,
            )
            trial_ids.append(train_id)

            # Test trial
            test_id = self.save_trial(
                strategy_name=strategy_name,
                class_name=class_name,
                symbol=symbol,
                params=window.best_params,
                result=window.test_result,
                interval=interval,
                train_start=window.train_start,
                train_end=window.train_end,
                test_start=window.test_start,
                test_end=window.test_end,
                cash=cash,
                commission=commission,
                is_train=False,
                overfitting_score=window.overfitting_score,
                is_validated=window.is_valid,
            )
            trial_ids.append(test_id)

        logger.info(
            "Saved %d walk-forward trials for %s/%s",
            len(trial_ids),
            strategy_name,
            symbol,
        )
        return trial_ids

    # ------------------------------------------------------------------ #
    # Query helpers
    # ------------------------------------------------------------------ #

    def get_trial(self, trial_id: int) -> BTTrial | None:
        """Load a single trial by its primary key."""
        with self._session() as session:
            trial = session.get(BTTrial, trial_id)
            if trial is not None:
                # Eagerly load relationships before session closes
                _ = trial.strategy
                _ = trial.equity_curve
                _ = trial.trade_log
                session.expunge_all()
            return trial

    def get_strategy_trials(self, strategy_name: str) -> list[BTTrial]:
        """Return all trials belonging to a named strategy."""
        with self._session() as session:
            trials = (
                session.query(BTTrial)
                .join(BTStrategy)
                .filter(BTStrategy.name == strategy_name)
                .all()
            )
            for t in trials:
                _ = t.strategy
                _ = t.equity_curve
                _ = t.trade_log
            session.expunge_all()
            return trials

    def get_all_trials(self) -> list[BTTrial]:
        """Return every trial in the database."""
        with self._session() as session:
            trials = session.query(BTTrial).all()
            for t in trials:
                _ = t.strategy
                _ = t.equity_curve
                _ = t.trade_log
            session.expunge_all()
            return trials
