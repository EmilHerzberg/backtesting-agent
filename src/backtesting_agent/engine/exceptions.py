"""Custom exception hierarchy for the backtesting engine."""

from __future__ import annotations


class BacktestError(Exception):
    """Base exception for all backtesting engine errors."""


class InsufficientDataError(BacktestError):
    """Raised when the provided DataFrame has too few rows for a meaningful backtest."""

    def __init__(self, rows: int, minimum: int = 2) -> None:
        self.rows = rows
        self.minimum = minimum
        super().__init__(
            f"Insufficient data: got {rows} rows, need at least {minimum}."
        )


class InvalidParameterError(BacktestError):
    """Raised when strategy parameters are invalid or out of range."""

    def __init__(self, message: str, params: dict | None = None) -> None:
        self.params = params or {}
        super().__init__(message)


class NoTradesError(BacktestError):
    """Raised when a backtest completes but produces zero trades."""

    def __init__(self, symbol: str = "") -> None:
        self.symbol = symbol
        msg = "Backtest produced no trades"
        if symbol:
            msg += f" for {symbol}"
        super().__init__(msg)


class OptimizationError(BacktestError):
    """Raised when Optuna optimization fails or produces no valid trials."""

    def __init__(self, message: str, n_trials: int = 0) -> None:
        self.n_trials = n_trials
        super().__init__(message)
