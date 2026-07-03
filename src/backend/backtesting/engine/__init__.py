"""E-4 Execution & Evaluation Engine for the backtesting module.

Provides the core backtest runner, metrics extraction, Optuna-based
optimization, walk-forward validation, and parallel execution.

Usage::

    from src.backend.backtesting.engine import (
        BacktestConfig, run_backtest,
        OptimizationConfig, optimize,
        WalkForwardConfig, walk_forward_validate,
        run_parallel_backtests,
    )
"""

from src.backend.backtesting.engine.exceptions import (
    BacktestError,
    InsufficientDataError,
    InvalidParameterError,
    NoTradesError,
    OptimizationError,
)
from src.backend.backtesting.engine.metrics import (
    TradeDetail,
    calculate_calmar,
    calculate_profit_factor,
    calculate_sortino,
    extract_trades,
)
from src.backend.backtesting.engine.optimizer import (
    OptimizationConfig,
    OptimizationResult,
    optimize,
)
from src.backend.backtesting.engine.parallel import (
    ParallelConfig,
    run_parallel_backtests,
)
from src.backend.backtesting.engine.runner import (
    BacktestConfig,
    BacktestResult,
    run_backtest,
)
from src.backend.backtesting.engine.walk_forward import (
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
