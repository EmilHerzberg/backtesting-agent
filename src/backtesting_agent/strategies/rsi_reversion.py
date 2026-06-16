"""RSI Mean Reversion strategy for backtesting.py."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from backtesting_agent.strategies.base import StrategyBase


class RSIMeanReversion(StrategyBase):
    """RSI mean-reversion strategy.

    Buys when RSI drops below the buy threshold (oversold) and sells
    (closes position) when RSI rises above the sell threshold (overbought).
    """

    period: int = 14
    buy_threshold: float = 30.0
    sell_threshold: float = 70.0

    @classmethod
    def parameter_space(cls) -> dict[str, dict[str, Any]]:
        return {
            "period": {"type": "int", "low": 5, "high": 30},
            "buy_threshold": {"type": "float", "low": 15.0, "high": 40.0},
            "sell_threshold": {"type": "float", "low": 60.0, "high": 85.0},
        }

    @classmethod
    def validate_params(cls, params: dict[str, Any]) -> None:
        """F-017 fix: enforce sell_threshold > buy_threshold + 10."""
        from backtesting_agent.engine.exceptions import InvalidParameterError
        buy = params.get("buy_threshold", cls.buy_threshold)
        sell = params.get("sell_threshold", cls.sell_threshold)
        if sell <= buy + 10:
            raise InvalidParameterError(
                f"RSIMeanReversion requires sell_threshold > buy_threshold + 10 "
                f"(got buy={buy}, sell={sell})"
            )

    @staticmethod
    def _compute_rsi(close: np.ndarray, period: int) -> np.ndarray:
        """Compute RSI using Wilder's smoothing (standard) with safe fallbacks.

        F-014 fix: Previously used ewm with alpha=1/period which produced
        permanent NaN values when the initial bars had no losses (avg_loss
        stays at 0 forever in ewm). Now uses Wilder's simple moving average
        for the initial seed + explicit 100 when avg_loss == 0 but avg_gain
        > 0 (perfect up-trend).
        """
        s = pd.Series(close, dtype=float)
        delta = s.diff()

        # Separate gains and losses
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)

        # Wilder's smoothing: first value is simple mean of period, then
        # recursive: new = (prev * (n-1) + current) / n
        n = period
        avg_gain = gain.rolling(window=n, min_periods=n).mean()
        avg_loss = loss.rolling(window=n, min_periods=n).mean()

        # Apply Wilder recursion AFTER the initial SMA seed
        # This yields slightly different values than ewm(alpha=1/n, adjust=False)
        # but matches TA-Lib / Wilder's definition.
        ag = avg_gain.to_numpy().copy()  # writable
        al = avg_loss.to_numpy().copy()
        gain_arr = gain.to_numpy()
        loss_arr = loss.to_numpy()
        for i in range(n + 1, len(ag)):
            if not np.isnan(ag[i - 1]):
                ag[i] = (ag[i - 1] * (n - 1) + gain_arr[i]) / n
                al[i] = (al[i - 1] * (n - 1) + loss_arr[i]) / n

        # Compute RSI with safe fallback
        rsi = np.full_like(ag, np.nan, dtype=float)
        for i in range(len(ag)):
            if np.isnan(ag[i]) or np.isnan(al[i]):
                continue
            if al[i] == 0 and ag[i] > 0:
                rsi[i] = 100.0  # F-014: pure up-trend → maximum RSI
            elif al[i] == 0 and ag[i] == 0:
                rsi[i] = 50.0  # F-014: flat market → neutral
            else:
                rs = ag[i] / al[i]
                rsi[i] = 100.0 - 100.0 / (1.0 + rs)
        return rsi

    def init(self) -> None:
        self.rsi = self.I(
            self._compute_rsi,
            self.data.Close,
            self.period,
            name=f"RSI({self.period})",
        )

    def next(self) -> None:
        if self.rsi[-1] < self.buy_threshold:
            if not self.position:
                self.buy()
        elif self.rsi[-1] > self.sell_threshold:
            if self.position:
                self.position.close()
