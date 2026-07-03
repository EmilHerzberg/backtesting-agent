"""Trend-following backtesting indicators: SMA, EMA, MACD, ADX, Ichimoku."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.backend.backtesting.indicators.base import BacktestIndicator, Signal
from src.backend.backtesting.indicators.registry import registry


# ======================================================================
# SMA
# ======================================================================


class SMAIndicator(BacktestIndicator):
    """Simple Moving Average of the Close price."""

    def __init__(self, period: int = 20) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self._period = period

    @property
    def name(self) -> str:
        return f"SMA({self._period})"

    def parameter_space(self) -> dict[str, dict[str, Any]]:
        return {"period": {"type": "int", "low": 5, "high": 200}}

    def compute(self, df: pd.DataFrame) -> pd.Series:
        self._validate_close(df)
        return df["Close"].rolling(window=self._period, min_periods=self._period).mean()

    def signal(self, df: pd.DataFrame) -> pd.Series:
        self._validate_close(df)
        sma = self.compute(df)
        close = df["Close"]
        signals = pd.Series(Signal.HOLD, index=df.index)
        signals[close > sma] = Signal.BUY
        signals[close < sma] = Signal.SELL
        signals[sma.isna()] = Signal.HOLD
        return signals


# ======================================================================
# EMA
# ======================================================================


class EMAIndicator(BacktestIndicator):
    """Exponential Moving Average of the Close price."""

    def __init__(self, period: int = 20) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self._period = period

    @property
    def name(self) -> str:
        return f"EMA({self._period})"

    def parameter_space(self) -> dict[str, dict[str, Any]]:
        return {"period": {"type": "int", "low": 5, "high": 200}}

    def compute(self, df: pd.DataFrame) -> pd.Series:
        self._validate_close(df)
        return df["Close"].ewm(span=self._period, adjust=False).mean()

    def signal(self, df: pd.DataFrame) -> pd.Series:
        self._validate_close(df)
        ema = self.compute(df)
        close = df["Close"]
        signals = pd.Series(Signal.HOLD, index=df.index)
        signals[close > ema] = Signal.BUY
        signals[close < ema] = Signal.SELL
        signals[ema.isna()] = Signal.HOLD
        return signals


# ======================================================================
# MACD
# ======================================================================


class MACDIndicator(BacktestIndicator):
    """Moving Average Convergence Divergence."""

    def __init__(
        self,
        fast: int = 12,
        slow: int = 26,
        signal_period: int = 9,
    ) -> None:
        if fast < 1 or slow < 1 or signal_period < 1:
            raise ValueError("All periods must be >= 1")
        if fast >= slow:
            raise ValueError("fast must be < slow")
        self._fast = fast
        self._slow = slow
        self._signal_period = signal_period

    @property
    def name(self) -> str:
        return f"MACD({self._fast},{self._slow},{self._signal_period})"

    def parameter_space(self) -> dict[str, dict[str, Any]]:
        return {
            "fast": {"type": "int", "low": 5, "high": 20},
            "slow": {"type": "int", "low": 20, "high": 50},
            "signal_period": {"type": "int", "low": 5, "high": 15},
        }

    def compute(self, df: pd.DataFrame) -> pd.Series:
        """Return the MACD line (fast EMA - slow EMA)."""
        self._validate_close(df)
        fast_ema = df["Close"].ewm(span=self._fast, adjust=False).mean()
        slow_ema = df["Close"].ewm(span=self._slow, adjust=False).mean()
        return fast_ema - slow_ema

    def compute_full(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return DataFrame with columns macd, signal, histogram."""
        macd_line = self.compute(df)
        signal_line = macd_line.ewm(span=self._signal_period, adjust=False).mean()
        histogram = macd_line - signal_line
        return pd.DataFrame(
            {"macd": macd_line, "signal": signal_line, "histogram": histogram},
            index=df.index,
        )

    def signal(self, df: pd.DataFrame) -> pd.Series:
        self._validate_close(df)
        full = self.compute_full(df)
        macd_line = full["macd"]
        signal_line = full["signal"]

        # Cross detection: MACD crosses above / below signal line
        above = macd_line > signal_line
        cross_up = above & ~above.shift(1, fill_value=False)
        cross_down = ~above & above.shift(1, fill_value=True)

        signals = pd.Series(Signal.HOLD, index=df.index)
        signals[cross_up] = Signal.BUY
        signals[cross_down] = Signal.SELL
        return signals


# ======================================================================
# ADX  (Average Directional Index)
# ======================================================================


