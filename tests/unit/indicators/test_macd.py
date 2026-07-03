from decimal import Decimal

import pytest

from src.backend.indicators.interface import Signal
from src.backend.indicators.macd import MACD


def _trending_up(n: int) -> list[Decimal]:
    return [Decimal("100") + Decimal(i) * Decimal("0.5") for i in range(n)]


def _trending_down(n: int) -> list[Decimal]:
    return [Decimal("200") - Decimal(i) * Decimal("0.5") for i in range(n)]


class TestMACDCalculate:
    def test_returns_decimal(self):
        macd = MACD()
        prices = _trending_up(30)
        result = macd.calculate(prices)
        assert result is not None
        assert isinstance(result, Decimal)

    def test_positive_in_uptrend(self):
        macd = MACD()
        prices = _trending_up(40)
        result = macd.calculate(prices)
        assert result is not None
        assert result > Decimal("0")

    def test_negative_in_downtrend(self):
        macd = MACD()
        prices = _trending_down(40)
        result = macd.calculate(prices)
        assert result is not None
        assert result < Decimal("0")

    def test_not_enough_data(self):
        macd = MACD()
        prices = [Decimal("100")] * 10
        assert macd.calculate(prices) is None

    def test_invalid_periods(self):
        with pytest.raises(ValueError):
            MACD(fast_period=26, slow_period=12)


class TestMACDFull:
    def test_returns_three_values(self):
        macd = MACD()
        prices = _trending_up(50)
        result = macd.calculate_full(prices)
        assert result is not None
        macd_line, signal_line, histogram = result
        assert isinstance(macd_line, Decimal)
        assert isinstance(signal_line, Decimal)
        assert histogram == macd_line - signal_line

    def test_not_enough_for_signal_line(self):
        macd = MACD()
        prices = _trending_up(30)
        result = macd.calculate_full(prices)
        assert result is None


class TestMACDSignal:
    def test_hold_insufficient_data(self):
        macd = MACD()
        prices = [Decimal("100")] * 10
        assert macd.signal(prices) == Signal.HOLD

    def test_produces_signal_with_enough_data(self):
        macd = MACD(fast_period=12, slow_period=26, signal_period=9)
        # Build a series that transitions from flat to rising
        flat = [Decimal("100")] * 30
        rising = [Decimal("100") + Decimal(i) * Decimal("2") for i in range(20)]
        prices = flat + rising
        result = macd.signal(prices)
        assert result in (Signal.BUY, Signal.SELL, Signal.HOLD)


class TestMACDProperties:
    def test_name(self):
        assert MACD().name == "MACD(12,26,9)"
        assert MACD(8, 21, 5).name == "MACD(8,21,5)"

    def test_min_periods(self):
        assert MACD().min_periods == 35  # 26 + 9
