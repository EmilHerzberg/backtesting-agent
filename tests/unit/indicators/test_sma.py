from decimal import Decimal

import pytest

from src.backend.indicators.interface import Signal
from src.backend.indicators.sma import SMA


class TestSMACalculate:
    def test_basic(self):
        sma = SMA(period=3)
        prices = [Decimal("10"), Decimal("20"), Decimal("30")]
        assert sma.calculate(prices) == Decimal("20")

    def test_not_enough_data(self):
        sma = SMA(period=5)
        prices = [Decimal("10"), Decimal("20")]
        assert sma.calculate(prices) is None

    def test_uses_last_n_prices(self):
        sma = SMA(period=3)
        prices = [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4"), Decimal("5")]
        # Should use [3, 4, 5]
        assert sma.calculate(prices) == Decimal("4")

    def test_single_period(self):
        sma = SMA(period=1)
        assert sma.calculate([Decimal("42")]) == Decimal("42")

    def test_invalid_period(self):
        with pytest.raises(ValueError):
            SMA(period=0)


class TestSMASignal:
    def test_buy_signal_on_crossover(self):
        sma = SMA(period=3)
        # Prices below SMA, then cross above
        # SMA of [10,10,10] = 10, price[2]=10 <= SMA
        # SMA of [10,10,15] = 11.67, price[3]=15 > SMA -> BUY
        prices = [Decimal("10"), Decimal("10"), Decimal("10"), Decimal("15")]
        assert sma.signal(prices) == Signal.BUY

    def test_sell_signal_on_crossunder(self):
        sma = SMA(period=3)
        # SMA of [10,10,10] = 10, price[2]=10 >= SMA
        # SMA of [10,10,5] = 8.33, price[3]=5 < SMA -> SELL
        prices = [Decimal("10"), Decimal("10"), Decimal("10"), Decimal("5")]
        assert sma.signal(prices) == Signal.SELL

    def test_hold_when_no_cross(self):
        sma = SMA(period=3)
        # Price stays above SMA
        prices = [Decimal("10"), Decimal("11"), Decimal("12"), Decimal("13")]
        assert sma.signal(prices) == Signal.HOLD

    def test_hold_insufficient_data(self):
        sma = SMA(period=5)
        prices = [Decimal("10"), Decimal("11")]
        assert sma.signal(prices) == Signal.HOLD


class TestSMAProperties:
    def test_name(self):
        assert SMA(period=20).name == "SMA(20)"

    def test_min_periods(self):
        assert SMA(period=14).min_periods == 14
