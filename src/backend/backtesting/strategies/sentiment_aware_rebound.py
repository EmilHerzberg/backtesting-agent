"""SentimentAwareReboundStrategy — reference E2E strategy (TRD-DATA-1009 / ATS-1173).

Long-only intraday rebound strategy that combines technical mean-reversion
(RSI + Bollinger lower-band) with news-sentiment and earnings-window
filters. Designed to validate the AV pipeline end-to-end; NOT a production
strategy.

Entry (all must be true):
    rsi_14 < rsi_oversold (default 35)
    close < bollinger_lower
    sentiment_score_24h >= -0.1
    news_count_24h > 0
    is_pre_earnings_window == False
    is_post_earnings_window == False
    market_regime != "BEARISH"

Exit (any triggers close):
    take_profit reached  (default +0.8%)
    stop_loss hit        (default -0.5%)
    rsi_14 > rsi_overbought (default 55)
    held for >= max_holding_bars (default 16, ~4h on 15m)

The DataFrame passed to Backtest() must include:
    - "Open", "High", "Low", "Close", "Volume"  (capitalized — backtesting.py
      requirement)
    - "rsi_14", "bollinger_lower"
    - "sentiment_score_24h", "news_count_24h"
    - "is_pre_earnings_window", "is_post_earnings_window"
    - "market_regime"
i.e. FeatureFrame from BacktestDataService.get_feature_frame() with
columns renamed via DataFrame.rename(columns=str.capitalize) for OHLC.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from src.backend.backtesting.strategies.base import StrategyBase


class SentimentAwareReboundStrategy(StrategyBase):
    """Reference rebound strategy using AV-derived features."""

    # --- entry thresholds ---
    rsi_oversold: int = 35
    sentiment_floor: float = -0.1
    require_news: bool = True
    block_pre_earnings: bool = True
    block_post_earnings: bool = True
    block_bearish_regime: bool = True

    # --- exit thresholds ---
    take_profit_pct: float = 0.008  # +0.8%
    stop_loss_pct: float = 0.005    # -0.5%
    rsi_overbought: int = 55
    max_holding_bars: int = 16

    @classmethod
    def parameter_space(cls) -> dict[str, dict[str, Any]]:
        return {
            "rsi_oversold": {"type": "int", "low": 20, "high": 40},
            "rsi_overbought": {"type": "int", "low": 50, "high": 70},
            "take_profit_pct": {"type": "float", "low": 0.003, "high": 0.020},
            "stop_loss_pct": {"type": "float", "low": 0.002, "high": 0.010},
            "max_holding_bars": {"type": "int", "low": 4, "high": 32},
            "sentiment_floor": {"type": "float", "low": -0.5, "high": 0.2},
        }

    @classmethod
    def validate_params(cls, params: dict[str, Any]) -> None:
        from src.backend.backtesting.engine.exceptions import InvalidParameterError
        oversold = params.get("rsi_oversold", cls.rsi_oversold)
        overbought = params.get("rsi_overbought", cls.rsi_overbought)
        if oversold >= overbought:
            raise InvalidParameterError(
                f"rsi_oversold ({oversold}) must be < rsi_overbought ({overbought})"
            )
        tp = params.get("take_profit_pct", cls.take_profit_pct)
        sl = params.get("stop_loss_pct", cls.stop_loss_pct)
        if tp <= 0 or sl <= 0:
            raise InvalidParameterError(
                f"take_profit_pct and stop_loss_pct must be > 0 (got tp={tp}, sl={sl})"
            )

    def init(self) -> None:
        # Pull feature columns into indicator series so backtesting.py keeps
        # them aligned and accessible per-bar via self.<name>[-1].
        self.rsi = self.I(self._passthrough, np.asarray(self.data.rsi_14, dtype=float),
                          name="RSI")
        self.bb_lower = self.I(self._passthrough,
                               np.asarray(self.data.bollinger_lower, dtype=float),
                               name="BB_lower")
        self.sentiment = self.I(self._passthrough,
                                np.asarray(self.data.sentiment_score_24h, dtype=float),
                                name="Sentiment24h")
        self.news_count = self.I(self._passthrough,
                                 np.asarray(self.data.news_count_24h, dtype=float),
                                 name="NewsCount24h")
        self.pre_earn = self.I(self._passthrough,
                               np.asarray(self.data.is_pre_earnings_window, dtype=float),
                               name="PreEarn")
        self.post_earn = self.I(self._passthrough,
                                np.asarray(self.data.is_post_earnings_window, dtype=float),
                                name="PostEarn")
        # market_regime is categorical; we store it as a string array
        self._regime = np.asarray(self.data.market_regime, dtype=object)
        self._entry_bar: int | None = None
        self._entry_price: float | None = None

    @staticmethod
    def _passthrough(arr: np.ndarray) -> np.ndarray:
        return arr

    def next(self) -> None:
        i = len(self.data) - 1
        price = float(self.data.Close[-1])
        rsi = float(self.rsi[-1]) if not np.isnan(self.rsi[-1]) else 50.0
        bb_lo = float(self.bb_lower[-1]) if not np.isnan(self.bb_lower[-1]) else price
        sent = float(self.sentiment[-1]) if not np.isnan(self.sentiment[-1]) else 0.0
        news_n = float(self.news_count[-1]) if not np.isnan(self.news_count[-1]) else 0.0
        pre_earn = bool(self.pre_earn[-1])
        post_earn = bool(self.post_earn[-1])
        regime = str(self._regime[i]) if i < len(self._regime) else ""

        # --- exits first ---
        if self.position:
            assert self._entry_bar is not None and self._entry_price is not None
            held = i - self._entry_bar
            ret = price / self._entry_price - 1.0
            if ret >= self.take_profit_pct:
                self.position.close()
                self._entry_bar = None
                self._entry_price = None
                return
            if ret <= -self.stop_loss_pct:
                self.position.close()
                self._entry_bar = None
                self._entry_price = None
                return
            if rsi > self.rsi_overbought:
                self.position.close()
                self._entry_bar = None
                self._entry_price = None
                return
            if held >= self.max_holding_bars:
                self.position.close()
                self._entry_bar = None
                self._entry_price = None
                return
            return

        # --- entries ---
        if rsi >= self.rsi_oversold:
            return
        if price >= bb_lo:
            return
        if sent < self.sentiment_floor:
            return
        if self.require_news and news_n <= 0:
            return
        if self.block_pre_earnings and pre_earn:
            return
        if self.block_post_earnings and post_earn:
            return
        if self.block_bearish_regime and regime == "BEARISH":
            return

        self.buy()
        self._entry_bar = i
        self._entry_price = price
