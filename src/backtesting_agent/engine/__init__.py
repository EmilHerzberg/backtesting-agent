"""E-4 Execution & Evaluation Engine for the backtesting module.

Provides the core backtest runner, metrics extraction, Optuna-based
optimization, walk-forward validation, and parallel execution.

Usage::

    from backtesting_agent.engine import (
        BacktestConfig, run_backtest,
        OptimizationConfig, optimize,
        WalkForwardConfig, walk_forward_validate,
        run_parallel_backtests,
    )
"""

from backtesting_agent.engine.exceptions import (
    BacktestError,
    InsufficientDataError,
    InvalidParameterError,
    NoTradesError,
    OptimizationError,
)
from backtesting_agent.engine.metrics import (
    TradeDetail,
    calculate_calmar,
    calculate_profit_factor,
    calculate_sortino,
    extract_trades,
)
from backtesting_agent.engine.optimizer import (
    OptimizationConfig,
    OptimizationResult,
    optimize,
)
from backtesting_agent.engine.parallel import (
    ParallelConfig,
    run_parallel_backtests,
)
from backtesting_agent.engine.runner import (
    BacktestConfig,
    BacktestResult,
    run_backtest,
)
from backtesting_agent.engine.walk_forward import (
    WalkForwardConfig,
    WalkForwardResult,
    WalkForwardWindow,
    walk_forward_validate,
)

__all__ = [
    # Exceptions
    "BacktestError",
    "InsufficientDataError",
    "InvalidParameterError",
    "NoTradesError",
    "OptimizationError",
    # Metrics
    "TradeDetail",
    "calculate_calmar",
    "calculate_profit_factor",
    "calculate_sortino",
    "extract_trades",
    # Runner
    "BacktestConfig",
    "BacktestResult",
    "run_backtest",
    # Optimizer
    "OptimizationConfig",
    "OptimizationResult",
    "optimize",
    # Walk-forward
    "WalkForwardConfig",
    "WalkForwardResult",
    "WalkForwardWindow",
    "walk_forward_validate",
    # Parallel
    "ParallelConfig",
    "run_parallel_backtests",
]
