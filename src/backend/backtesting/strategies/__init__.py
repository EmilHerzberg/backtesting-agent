"""Backtesting strategy module.

Provides pre-built strategies compatible with backtesting.py and a
combinatorial generator that uses Optuna to dynamically compose
multi-indicator strategies.

Usage::

    from src.backend.backtesting.strategies import SMACrossover, generate_strategy

    # Use a fixed strategy with default parameters
    bt = Backtest(data, SMACrossover, cash=10_000)

    # Or create a parameterised variant
    MyStrat = SMACrossover.create_with_params(fast_period=15, slow_period=60)
    bt = Backtest(data, MyStrat, cash=10_000)
"""

from src.backend.backtesting.strategies.base import StrategyBase
from src.backend.backtesting.strategies.bollinger_breakout import BollingerBreakout
from src.backend.backtesting.strategies.generator import generate_strategy
from src.backend.backtesting.strategies.macd_cross import MACDSignalCross
from src.backend.backtesting.strategies.multi_indicator import MultiIndicator
from src.backend.backtesting.strategies.rsi_reversion import RSIMeanReversion
from src.backend.backtesting.strategies.signals import (
    SignalDirection,
    SignalHistory,
    TradeSignal,
)
from src.backend.backtesting.strategies.sma_crossover import SMACrossover

__all__ = [
    # Base
    "StrategyBase",
    # Signal interface (ATS-171)
    "TradeSignal",
    "SignalDirection",
    "SignalHistory",
    # Fixed strategies
    "SMACrossover",
    "RSIMeanReversion",
    "BollingerBreakout",
    "MACDSignalCross",
    "MultiIndicator",
    # Generator
    "generate_strategy",
]
