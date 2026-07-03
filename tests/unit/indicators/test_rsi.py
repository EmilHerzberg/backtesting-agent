from decimal import Decimal

import pytest

from src.backend.indicators.interface import Signal
from src.backend.indicators.rsi import RSI


def _rising_prices(n: int, start: Decimal = Decimal("100")) -> list[Decimal]:
    """Generate n steadily rising prices."""
    return [start + Decimal(i) for i in range(n)]


def _falling_prices(n: int, start: Decimal = Decimal("200")) -> list[Decimal]:
    """Generate n steadily falling prices."""
    return [start - Decimal(i) for i in range(n)]


class TestRSICalculate:
    def test_all_gains_returns_100(self):
        rsi = RSI(period=14)
        prices = _rising_prices(20)
        result = rsi.calculate(prices)
        assert result == Decimal("100")

    def test_all_losses_returns_0(self):
        rsi = RSI(period=14)
        prices = _falling_prices(20)
        result = rsi.calculate(prices)
        assert result is not None
        assert result < Decimal("1")  # Very close to 0

    def test_range_0_to_100(self):
        rsi = RSI(period=14)
        prices = [Decimal("100") + Decimal(i % 5) for i in range(30)]
        result = rsi.calculate(prices)
        assert result is not None
        assert Decimal("0") <= result <= Decimal("100")

    def test_not_enough_data(self):
        rsi = RSI(period=14)
        prices = [Decimal("100")] * 10
        assert rsi.calculate(prices) is None

    def test_invalid_period(self):
        with pytest.raises(ValueError):
            RSI(period=0)


class TestRSISignal:
    def test_buy_when_oversold(self):
        rsi = RSI(period=14, oversold=Decimal("30"))
        # Falling prices -> RSI near 0 -> BUY
        prices = _falling_prices(20)
        assert rsi.signal(prices) == Signal.BUY

    def test_sell_when_overbought(self):
        rsi = RSI(period=14, overbought=Decimal("70"))
        prices = _rising_prices(20)
        assert rsi.signal(prices) == Signal.SELL

    def test_hold_in_middle(self):
        rsi = RSI(period=14)
        # Alternating up/down -> RSI near 50 -> HOLD
        prices = []
        for i in range(30):
            prices.append(Decimal("100") + Decimal(3 if i % 2 == 0 else -3))
        result = rsi.signal(prices)
        assert result == Signal.HOLD

    def test_hold_insufficient_data(self):
        rsi = RSI(period=14)
        assert rsi.signal([Decimal("100")]) == Signal.HOLD


class TestRSIProperties:
    def test_name(self):
        assert RSI(period=14).name == "RSI(14)"

    def test_min_periods(self):
        assert RSI(period=14).min_periods == 15
