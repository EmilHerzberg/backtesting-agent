"""Volatility backtesting indicators: Bollinger Bands, ATR, Keltner Channels."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.backend.backtesting.indicators.base import BacktestIndicator, Signal
from src.backend.backtesting.indicators.registry import registry


# ======================================================================
# Bollinger Bands
# ======================================================================


class BollingerBandsIndicator(BacktestIndicator):
    """Bollinger Bands: SMA +/- *std_dev* standard deviations."""

    def __init__(self, period: int = 20, std_dev: float = 2.0) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        if std_dev <= 0:
            raise ValueError("std_dev must be > 0")
        self._period = period
        self._std_dev = std_dev

    @property
    def name(self) -> str:
        return f"BollingerBands({self._period},{self._std_dev})"

    def parameter_space(self) -> dict[str, dict[str, Any]]:
        return {
            "period": {"type": "int", "low": 10, "high": 50},
            "std_dev": {"type": "float", "low": 1.0, "high": 3.5},
        }

    def compute(self, df: pd.DataFrame) -> pd.Series:
        """Return the middle band (SMA) as the primary value."""
        self._validate_close(df)
        return df["Close"].rolling(window=self._period, min_periods=self._period).mean()

    def compute_full(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return DataFrame with middle, upper, lower bands."""
        self._validate_close(df)
        middle = df["Close"].rolling(window=self._period, min_periods=self._period).mean()
        std = df["Close"].rolling(window=self._period, min_periods=self._period).std()
        upper = middle + self._std_dev * std
        lower = middle - self._std_dev * std
        return pd.DataFrame(
            {"middle": middle, "upper": upper, "lower": lower},
            index=df.index,
        )

    def signal(self, df: pd.DataFrame) -> pd.Series:
        full = self.compute_full(df)
        close = df["Close"]
        signals = pd.Series(Signal.HOLD, index=df.index)
        signals[close < full["lower"]] = Signal.BUY
        signals[close > full["upper"]] = Signal.SELL
        signals[full["middle"].isna()] = Signal.HOLD
        return signals


# ======================================================================
# ATR (Average True Range)
# ======================================================================


class ATRIndicator(BacktestIndicator):
    """Average True Range -- a pure volatility measure, no direct BUY/SELL."""

    def __init__(self, period: int = 14) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self._period = period

    @property
    def name(self) -> str:
        return f"ATR({self._period})"

    def parameter_space(self) -> dict[str, dict[str, Any]]:
        return {"period": {"type": "int", "low": 7, "high": 30}}

    def compute(self, df: pd.DataFrame) -> pd.Series:
        self._validate_ohlcv(df)
        high = df["High"]
        low = df["Low"]
        close = df["Close"]

        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # H12: min_periods so ATR is NaN until converged.
        atr = true_range.ewm(alpha=1.0 / self._period, adjust=False, min_periods=self._period).mean()
        return atr

    def signal(self, df: pd.DataFrame) -> pd.Series:
        """ATR is a volatility filter, not a directional signal.

        High ATR (above its own 50-period SMA) -> HOLD (volatile, caution).
        Low ATR -> HOLD as well. Always returns HOLD.
        """
        return pd.Series(Signal.HOLD, index=df.index)


# ======================================================================
# Keltner Channels
# ======================================================================


class KeltnerChannelsIndicator(BacktestIndicator):
    """Keltner Channels: EMA +/- *multiplier* x ATR."""

    def __init__(
        self,
        ema_period: int = 20,
        atr_period: int = 14,
        multiplier: float = 2.0,
    ) -> None:
        if ema_period < 1 or atr_period < 1:
            raise ValueError("All periods must be >= 1")
        if multiplier <= 0:
            raise ValueError("multiplier must be > 0")
        self._ema_period = ema_period
        self._atr_period = atr_period
        self._multiplier = multiplier

    @property
    def name(self) -> str:
        return f"Keltner({self._ema_period},{self._atr_period},{self._multiplier})"

    def parameter_space(self) -> dict[str, dict[str, Any]]:
        return {
            "ema_period": {"type": "int", "low": 10, "high": 40},
            "atr_period": {"type": "int", "low": 7, "high": 20},
            "multiplier": {"type": "float", "low": 1.0, "high": 3.0},
        }

    def _atr(self, df: pd.DataFrame) -> pd.Series:
        high = df["High"]
        low = df["Low"]
        close = df["Close"]
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        # H12: min_periods so ATR is NaN until converged.
        return true_range.ewm(
            alpha=1.0 / self._atr_period, adjust=False, min_periods=self._atr_period
        ).mean()

    def compute(self, df: pd.DataFrame) -> pd.Series:
        """Return the middle line (EMA) as the primary value."""
        self._validate_ohlcv(df)
        return df["Close"].ewm(span=self._ema_period, adjust=False, min_periods=self._ema_period).mean()

    def compute_full(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return DataFrame with middle, upper, lower channels."""
        self._validate_ohlcv(df)
        middle = df["Close"].ewm(span=self._ema_period, adjust=False, min_periods=self._ema_period).mean()
        atr = self._atr(df)
        upper = middle + self._multiplier * atr
        lower = middle - self._multiplier * atr
        return pd.DataFrame(
            {"middle": middle, "upper": upper, "lower": lower},
            index=df.index,
        )

    def signal(self, df: pd.DataFrame) -> pd.Series:
        """Breakout signals: close > upper = BUY, close < lower = SELL."""
        full = self.compute_full(df)
        close = df["Close"]
        signals = pd.Series(Signal.HOLD, index=df.index)
        signals[close > full["upper"]] = Signal.BUY
        signals[close < full["lower"]] = Signal.SELL
        # H12: no breakout signal while the EMA/ATR channel is still warming up.
        signals[full["middle"].isna() | full["upper"].isna()] = Signal.HOLD
        return signals


# ------------------------------------------------------------------
# Auto-registration
# ------------------------------------------------------------------

registry.register("BOLLINGER", BollingerBandsIndicator)
registry.register("ATR", ATRIndicator)
registry.register("KELTNER", KeltnerChannelsIndicator)
