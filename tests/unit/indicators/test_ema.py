from decimal import Decimal

import pytest

from src.backend.indicators.ema import EMA
from src.backend.indicators.interface import Signal


class TestEMACalculate:
    def test_with_exact_period_data(self):
        ema = EMA(period=3)
        prices = [Decimal("10"), Decimal("20"), Decimal("30")]
        result = ema.calculate(prices)
        # With only period data, EMA = SMA = 20
        assert result == Decimal("20")

    def test_ema_weights_recent_more(self):
        ema = EMA(period=3)
        prices = [Decimal("10"), Decimal("10"), Decimal("10"), Decimal("20")]
        result = ema.calculate(prices)
        assert result is not None
        # EMA should be between 10 and 20, closer to 20 than SMA
        assert Decimal("10") < result < Decimal("20")

    def test_not_enough_data(self):
        ema = EMA(period=10)
        prices = [Decimal("10")] * 5
        assert ema.calculate(prices) is None

    def test_invalid_period(self):
        with pytest.raises(ValueError):
            EMA(period=0)


class TestEMASignal:
    def test_hold_insufficient_data(self):
        ema = EMA(period=5)
        prices = [Decimal("10")] * 3
        assert ema.signal(prices) == Signal.HOLD

    def test_buy_on_crossover(self):
        ema = EMA(period=3)
        # Prices below EMA, then jump above
        prices = [Decimal("10"), Decimal("10"), Decimal("10"), Decimal("15")]
        assert ema.signal(prices) == Signal.BUY

    def test_sell_on_crossunder(self):
        ema = EMA(period=3)
        prices = [Decimal("10"), Decimal("10"), Decimal("10"), Decimal("5")]
        assert ema.signal(prices) == Signal.SELL


class TestEMAProperties:
    def test_name(self):
        assert EMA(period=12).name == "EMA(12)"

    def test_min_periods(self):
        assert EMA(period=26).min_periods == 26
