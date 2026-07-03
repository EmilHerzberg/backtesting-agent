import pytest

from src.backend.indicators.ema import EMA
from src.backend.indicators.macd import MACD
from src.backend.indicators.registry import available_indicators, get_indicator
from src.backend.indicators.rsi import RSI
from src.backend.indicators.sma import SMA


class TestRegistry:
    def test_get_sma(self):
        ind = get_indicator("SMA", period=20)
        assert isinstance(ind, SMA)

    def test_get_ema(self):
        ind = get_indicator("ema")  # case insensitive
        assert isinstance(ind, EMA)

    def test_get_rsi(self):
        ind = get_indicator("RSI", period=14)
        assert isinstance(ind, RSI)

    def test_get_macd(self):
        ind = get_indicator("MACD")
        assert isinstance(ind, MACD)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown indicator"):
            get_indicator("BOLLINGER")

    def test_available_indicators(self):
        available = available_indicators()
        assert available == ["EMA", "MACD", "RSI", "SMA"]
