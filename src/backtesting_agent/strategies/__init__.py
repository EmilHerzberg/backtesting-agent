"""Backtesting strategy module.

Provides pre-built strategies compatible with backtesting.py and a
combinatorial generator that uses Optuna to dynamically compose
multi-indicator strategies.

Usage::

    from backtesting_agent.strategies import SMACrossover, generate_strategy

    # Use a fixed strategy with default parameters
    bt = Backtest(data, SMACrossover, cash=10_000)

    # Or create a parameterised variant
    MyStrat = SMACrossover.create_with_params(fast_period=15, slow_period=60)
    bt = Backtest(data, MyStrat, cash=10_000)
"""

from backtesting_agent.strategies.base import StrategyBase
from backtesting_agent.strategies.bollinger_breakout import BollingerBreakout
from backtesting_agent.strategies.generator import generate_strategy
from backtesting_agent.strategies.macd_cross import MACDSignalCross
from backtesting_agent.strategies.multi_indicator import MultiIndicator
from backtesting_agent.strategies.rsi_reversion import RSIMeanReversion
from backtesting_agent.strategies.signals import (
    SignalDirection,
    SignalHistory,
    TradeSignal,
)
from backtesting_agent.strategies.sma_crossover import SMACrossover

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
