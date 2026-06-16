"""Base class for backtesting indicators with Optuna parameter space support."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

import pandas as pd


class Signal(StrEnum):
    """Trading signal enumeration."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class BacktestIndicator(ABC):
    """Abstract base class for all backtesting indicators.

    Extends the concept of the existing IIndicator to work with pandas
    DataFrames (OHLCV) and declare Optuna parameter search spaces.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique indicator name, e.g. 'SMA(20)'."""

    @abstractmethod
    def parameter_space(self) -> dict[str, dict[str, Any]]:
        """Return Optuna parameter definitions.

        Example::

            {
                "period": {"type": "int", "low": 5, "high": 200},
                "threshold": {"type": "float", "low": 0.1, "high": 0.9},
            }

        Supported types: "int", "float", "categorical".
        For "categorical", provide "choices" instead of "low"/"high".
        """

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.Series:
        """Compute the indicator's primary value from an OHLCV DataFrame.

        Args:
            df: DataFrame with columns Open, High, Low, Close, Volume.

        Returns:
            Series of indicator values, indexed like *df*.
        """

    @abstractmethod
    def signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate BUY / SELL / HOLD signals for every row.

        Args:
            df: DataFrame with columns Open, High, Low, Close, Volume.

        Returns:
            Series of :class:`Signal` values, indexed like *df*.
        """

    def _validate_ohlcv(self, df: pd.DataFrame) -> None:
        """Raise ``ValueError`` if required OHLCV columns are missing."""
        required = {"Open", "High", "Low", "Close", "Volume"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"DataFrame missing required columns: {missing}")

    def _validate_close(self, df: pd.DataFrame) -> None:
        """Raise ``ValueError`` if the Close column is missing."""
        if "Close" not in df.columns:
            raise ValueError("DataFrame missing required column: Close")


def suggest_params(
    trial: Any,
    param_space: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Suggest Optuna trial parameters from a parameter-space definition.

    Args:
        trial: An ``optuna.trial.Trial`` object.
        param_space: Parameter definitions as returned by
            :meth:`BacktestIndicator.parameter_space`.

    Returns:
        Dict mapping parameter name to the suggested value.
    """
    params: dict[str, Any] = {}
    for name, spec in param_space.items():
        ptype = spec["type"]
        if ptype == "int":
            params[name] = trial.suggest_int(
                name, spec["low"], spec["high"], step=spec.get("step", 1)
            )
        elif ptype == "float":
            params[name] = trial.suggest_float(
                name,
                spec["low"],
                spec["high"],
                step=spec.get("step"),
                log=spec.get("log", False),
            )
        elif ptype == "categorical":
            params[name] = trial.suggest_categorical(name, spec["choices"])
        else:
            raise ValueError(f"Unknown parameter type '{ptype}' for '{name}'")
    return params
