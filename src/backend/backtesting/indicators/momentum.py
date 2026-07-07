"""Momentum backtesting indicators: RSI, Stochastic, CCI, Williams %R."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.backend.backtesting.indicators.base import BacktestIndicator, Signal
from src.backend.backtesting.indicators.registry import registry


# ======================================================================
# RSI
# ======================================================================


class RSIIndicator(BacktestIndicator):
    """Relative Strength Index."""

    def __init__(
        self,
        period: int = 14,
        overbought: float = 70.0,
        oversold: float = 30.0,
    ) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        if not (0 <= oversold < overbought <= 100):
            raise ValueError("Must have 0 <= oversold < overbought <= 100")
        self._period = period
        self._overbought = overbought
        self._oversold = oversold

    @property
    def name(self) -> str:
        return f"RSI({self._period})"

    def parameter_space(self) -> dict[str, dict[str, Any]]:
        return {
            "period": {"type": "int", "low": 5, "high": 30},
            "overbought": {"type": "float", "low": 65.0, "high": 85.0},
            "oversold": {"type": "float", "low": 15.0, "high": 35.0},
        }

    def compute(self, df: pd.DataFrame) -> pd.Series:
        self._validate_close(df)
        delta = df["Close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)

        # H12: min_periods so the EWM is NaN (not a garbage value) until it has converged — otherwise
        # RSI emits directional signals from bar 1 on an unwarmed average.
        avg_gain = gain.ewm(alpha=1.0 / self._period, adjust=False, min_periods=self._period).mean()
        avg_loss = loss.ewm(alpha=1.0 / self._period, adjust=False, min_periods=self._period).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100.0 - 100.0 / (1.0 + rs)
        # M16 (F-014): no losses yet (avg_loss == 0) means RSI is 100 (fully overbought), NOT NaN → HOLD.
        # Otherwise a perfect uptrend never registers as overbought and never emits SELL. The true
        # warm-up region (avg_loss NaN via min_periods) stays NaN and is masked to HOLD by signal().
        rsi = rsi.where(~((avg_loss == 0) & avg_gain.notna()), 100.0)
        return rsi

    def signal(self, df: pd.DataFrame) -> pd.Series:
        rsi = self.compute(df)
        signals = pd.Series(Signal.HOLD, index=df.index)
        signals[rsi <= self._oversold] = Signal.BUY
        signals[rsi >= self._overbought] = Signal.SELL
        signals[rsi.isna()] = Signal.HOLD
        return signals


# ======================================================================
# Stochastic Oscillator
# ======================================================================


class StochasticIndicator(BacktestIndicator):
    """Stochastic Oscillator (%K / %D)."""

    def __init__(
        self,
        k_period: int = 14,
        d_period: int = 3,
        slowing: int = 3,
    ) -> None:
        if k_period < 1 or d_period < 1 or slowing < 1:
            raise ValueError("All periods must be >= 1")
        self._k_period = k_period
        self._d_period = d_period
        self._slowing = slowing

    @property
    def name(self) -> str:
        return f"Stochastic({self._k_period},{self._d_period},{self._slowing})"

    def parameter_space(self) -> dict[str, dict[str, Any]]:
        return {
            "k_period": {"type": "int", "low": 5, "high": 21},
            "d_period": {"type": "int", "low": 2, "high": 7},
            "slowing": {"type": "int", "low": 1, "high": 5},
        }

    def compute(self, df: pd.DataFrame) -> pd.Series:
        """Return the %K line (slowed)."""
        self._validate_ohlcv(df)
        lowest_low = df["Low"].rolling(window=self._k_period, min_periods=self._k_period).min()
        highest_high = df["High"].rolling(window=self._k_period, min_periods=self._k_period).max()

        raw_k = 100 * (df["Close"] - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)
        # Apply slowing (SMA of raw %K)
        k = raw_k.rolling(window=self._slowing, min_periods=self._slowing).mean()
        return k

    def compute_full(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return DataFrame with %K and %D."""
        k = self.compute(df)
        d = k.rolling(window=self._d_period, min_periods=self._d_period).mean()
        return pd.DataFrame({"k": k, "d": d}, index=df.index)

    def signal(self, df: pd.DataFrame) -> pd.Series:
        """BUY when %K crosses above %D below 20; SELL when crosses below above 80."""
        full = self.compute_full(df)
        k, d = full["k"], full["d"]

        above = k > d
        cross_up = above & ~above.shift(1, fill_value=False)
        cross_down = ~above & above.shift(1, fill_value=True)

        signals = pd.Series(Signal.HOLD, index=df.index)
        signals[cross_up & (k < 20)] = Signal.BUY
        signals[cross_down & (k > 80)] = Signal.SELL
        signals[k.isna()] = Signal.HOLD
        return signals


# ======================================================================
# CCI (Commodity Channel Index)
# ======================================================================


class CCIIndicator(BacktestIndicator):
    """Commodity Channel Index."""

    def __init__(self, period: int = 20) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self._period = period

    @property
    def name(self) -> str:
        return f"CCI({self._period})"

    def parameter_space(self) -> dict[str, dict[str, Any]]:
        return {"period": {"type": "int", "low": 10, "high": 40}}

    def compute(self, df: pd.DataFrame) -> pd.Series:
        self._validate_ohlcv(df)
        typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
        sma = typical_price.rolling(window=self._period, min_periods=self._period).mean()
        mad = typical_price.rolling(window=self._period, min_periods=self._period).apply(
            lambda x: np.abs(x - x.mean()).mean(), raw=True
        )
        cci = (typical_price - sma) / (0.015 * mad)
        return cci

    def signal(self, df: pd.DataFrame) -> pd.Series:
        cci = self.compute(df)
        signals = pd.Series(Signal.HOLD, index=df.index)
        signals[cci < -100] = Signal.BUY
        signals[cci > 100] = Signal.SELL
        signals[cci.isna()] = Signal.HOLD
        return signals


# ======================================================================
# Williams %R
# ======================================================================


class WilliamsRIndicator(BacktestIndicator):
    """Williams %R momentum indicator."""

    def __init__(self, period: int = 14) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self._period = period

    @property
    def name(self) -> str:
        return f"WilliamsR({self._period})"

    def parameter_space(self) -> dict[str, dict[str, Any]]:
        return {"period": {"type": "int", "low": 5, "high": 30}}

    def compute(self, df: pd.DataFrame) -> pd.Series:
        self._validate_ohlcv(df)
        highest_high = df["High"].rolling(window=self._period, min_periods=self._period).max()
        lowest_low = df["Low"].rolling(window=self._period, min_periods=self._period).min()
        wr = -100 * (highest_high - df["Close"]) / (highest_high - lowest_low).replace(0, np.nan)
        return wr

    def signal(self, df: pd.DataFrame) -> pd.Series:
        wr = self.compute(df)
        signals = pd.Series(Signal.HOLD, index=df.index)
        signals[wr < -80] = Signal.BUY
        signals[wr > -20] = Signal.SELL
        signals[wr.isna()] = Signal.HOLD
        return signals


# ------------------------------------------------------------------
# Auto-registration
# ------------------------------------------------------------------

registry.register("RSI", RSIIndicator)
registry.register("STOCHASTIC", StochasticIndicator)
registry.register("CCI", CCIIndicator)
registry.register("WILLIAMSR", WilliamsRIndicator)
