from __future__ import annotations

from decimal import Decimal

from src.backend.indicators.interface import IIndicator, Signal

_ZERO = Decimal("0")


class RSI(IIndicator):
    """Relative Strength Index.

    RSI < oversold (default 30) -> BUY
    RSI > overbought (default 70) -> SELL
    """

    def __init__(
        self,
        period: int = 14,
        overbought: Decimal = Decimal("70"),
        oversold: Decimal = Decimal("30"),
    ) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self._period = period
        self._overbought = overbought
        self._oversold = oversold

    @property
    def name(self) -> str:
        return f"RSI({self._period})"

    @property
    def min_periods(self) -> int:
        return self._period + 1  # Need period+1 prices for period changes

    def calculate(self, prices: list[Decimal]) -> Decimal | None:
        if len(prices) < self._period + 1:
            return None

        changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

        # Initial average gain/loss from first `period` changes
        gains = [c if c > _ZERO else _ZERO for c in changes[: self._period]]
        losses = [-c if c < _ZERO else _ZERO for c in changes[: self._period]]

        avg_gain = sum(gains) / self._period
        avg_loss = sum(losses) / self._period

        # Smooth with remaining changes
        for c in changes[self._period :]:
            gain = c if c > _ZERO else _ZERO
            loss = -c if c < _ZERO else _ZERO
            avg_gain = (avg_gain * (self._period - 1) + gain) / self._period
            avg_loss = (avg_loss * (self._period - 1) + loss) / self._period

        if avg_loss == _ZERO:
            return Decimal("100")

        rs = avg_gain / avg_loss
        rsi = Decimal("100") - Decimal("100") / (Decimal("1") + rs)
        return rsi

    def signal(self, prices: list[Decimal]) -> Signal:
        rsi = self.calculate(prices)
        if rsi is None:
            return Signal.HOLD
        if rsi <= self._oversold:
            return Signal.BUY
        if rsi >= self._overbought:
            return Signal.SELL
        return Signal.HOLD
