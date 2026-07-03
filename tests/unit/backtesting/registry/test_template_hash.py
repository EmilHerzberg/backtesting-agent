"""Tests for ATS-1705 — template_hash on StrategyBase."""

from src.backend.backtesting.strategies.sma_crossover import SMACrossover
from src.backend.backtesting.strategies.rsi_reversion import RSIMeanReversion
from src.backend.backtesting.strategies.base import StrategyBase


class TestTemplateHash:
    def test_hash_is_sha256_hex(self):
        h = SMACrossover.template_hash()
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_stable_across_calls(self):
        h1 = SMACrossover.template_hash()
        h2 = SMACrossover.template_hash()
        assert h1 == h2

    def test_different_strategies_different_hash(self):
        h1 = SMACrossover.template_hash()
        h2 = RSIMeanReversion.template_hash()
        assert h1 != h2

    def test_all_strategies_have_version(self):
        """Every StrategyBase subclass must have a version attribute."""
        from src.backend.backtesting.strategies import (
            bollinger_breakout,
            macd_cross,
            multi_indicator,
        )
        strategies = [
            SMACrossover,
            RSIMeanReversion,
            bollinger_breakout.BollingerBreakout,
            macd_cross.MACDSignalCross,
            multi_indicator.MultiIndicator,
        ]
        for cls in strategies:
            assert hasattr(cls, "version"), f"{cls.__name__} missing version"
            assert isinstance(cls.version, int), f"{cls.__name__}.version not int"

    def test_version_attribute_exists_on_base(self):
        assert hasattr(StrategyBase, "version")
        assert StrategyBase.version == 1
