"""Volume-based backtesting indicators: OBV, VWAP, Volume Profile."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.backend.backtesting.indicators.base import BacktestIndicator, Signal
from src.backend.backtesting.indicators.registry import registry


# ======================================================================
# OBV (On-Balance Volume)
# ======================================================================


class OBVIndicator(BacktestIndicator):
    """On-Balance Volume: cumulative volume based on price direction."""

    def __init__(self) -> None:
        pass

    @property
    def name(self) -> str:
        return "OBV"

    def parameter_space(self) -> dict[str, dict[str, Any]]:
        # OBV has no tuneable parameters; return empty space.
        return {}

    def compute(self, df: pd.DataFrame) -> pd.Series:
        self._validate_ohlcv(df)
        direction = np.sign(df["Close"].diff())
        # First value has no previous close, set direction to 0
        direction.iloc[0] = 0
        obv = (direction * df["Volume"]).cumsum()
        return obv

    def signal(self, df: pd.DataFrame) -> pd.Series:
        """BUY when OBV is rising (above its 20-period SMA), SELL when falling."""
        obv = self.compute(df)
        obv_sma = obv.rolling(window=20, min_periods=20).mean()

        signals = pd.Series(Signal.HOLD, index=df.index)
        signals[obv > obv_sma] = Signal.BUY
        signals[obv < obv_sma] = Signal.SELL
        signals[obv_sma.isna()] = Signal.HOLD
        return signals


# ======================================================================
# VWAP (Volume-Weighted Average Price)
# ======================================================================


class VWAPIndicator(BacktestIndicator):
    """Intraday-style cumulative VWAP (resets are not applied here)."""

    def __init__(self) -> None:
        pass

    @property
    def name(self) -> str:
        return "VWAP"

    def parameter_space(self) -> dict[str, dict[str, Any]]:
        return {}

    def compute(self, df: pd.DataFrame) -> pd.Series:
        self._validate_ohlcv(df)
        typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
        cum_tp_vol = (typical_price * df["Volume"]).cumsum()
        cum_vol = df["Volume"].cumsum().replace(0, np.nan)
        vwap = cum_tp_vol / cum_vol
        return vwap

    def signal(self, df: pd.DataFrame) -> pd.Series:
        vwap = self.compute(df)
        close = df["Close"]
        signals = pd.Series(Signal.HOLD, index=df.index)
        signals[close > vwap] = Signal.BUY
        signals[close < vwap] = Signal.SELL
        signals[vwap.isna()] = Signal.HOLD
        return signals


# ======================================================================
# Volume Profile (Point of Control)
# ======================================================================


class VolumeProfileIndicator(BacktestIndicator):
    """Rolling Volume Profile returning the Point of Control (POC).

    The POC is the price level with the highest traded volume in a
    rolling window. The price range is split into *bins* equal buckets.
    """

    def __init__(self, bins: int = 20) -> None:
        if bins < 2:
            raise ValueError("bins must be >= 2")
        self._bins = bins

    @property
    def name(self) -> str:
        return f"VolumeProfile({self._bins})"

    def parameter_space(self) -> dict[str, dict[str, Any]]:
        return {"bins": {"type": "int", "low": 10, "high": 50}}

    def compute(self, df: pd.DataFrame) -> pd.Series:
        """Return a rolling POC price for every row.

        Uses a 50-bar lookback window for the volume profile.
        """
        self._validate_ohlcv(df)
        lookback = 50
        poc = pd.Series(np.nan, index=df.index)

        close_arr = df["Close"].values
        volume_arr = df["Volume"].values

        for i in range(lookback, len(df)):
            window_close = close_arr[i - lookback : i + 1]
            window_vol = volume_arr[i - lookback : i + 1]

            price_min = window_close.min()
            price_max = window_close.max()
            if price_max == price_min:
                poc.iloc[i] = price_min
                continue

            bin_edges = np.linspace(price_min, price_max, self._bins + 1)
            bin_indices = np.digitize(window_close, bin_edges) - 1
            bin_indices = np.clip(bin_indices, 0, self._bins - 1)

            bin_vol = np.zeros(self._bins)
            for bi, vol in zip(bin_indices, window_vol):
                bin_vol[bi] += vol

            max_bin = int(np.argmax(bin_vol))
            poc.iloc[i] = (bin_edges[max_bin] + bin_edges[max_bin + 1]) / 2

        return poc

    def signal(self, df: pd.DataFrame) -> pd.Series:
        """Price near POC -> HOLD; above -> BUY; below -> SELL."""
        poc = self.compute(df)
        close = df["Close"]
        # Use 0.5% tolerance around POC for "near"
        tolerance = poc * 0.005

        signals = pd.Series(Signal.HOLD, index=df.index)
        signals[close > poc + tolerance] = Signal.BUY
        signals[close < poc - tolerance] = Signal.SELL
        signals[poc.isna()] = Signal.HOLD
        return signals


# ------------------------------------------------------------------
# Auto-registration
# ------------------------------------------------------------------

registry.register("OBV", OBVIndicator)
registry.register("VWAP", VWAPIndicator)
registry.register("VOLUMEPROFILE", VolumeProfileIndicator)
