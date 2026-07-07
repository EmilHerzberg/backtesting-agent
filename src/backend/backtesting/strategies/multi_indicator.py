"""Multi-Indicator strategy combining RSI + SMA for backtesting.py."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.backend.backtesting.strategies.base import StrategyBase


class MultiIndicator(StrategyBase):
    """Combined RSI + SMA trend-confirmation strategy.

    Buys when RSI is below ``rsi_buy`` *and* price is above the SMA
    (trend confirmation).  Sells (closes position) when RSI exceeds
    ``rsi_sell`` *or* price drops below the SMA.
    """

    sma_period: int = 50
    rsi_period: int = 14
    rsi_buy: float = 30.0
    rsi_sell: float = 70.0

    @classmethod
    def parameter_space(cls) -> dict[str, dict[str, Any]]:
        return {
            "sma_period": {"type": "int", "low": 20, "high": 200},
            "rsi_period": {"type": "int", "low": 5, "high": 30},
            "rsi_buy": {"type": "float", "low": 15.0, "high": 40.0},
            "rsi_sell": {"type": "float", "low": 60.0, "high": 85.0},
        }

    @classmethod
    def validate_params(cls, params: dict[str, Any]) -> None:
        """F-020 fix: enforce rsi_sell > rsi_buy + 10."""
        from src.backend.backtesting.engine.exceptions import InvalidParameterError
        buy = params.get("rsi_buy", cls.rsi_buy)
        sell = params.get("rsi_sell", cls.rsi_sell)
        if sell <= buy + 10:
            raise InvalidParameterError(
                f"MultiIndicator requires rsi_sell > rsi_buy + 10 "
                f"(got rsi_buy={buy}, rsi_sell={sell})"
            )

    @staticmethod
    def _compute_sma(close: np.ndarray, period: int) -> np.ndarray:
        s = pd.Series(close)
        return s.rolling(window=period, min_periods=period).mean().values

    @staticmethod
    def _compute_rsi(close: np.ndarray, period: int) -> np.ndarray:
        s = pd.Series(close)
        delta = s.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100.0 - 100.0 / (1.0 + rs)
        return rsi.values

    def init(self) -> None:
        close = self.data.Close
        self.sma = self.I(
            self._compute_sma, close, self.sma_period,
            name=f"SMA({self.sma_period})",
        )
        self.rsi = self.I(
            self._compute_rsi, close, self.rsi_period,
            name=f"RSI({self.rsi_period})",
        )

    def next(self) -> None:
        price = self.data.Close[-1]
        rsi_val = self.rsi[-1]
        sma_val = self.sma[-1]

        # Skip if indicator values are not yet available (NaN)
        if np.isnan(rsi_val) or np.isnan(sma_val):
            return

        if not self.position:
            # Buy when RSI is oversold AND price is above SMA (uptrend)
            if rsi_val < self.rsi_buy and price > sma_val:
                self._gated_buy()   # H13: through the event gate (no-op when unconfigured)
        else:
            # Sell when RSI is overbought OR price falls below SMA
            if rsi_val > self.rsi_sell or price < sma_val:
                self.position.close()
