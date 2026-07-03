from __future__ import annotations

from decimal import Decimal

from src.backend.indicators.interface import IIndicator, Signal


class EMA(IIndicator):
    """Exponential Moving Average.

    Buy when price crosses above EMA, sell when below.
    """

    def __init__(self, period: int = 20) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self._period = period
        self._multiplier = Decimal(2) / (Decimal(period) + Decimal(1))

    @property
    def name(self) -> str:
        return f"EMA({self._period})"

    @property
    def min_periods(self) -> int:
        return self._period

    def calculate(self, prices: list[Decimal]) -> Decimal | None:
        if len(prices) < self._period:
            return None
        return self._compute_ema(prices)

    def _compute_ema(self, prices: list[Decimal]) -> Decimal:
        # Seed with SMA of first `period` prices
        ema = sum(prices[: self._period]) / self._period
        for price in prices[self._period :]:
            ema = (price - ema) * self._multiplier + ema
        return ema

    def signal(self, prices: list[Decimal]) -> Signal:
        if len(prices) < self._period + 1:
            return Signal.HOLD
        current_price = prices[-1]
        ema_now = self.calculate(prices)
        ema_prev = self.calculate(prices[:-1])
        if ema_now is None or ema_prev is None:
            return Signal.HOLD
        if current_price > ema_now and prices[-2] <= ema_prev:
            return Signal.BUY
        if current_price < ema_now and prices[-2] >= ema_prev:
            return Signal.SELL
        return Signal.HOLD
