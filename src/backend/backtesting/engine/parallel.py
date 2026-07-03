"""Parallel backtest execution using ProcessPoolExecutor."""

from __future__ import annotations

import logging
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass

from src.backend.backtesting.engine.exceptions import BacktestError
from src.backend.backtesting.engine.runner import (
    BacktestConfig,
    BacktestResult,
    run_backtest,
)

logger = logging.getLogger(__name__)


@dataclass
class ParallelConfig:
    """Configuration for parallel backtest execution.

    Attributes:
        n_workers: Number of worker processes.  ``0`` (default) means
            ``cpu_count - 1`` (at least 1).
    """

    n_workers: int = 0


def run_parallel_backtests(
    configs: list[BacktestConfig],
    n_workers: int = 0,
) -> list[BacktestResult | BacktestError]:
    """Run multiple backtests in parallel.

    Each config is executed in a separate process.  If a backtest fails the
    corresponding position in the result list contains a :class:`BacktestError`
    instead of a :class:`BacktestResult`, so the caller can inspect failures
    without losing the results of successful runs.

    Args:
        configs: List of backtest configurations.
        n_workers: Number of worker processes (0 = auto).

    Returns:
        List aligned with *configs* -- each element is either a
        :class:`BacktestResult` or a :class:`BacktestError`.
    """
    if not configs:
        return []

    if n_workers <= 0:
        n_workers = max(1, mp.cpu_count() - 1)

    # For a single config, skip the overhead of spawning a process pool
    if len(configs) == 1:
        return [_run_single(configs[0])]

    # Cap workers to the number of configs
    n_workers = min(n_workers, len(configs))

    results: list[BacktestResult | BacktestError] = [
        BacktestError("Not started")
    ] * len(configs)

    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        future_to_idx = {
            executor.submit(_run_single, cfg): idx
            for idx, cfg in enumerate(configs)
        }

        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as exc:
                logger.error("Parallel backtest %d failed: %s", idx, exc)
                results[idx] = BacktestError(
                    f"Parallel execution failed for config {idx}: {exc}"
                )

    return results


def _run_single(
    config: BacktestConfig,
) -> BacktestResult | BacktestError:
    """Run a single backtest, returning an error object on failure.

    This wrapper exists so that process-pool workers never raise -- they
    always return a value that the main process can inspect.
    """
    try:
        return run_backtest(config)
    except BacktestError as exc:
        return exc
    except Exception as exc:
        return BacktestError(f"Unexpected error: {exc}")
