from __future__ import annotations

from decimal import Decimal

from src.backend.indicators.interface import IIndicator, Signal


class MACD(IIndicator):
    """Moving Average Convergence Divergence.

    MACD = EMA(fast) - EMA(slow)
    Signal line = EMA(signal_period) of MACD values

    Buy when MACD crosses above signal line.
    Sell when MACD crosses below signal line.
    """

    def __init__(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> None:
        if fast_period < 1 or slow_period < 1 or signal_period < 1:
            raise ValueError("All periods must be >= 1")
        if fast_period >= slow_period:
            raise ValueError("fast_period must be less than slow_period")
        self._fast = fast_period
        self._slow = slow_period
        self._signal_period = signal_period

    @property
    def name(self) -> str:
        return f"MACD({self._fast},{self._slow},{self._signal_period})"

    @property
    def min_periods(self) -> int:
        return self._slow + self._signal_period

    def calculate(self, prices: list[Decimal]) -> Decimal | None:
        """Returns the MACD line value (fast EMA - slow EMA)."""
        if len(prices) < self._slow:
            return None
        fast_ema = self._ema(prices, self._fast)
        slow_ema = self._ema(prices, self._slow)
        return fast_ema - slow_ema

    def calculate_full(
        self, prices: list[Decimal]
    ) -> tuple[Decimal, Decimal, Decimal] | None:
        """Returns (macd_line, signal_line, histogram) or None."""
        if len(prices) < self.min_periods:
            return None

        # Build MACD line series
        macd_values: list[Decimal] = []
        for i in range(self._slow, len(prices) + 1):
            window = prices[:i]
            fast_ema = self._ema(window, self._fast)
            slow_ema = self._ema(window, self._slow)
            macd_values.append(fast_ema - slow_ema)

        if len(macd_values) < self._signal_period:
            return None

        signal_line = self._ema(macd_values, self._signal_period)
        macd_line = macd_values[-1]
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    def signal(self, prices: list[Decimal]) -> Signal:
        if len(prices) < self.min_periods + 1:
            return Signal.HOLD

        current = self.calculate_full(prices)
        previous = self.calculate_full(prices[:-1])

        if current is None or previous is None:
            return Signal.HOLD

        macd_now, signal_now, _ = current
        macd_prev, signal_prev, _ = previous

        # MACD crosses above signal line -> BUY
        if macd_now > signal_now and macd_prev <= signal_prev:
            return Signal.BUY
        # MACD crosses below signal line -> SELL
        if macd_now < signal_now and macd_prev >= signal_prev:
            return Signal.SELL
        return Signal.HOLD

    @staticmethod
    def _ema(values: list[Decimal], period: int) -> Decimal:
        if len(values) < period:
            return values[-1] if values else Decimal("0")
        multiplier = Decimal(2) / (Decimal(period) + Decimal(1))
        ema = sum(values[:period]) / period
        for val in values[period:]:
            ema = (val - ema) * multiplier + ema
        return ema