class ADXIndicator(BacktestIndicator):
    """Average Directional Index computed from High / Low / Close."""

    def __init__(self, period: int = 14) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self._period = period

    @property
    def name(self) -> str:
        return f"ADX({self._period})"

    def parameter_space(self) -> dict[str, dict[str, Any]]:
        return {"period": {"type": "int", "low": 7, "high": 30}}

    def compute(self, df: pd.DataFrame) -> pd.Series:
        """Return the ADX series."""
        self._validate_ohlcv(df)
        high = df["High"]
        low = df["Low"]
        close = df["Close"]

        plus_dm = high.diff()
        minus_dm = -low.diff()

        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr = true_range.ewm(alpha=1.0 / self._period, adjust=False).mean()
        plus_di = 100 * plus_dm.ewm(alpha=1.0 / self._period, adjust=False).mean() / atr
        minus_di = 100 * minus_dm.ewm(alpha=1.0 / self._period, adjust=False).mean() / atr

        dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
        adx = dx.ewm(alpha=1.0 / self._period, adjust=False).mean()
        return adx

    def signal(self, df: pd.DataFrame) -> pd.Series:
        """ADX > 25 indicates a trending market (BUY bias); otherwise HOLD."""
        adx = self.compute(df)
        signals = pd.Series(Signal.HOLD, index=df.index)
        signals[adx > 25] = Signal.BUY
        signals[adx.isna()] = Signal.HOLD
        return signals


# ======================================================================
# Ichimoku Cloud
# ======================================================================


class IchimokuIndicator(BacktestIndicator):
    """Ichimoku Kinko Hyo cloud indicator."""

    def __init__(
        self,
        tenkan: int = 9,
        kijun: int = 26,
        senkou_b: int = 52,
    ) -> None:
        if tenkan < 1 or kijun < 1 or senkou_b < 1:
            raise ValueError("All periods must be >= 1")
        self._tenkan = tenkan
        self._kijun = kijun
        self._senkou_b = senkou_b

    @property
    def name(self) -> str:
        return f"Ichimoku({self._tenkan},{self._kijun},{self._senkou_b})"

    def parameter_space(self) -> dict[str, dict[str, Any]]:
        return {
            "tenkan": {"type": "int", "low": 5, "high": 20},
            "kijun": {"type": "int", "low": 20, "high": 40},
            "senkou_b": {"type": "int", "low": 40, "high": 80},
        }

    def _donchian(self, series_h: pd.Series, series_l: pd.Series, period: int) -> pd.Series:
        """Donchian mid-line: (highest-high + lowest-low) / 2 over *period*."""
        return (
            series_h.rolling(window=period, min_periods=period).max()
            + series_l.rolling(window=period, min_periods=period).min()
        ) / 2

    def compute(self, df: pd.DataFrame) -> pd.Series:
        """Return Senkou Span A (leading span A) as the primary value."""
        self._validate_ohlcv(df)
        tenkan_sen = self._donchian(df["High"], df["Low"], self._tenkan)
        kijun_sen = self._donchian(df["High"], df["Low"], self._kijun)
        senkou_a = ((tenkan_sen + kijun_sen) / 2).shift(self._kijun)
        return senkou_a

    def compute_full(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return all Ichimoku components."""
        self._validate_ohlcv(df)
        tenkan_sen = self._donchian(df["High"], df["Low"], self._tenkan)
        kijun_sen = self._donchian(df["High"], df["Low"], self._kijun)
        senkou_a = ((tenkan_sen + kijun_sen) / 2).shift(self._kijun)
        senkou_b = self._donchian(df["High"], df["Low"], self._senkou_b).shift(self._kijun)
        chikou = df["Close"].shift(-self._kijun)
        return pd.DataFrame(
            {
                "tenkan": tenkan_sen,
                "kijun": kijun_sen,
                "senkou_a": senkou_a,
                "senkou_b": senkou_b,
                "chikou": chikou,
            },
            index=df.index,
        )

    def signal(self, df: pd.DataFrame) -> pd.Series:
        """Price above the cloud -> BUY, below -> SELL, inside -> HOLD."""
        full = self.compute_full(df)
        close = df["Close"]
        cloud_top = full[["senkou_a", "senkou_b"]].max(axis=1)
        cloud_bottom = full[["senkou_a", "senkou_b"]].min(axis=1)

        signals = pd.Series(Signal.HOLD, index=df.index)
        signals[close > cloud_top] = Signal.BUY
        signals[close < cloud_bottom] = Signal.SELL
        signals[cloud_top.isna() | cloud_bottom.isna()] = Signal.HOLD
        return signals


# ------------------------------------------------------------------
# Auto-registration
# ------------------------------------------------------------------

registry.register("SMA", SMAIndicator)
registry.register("EMA", EMAIndicator)
registry.register("MACD", MACDIndicator)
registry.register("ADX", ADXIndicator)
registry.register("ICHIMOKU", IchimokuIndicator)
