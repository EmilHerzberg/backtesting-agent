"""Structured logging, progress callbacks, and error reporting for backtesting."""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------- #
# JSON formatter
# ---------------------------------------------------------------------- #


class BacktestJsonFormatter(logging.Formatter):
    """JSON formatter for structured logging output.

    Emits one JSON object per log line.  Extra attributes ``trial_id`` and
    ``metrics`` are included when present on the log record.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
        }
        if hasattr(record, "trial_id"):
            log_data["trial_id"] = record.trial_id
        if hasattr(record, "metrics"):
            log_data["metrics"] = record.metrics
        return json.dumps(log_data, default=str)


# ---------------------------------------------------------------------- #
# Logging setup helper
# ---------------------------------------------------------------------- #


def setup_backtest_logging(
    verbose: bool = False,
    json_format: bool = False,
) -> None:
    """Configure logging for a backtesting CLI session.

    Args:
        verbose: If ``True``, set level to DEBUG; otherwise INFO.
        json_format: If ``True``, use :class:`BacktestJsonFormatter`.
    """
    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)

    # Remove existing handlers to avoid duplicates
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)

    if json_format:
        handler.setFormatter(BacktestJsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    root.addHandler(handler)

    # Reduce noise from third-party libraries
    for noisy in (
        "httpx", "httpcore", "urllib3", "yfinance",
        "sqlalchemy.engine", "optuna",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logger.debug("Backtesting logging initialized (level=%s)", level)


# ---------------------------------------------------------------------- #
# Optuna progress callback
# ---------------------------------------------------------------------- #


class TrialProgressCallback:
    """Optuna callback that prints trial progress with ETA.

    Usage::

        cb = TrialProgressCallback(total_trials=100)
        study.optimize(objective, n_trials=100, callbacks=[cb])
    """

    def __init__(self, total_trials: int) -> None:
        self.total: int = total_trials
        self.start_time: float | None = None
        self._logger = logging.getLogger(f"{__name__}.progress")

    def __call__(self, study: Any, trial: Any) -> None:
        if self.start_time is None:
            self.start_time = time.time()

        completed = trial.number + 1
        elapsed = time.time() - self.start_time
        rate = completed / elapsed if elapsed > 0 else 0.0
        remaining = (self.total - completed) / rate if rate > 0 else 0.0

        best_val = study.best_value if study.best_trial else float("nan")

        self._logger.info(
            "Trial %d/%d | best=%.4f | %.1f trials/s | ETA %.0fs",
            completed,
            self.total,
            best_val,
            rate,
            remaining,
        )


# ---------------------------------------------------------------------- #
# Error reporter
# ---------------------------------------------------------------------- #


class ErrorReporter:
    """Collects and reports failed Optuna trials.

    Can be used as an Optuna callback and also called manually.

    Args:
        log_path: Path for the JSONL error log file.
    """

    def __init__(self, log_path: str = "data/backtest_errors.jsonl") -> None:
        self.errors: list[dict[str, Any]] = []
        self.log_path: str = log_path

    def __call__(self, study: Any, trial: Any) -> None:
        """Optuna callback -- records failed trials."""
        try:
            import optuna

            if trial.state == optuna.trial.TrialState.FAIL:
                error_entry = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "study": study.study_name,
                    "trial_number": trial.number,
                    "params": dict(trial.params),
                    "state": trial.state.name,
                    "message": str(trial.value) if trial.value else "N/A",
                }
                self.errors.append(error_entry)
        except ImportError:
            pass

    def add_error(
        self,
        context: str,
        error: Exception,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Manually record a non-Optuna error."""
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "context": context,
            "error_type": type(error).__name__,
            "message": str(error),
        }
        if extra:
            entry.update(extra)
        self.errors.append(entry)

    def summary(self) -> str:
        """Return a human-readable summary of all recorded errors."""
        if not self.errors:
            return "No errors recorded."
        lines = [f"Total errors: {len(self.errors)}"]
        for i, err in enumerate(self.errors, 1):
            msg = err.get("message", err.get("error_type", "unknown"))
            ctx = err.get("context", err.get("study", "optuna"))
            lines.append(f"  {i}. [{ctx}] {msg}")
        return "\n".join(lines)

    def save(self) -> None:
        """Persist errors to a JSONL file."""
        if not self.errors:
            return
        path = Path(self.log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for entry in self.errors:
                f.write(json.dumps(entry, default=str) + "\n")
        logger.info("Saved %d error(s) to %s", len(self.errors), self.log_path)
