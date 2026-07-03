import inspect
from decimal import Decimal

import pytest

from src.backend.indicators.interface import IIndicator, Signal


class TestIIndicatorABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            IIndicator()

    def test_partial_implementation_raises(self):
        class Partial(IIndicator):
            @property
            def name(self) -> str:
                return "Partial"

        with pytest.raises(TypeError):
            Partial()

    def test_all_abstract_methods(self):
        expected = {"name", "calculate", "signal", "min_periods"}
        abstract = {
            n for n, _ in inspect.getmembers(IIndicator)
            if getattr(getattr(IIndicator, n, None), "__isabstractmethod__", False)
        }
        assert abstract == expected


class TestSignalEnum:
    def test_values(self):
        assert Signal.BUY == "BUY"
        assert Signal.SELL == "SELL"
        assert Signal.HOLD == "HOLD"
