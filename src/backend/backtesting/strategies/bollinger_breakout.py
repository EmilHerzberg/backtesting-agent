"""Bollinger Bands Breakout strategy for backtesting.py."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from backtesting.lib import crossover

from src.backend.backtesting.strategies.base import StrategyBase


class BollingerBreakout(StrategyBase):
    """Bollinger Bands mean-reversion / breakout strategy.

    Buys when the price crosses below the lower band (oversold breakout)
    and sells when price crosses above the upper band.  When
    ``exit_on_mean`` is true, positions are also closed when price
    returns to the middle band.

    F-018 fix: optional hard stop-loss as fraction of entry price
    (stop_loss_pct). Default 0.0 = no stop-loss (backwards compatible).
    """

    period: int = 20
    std_dev: float = 2.0
    exit_on_mean: int = 1  # backtesting.py needs numeric; 1 = True, 0 = False
    stop_loss_pct: float = 0.0  # F-018: 0.0 = disabled, 0.10 = -10% stop

    @classmethod
    def parameter_space(cls) -> dict[str, dict[str, Any]]:
        return {
            "period": {"type": "int", "low": 10, "high": 50},
            "std_dev": {"type": "float", "low": 1.0, "high": 3.5},
            "exit_on_mean": {"type": "categorical", "choices": [0, 1]},
            "stop_loss_pct": {"type": "float", "low": 0.0, "high": 0.20},  # F-018
        }

    @staticmethod
    def _bollinger_upper(close: np.ndarray, period: int, std_dev: float) -> np.ndarray:
        s = pd.Series(close)
        middle = s.rolling(window=period, min_periods=period).mean()
        std = s.rolling(window=period, min_periods=period).std()
        return (middle + std_dev * std).values

    @staticmethod
    def _bollinger_lower(close: np.ndarray, period: int, std_dev: float) -> np.ndarray:
        s = pd.Series(close)
        middle = s.rolling(window=period, min_periods=period).mean()
        std = s.rolling(window=period, min_periods=period).std()
        return (middle - std_dev * std).values

    @staticmethod
    def _bollinger_middle(close: np.ndarray, period: int) -> np.ndarray:
        s = pd.Series(close)
        return s.rolling(window=period, min_periods=period).mean().values

    def init(self) -> None:
        close = self.data.Close
        self.upper = self.I(
            self._bollinger_upper, close, self.period, self.std_dev,
            name=f"BB_upper({self.period},{self.std_dev})",
        )
        self.lower = self.I(
            self._bollinger_lower, close, self.period, self.std_dev,
            name=f"BB_lower({self.period},{self.std_dev})",
        )
        self.middle = self.I(
            self._bollinger_middle, close, self.period,
            name=f"BB_middle({self.period})",
        )

    def next(self) -> None:
        price = self.data.Close[-1]

        if crossover(self.lower, self.data.Close):
            # Price crossed below lower band -- buy
            if not self.position:
                # F-018 fix: optional hard stop-loss below entry
                if self.stop_loss_pct and self.stop_loss_pct > 0:
                    sl_price = price * (1.0 - float(self.stop_loss_pct))
                    self._gated_buy(sl=sl_price)   # H13: through the event gate (no-op when unconfigured)
                else:
                    self._gated_buy()
        elif crossover(self.data.Close, self.upper):
            # Price crossed above upper band -- sell
            if self.position:
                self.position.close()
        elif self.exit_on_mean and self.position:
            # Exit when price returns to the middle band
            if crossover(self.data.Close, self.middle):
                self.position.close()
