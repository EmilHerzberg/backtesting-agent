from __future__ import annotations

from decimal import Decimal

from src.backend.indicators.interface import IIndicator, Signal


class SMA(IIndicator):
    """Simple Moving Average.

    Buy when price crosses above SMA, sell when below.
    """

    def __init__(self, period: int = 20) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self._period = period

    @property
    def name(self) -> str:
        return f"SMA({self._period})"

    @property
    def min_periods(self) -> int:
        return self._period

    def calculate(self, prices: list[Decimal]) -> Decimal | None:
        if len(prices) < self._period:
            return None
        window = prices[-self._period :]
        return sum(window) / self._period

    def signal(self, prices: list[Decimal]) -> Signal:
        if len(prices) < self._period + 1:
            return Signal.HOLD
        current_price = prices[-1]
        sma_now = self.calculate(prices)
        sma_prev = self.calculate(prices[:-1])
        if sma_now is None or sma_prev is None:
            return Signal.HOLD
        # Price crosses above SMA -> BUY
        if current_price > sma_now and prices[-2] <= sma_prev:
            return Signal.BUY
        # Price crosses below SMA -> SELL
        if current_price < sma_now and prices[-2] >= sma_prev:
            return Signal.SELL
        return Signal.HOLD
