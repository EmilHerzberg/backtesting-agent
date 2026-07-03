"""MACD Signal Cross strategy for backtesting.py."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from backtesting.lib import crossover

from src.backend.backtesting.strategies.base import StrategyBase


class MACDSignalCross(StrategyBase):
    """MACD / Signal line crossover strategy.

    Buys when the MACD line crosses above the signal line and closes
    the position when the MACD line crosses below the signal line.
    """

    fast: int = 12
    slow: int = 26
    signal_period: int = 9

    @classmethod
    def parameter_space(cls) -> dict[str, dict[str, Any]]:
        return {
            "fast": {"type": "int", "low": 5, "high": 20},
            "slow": {"type": "int", "low": 20, "high": 50},
            "signal_period": {"type": "int", "low": 5, "high": 15},
        }

    @classmethod
    def validate_params(cls, params: dict[str, Any]) -> None:
        """F-019 fix: enforce slow > fast + 5."""
        from src.backend.backtesting.engine.exceptions import InvalidParameterError
        fast = params.get("fast", cls.fast)
        slow = params.get("slow", cls.slow)
        if slow <= fast + 5:
            raise InvalidParameterError(
                f"MACDSignalCross requires slow > fast + 5 "
                f"(got fast={fast}, slow={slow})"
            )

    @staticmethod
    def _macd_line(close: np.ndarray, fast: int, slow: int) -> np.ndarray:
        s = pd.Series(close)
        fast_ema = s.ewm(span=fast, adjust=False).mean()
        slow_ema = s.ewm(span=slow, adjust=False).mean()
        return (fast_ema - slow_ema).values

    @staticmethod
    def _signal_line(
        close: np.ndarray, fast: int, slow: int, signal_period: int,
    ) -> np.ndarray:
        s = pd.Series(close)
        fast_ema = s.ewm(span=fast, adjust=False).mean()
        slow_ema = s.ewm(span=slow, adjust=False).mean()
        macd = fast_ema - slow_ema
        return macd.ewm(span=signal_period, adjust=False).mean().values

    def init(self) -> None:
        close = self.data.Close
        self.macd = self.I(
            self._macd_line, close, self.fast, self.slow,
            name=f"MACD({self.fast},{self.slow})",
        )
        self.signal = self.I(
            self._signal_line, close, self.fast, self.slow, self.signal_period,
            name=f"Signal({self.signal_period})",
        )

    def next(self) -> None:
        if crossover(self.macd, self.signal):
            if not self.position:
                self.buy()
        elif crossover(self.signal, self.macd):
            if self.position:
                self.position.close()
