"""CLI entry point for the AI Trading Backtesting Framework.

Run as::

    python -m src.backend.backtesting.cli --preset quick
    python -m src.backend.backtesting.cli --config path/to/config.yaml
    python -m src.backend.backtesting.cli --asset AAPL MSFT --strategy SMACrossover --trials 200

"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime
from typing import Any

from src.backend.backtesting.config.logging import (
    ErrorReporter,
    TrialProgressCallback,
    setup_backtest_logging,
)
from src.backend.backtesting.config.presets import get_preset
from src.backend.backtesting.config.schema import BacktestFullConfig, load_config

logger = logging.getLogger(__name__)

# Strategy class name -> importable class mapping
_STRATEGY_MAP: dict[str, str] = {
    "SMACrossover": "src.backend.backtesting.strategies.sma_crossover.SMACrossover",
    "RSIMeanReversion": "src.backend.backtesting.strategies.rsi_reversion.RSIMeanReversion",
    "BollingerBreakout": "src.backend.backtesting.strategies.bollinger_breakout.BollingerBreakout",
    "MACDSignalCross": "src.backend.backtesting.strategies.macd_cross.MACDSignalCross",
    "MultiIndicator": "src.backend.backtesting.strategies.multi_indicator.MultiIndicator",
}

# Flag for graceful Ctrl+C handling
_interrupted = False


def _handle_sigint(sig: int, frame: Any) -> None:
    """Handle Ctrl+C gracefully."""
    global _interrupted
    if _interrupted:
        # Second Ctrl+C -- force exit
        sys.stderr.write("\nForce exit.\n")
        sys.exit(1)
    _interrupted = True
    sys.stderr.write("\nInterrupted. Finishing current task and exiting...\n")


def _resolve_strategy_class(name: str) -> type:
    """Import and return a strategy class by its short name.

    Args:
        name: Strategy class name (e.g. ``"SMACrossover"``).

    Returns:
        The strategy class.

    Raises:
        ValueError: If the strategy name is unknown.
    """
    if name not in _STRATEGY_MAP:
        available = ", ".join(sorted(_STRATEGY_MAP))
        raise ValueError(
            f"Unknown strategy '{name}'. Available: {available}"
        )
    module_path, cls_name = _STRATEGY_MAP[name].rsplit(".", 1)
    import importlib

    mod = importlib.import_module(module_path)
    return getattr(mod, cls_name)


def _build_config(args: argparse.Namespace) -> BacktestFullConfig:
    """Build the configuration from CLI arguments.

    Priority: --config file > --preset > default "quick".
    CLI flags (--asset, --strategy, etc.) override the loaded config.
    """
    if args.config:
        config = load_config(args.config)
    elif args.preset:
        config = get_preset(args.preset)
    else:
        config = get_preset("quick")

    # Apply CLI overrides
    if args.asset:
        config.assets.symbols = args.asset
    if args.strategy:
        config.strategy.names = args.strategy
    if args.trials is not None:
        config.optuna.n_trials = args.trials
    if args.jobs is not None:
        config.n_workers = args.jobs
    if args.lookback:
        config.time.lookback = args.lookback
    if args.walk_forward:
        config.walk_forward.enabled = True
    if args.no_plots:
        config.output.plots = False

    return config


# ---------------------------------------------------------------------- #
# Summary table formatting
# ---------------------------------------------------------------------- #


def _format_table(
    headers: list[str],
    rows: list[list[str]],
    min_col_width: int = 10,
) -> str:
    """Format a simple ASCII table.

    Args:
        headers: Column header strings.
        rows: List of rows, each a list of cell strings.
        min_col_width: Minimum column width.

    Returns:
        Multi-line string representing the table.
    """
    col_widths = [max(min_col_width, len(h)) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(cell))

    separator = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"

    def _fmt_row(cells: list[str]) -> str:
        parts = []
        for i, cell in enumerate(cells):
            w = col_widths[i] if i < len(col_widths) else min_col_width
            parts.append(f" {cell:<{w}} ")
        return "|" + "|".join(parts) + "|"

    lines = [separator, _fmt_row(headers), separator]
    for row in rows:
        lines.append(_fmt_row(row))
    lines.append(separator)
    return "\n".join(lines)


def _print_summary(results: list[dict[str, Any]], elapsed: float) -> None:
    """Print a summary table of all backtest results.

    Args:
        results: List of result dicts with keys like symbol, strategy,
                 sharpe_ratio, total_return, max_drawdown, etc.
        elapsed: Total wall-clock time in seconds.
    """
    if not results:
        print("\nNo results to display.")
        return

    headers = [
        "Symbol", "Strategy", "Return %", "Sharpe",
        "Max DD %", "Win Rate %", "Trades", "Profit F.",
    ]
    rows: list[list[str]] = []
    for r in results:
        rows.append([
            str(r.get("symbol", "")),
            str(r.get("strategy", "")),
            f"{r.get('total_return', 0.0):+.2f}",
            f"{r.get('sharpe_ratio', 0.0):.3f}",
            f"{r.get('max_drawdown', 0.0):.2f}",
            f"{r.get('win_rate', 0.0):.1f}",
            str(r.get("trade_count", 0)),
            f"{r.get('profit_factor', 0.0):.2f}",
        ])

    print("\n" + "=" * 70)
    print("  BACKTESTING RESULTS SUMMARY")
    print("=" * 70)
    print(_format_table(headers, rows))

    # R11 (valconf): the Sharpe confidence interval, honestly labelled. It is the SAMPLING PRECISION of the
    # Sharpe on this sample — how noisy the number is — NOT an overfitting/robustness verdict (that is what
    # walk-forward / OOS is for). A band that straddles 0 means the Sharpe is not distinguishable from zero.
    _ci_rows = [r for r in results if r.get("sharpe_ci_low") is not None]
    if _ci_rows:
        print("\n  Sharpe 90% CI (sampling precision — NOT an overfitting verdict):")
        for r in _ci_rows:
            print(f"    {r.get('symbol','')}/{r.get('strategy','')}: "
                  f"Sharpe {r.get('sharpe_ratio', 0.0):.2f}  "
                  f"[{r['sharpe_ci_low']:.2f}, {r['sharpe_ci_high']:.2f}]")

    print(f"\nTotal combinations: {len(results)}")
    print(f"Elapsed time: {elapsed:.1f}s")
    print("=" * 70)


# ---------------------------------------------------------------------- #
# Pipeline
# ---------------------------------------------------------------------- #


def run_pipeline(
    config: BacktestFullConfig,
    progress_callback: callable | None = None,
    batch_job_id: int | None = None,  # F-001 fix: tag trials with batch_job_id
) -> list[dict[str, Any]]:
    """Main pipeline orchestrating the full backtesting workflow.

    Steps:
        1. Fetch/cache data for all symbols.
        2. Run data quality checks.
        3. For each (symbol, strategy) pair: optimize or walk-forward validate.
        4. Collect and return results.

    Args:
        config: Fully resolved backtest configuration.
        progress_callback: Optional callable(completed_count) for progress reporting.
        batch_job_id: Optional. If provided (e.g. from API batch endpoint),
            all persisted trials are tagged with this batch id so the
            Waterfall generator can later filter by it.

    Returns:
        List of result summary dicts (one per symbol x strategy combination).
    """
    from src.backend.marketdata.provider import create_provider
    from src.backend.marketdata.quality import DataQualityChecker
    from src.backend.marketdata.windows import LookbackConfig
    from src.backend.backtesting.engine.optimizer import OptimizationConfig, optimize
    from src.backend.backtesting.engine.walk_forward import (
        WalkForwardConfig,
        walk_forward_validate,
    )
    from src.backend.shared.types import BarInterval

    global _interrupted

    error_reporter = ErrorReporter()
    all_results: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ #
    # 1. Resolve time range
    # ------------------------------------------------------------------ #
    lookback_cfg = LookbackConfig(
        period=config.time.lookback,
        start=(
            datetime.fromisoformat(config.time.start)
            if config.time.start
            else None
        ),
        end=(
            datetime.fromisoformat(config.time.end)
            if config.time.end
            else None
        ),
    )
    start_dt, end_dt = lookback_cfg.resolve()
    logger.info(
        "Time range: %s -> %s (interval=%s)",
        start_dt.date(), end_dt.date(), config.time.interval,
    )

    # Map interval string to BarInterval enum
    interval_map: dict[str, BarInterval] = {
        "1m": BarInterval.ONE_MIN,
        "5m": BarInterval.FIVE_MIN,
        "15m": BarInterval.FIFTEEN_MIN,
        "1h": BarInterval.ONE_HOUR,
        "1d": BarInterval.ONE_DAY,
    }
    bar_interval = interval_map.get(config.time.interval, BarInterval.ONE_DAY)

    # ------------------------------------------------------------------ #
    # 2. Fetch data for all symbols
    # ------------------------------------------------------------------ #
    provider = create_provider("yahoo")
    quality_checker = DataQualityChecker()
    symbol_data: dict[str, Any] = {}

    for symbol in config.assets.symbols:
        if _interrupted:
            break

        logger.info("Fetching data for %s ...", symbol)
        try:
            df = provider.fetch_ohlcv(
                symbol, bar_interval, start=start_dt, end=end_dt
            )
            if df.empty:
                logger.warning("No data for %s -- skipping.", symbol)
                continue

            # Quality check
            report = quality_checker.validate(df, symbol=symbol, interval=bar_interval)
            if not report.is_clean:
                logger.warning(
                    "%s data has %d issue(s): %s",
                    symbol, report.total_issues, report.summary(),
                )

            symbol_data[symbol] = df
            logger.info(
                "  %s: %d rows (%s -> %s)",
                symbol, len(df), df.index.min().date(), df.index.max().date(),
            )
        except Exception as exc:
            logger.error("Failed to fetch %s: %s", symbol, exc)
            error_reporter.add_error(f"data_fetch:{symbol}", exc)

    if not symbol_data:
        raise ValueError("No data available for any symbol. Check data providers and network connection.")

    # Commission from cost config (H29: single shared effective-cost helper — same formula the AI
    # research executor now uses, so CLI and AI runs price transaction cost identically).
    from src.backend.backtesting.costs.model import effective_commission_pct
    commission = effective_commission_pct(
        config.costs.commission_pct, config.costs.spread_bps, config.costs.slippage_bps
    )

    # ------------------------------------------------------------------ #
    # 3. Run backtests: optimize or walk-forward for each combo
    # ------------------------------------------------------------------ #
    total_combos = len(symbol_data) * len(config.strategy.names)
    combo_idx = 0

    for symbol, df in symbol_data.items():
        if _interrupted:
            break

        for strategy_name in config.strategy.names:
            if _interrupted:
                break

            combo_idx += 1
            logger.info(
                "[%d/%d] %s x %s",
                combo_idx, total_combos, symbol, strategy_name,
            )

            try:
                strategy_cls = _resolve_strategy_class(strategy_name)
            except ValueError as exc:
                logger.error("  %s", exc)
                error_reporter.add_error(f"strategy:{strategy_name}", exc)
                continue

            # ResultStore for persistent storage
            from src.backend.backtesting.results.store import ResultStore
            store = ResultStore()

            try:
                if config.walk_forward.enabled:
                    # Walk-forward validation
                    wf_config = WalkForwardConfig(
                        strategy_class=strategy_cls,
                        data=df,
                        train_size=config.walk_forward.train_size,
                        test_size=config.walk_forward.test_size,
                        step=config.walk_forward.step,
                        n_trials_per_window=config.optuna.n_trials,
                        cash=config.cash,
                        commission=commission,
                        validation_threshold=config.walk_forward.validation_threshold,
                        # M10-CLI: forward the user's optuna objective/weights so per-window optimization
                        # targets what the YAML asked for (was silently dropped here → default composite,
                        # while windows were scored on test Sharpe — the exact M10 inconsistency).
                        objective_metric=config.optuna.objective,
                        composite_weights=config.optuna.composite_weights,
                        # F1: thread the asset symbol + event-gate config so a YAML gate is honoured in
                        # walk-forward mode (was inert — WalkForwardConfig was built without it).
                        symbol=symbol,
                        event_gate=config.event_gate,
                    )
                    wf_result = walk_forward_validate(wf_config)

                    # ── Persist each window to ResultStore ──
                    for w in wf_result.windows:
                        # Save train result
                        if w.train_result:
                            store.save_trial(
                                strategy_name=strategy_name,
                                class_name=strategy_name,
                                symbol=symbol,
                                params=w.best_params or {},
                                result=w.train_result,
                                interval=config.time.interval,
                                train_start=w.train_start,
                                train_end=w.train_end,
                                test_start=w.test_start,
                                test_end=w.test_end,
                                cash=config.cash,
                                commission=commission,
                                is_train=True,
                                overfitting_score=w.overfitting_score,
                                is_validated=wf_result.is_strategy_validated,
                                batch_job_id=batch_job_id,  # F-001 fix
                            )
                        # Save test result
                        if w.test_result:
                            store.save_trial(
                                strategy_name=strategy_name,
                                class_name=strategy_name,
                                symbol=symbol,
                                params=w.best_params or {},
                                result=w.test_result,
                                interval=config.time.interval,
                                train_start=w.train_start,
                                train_end=w.train_end,
                                test_start=w.test_start,
                                test_end=w.test_end,
                                cash=config.cash,
                                commission=commission,
                                is_train=False,
                                overfitting_score=w.overfitting_score,
                                is_validated=wf_result.is_strategy_validated,
                                batch_job_id=batch_job_id,  # F-001 fix
                            )

                    all_results.append({
                        "symbol": symbol,
                        "strategy": strategy_name,
                        "mode": "walk_forward",
                        "total_return": None,
                        "sharpe_ratio": wf_result.avg_test_sharpe,
                        "max_drawdown": None,
                        "win_rate": None,
                        "trade_count": None,
                        "profit_factor": None,
                        "avg_overfitting_score": wf_result.avg_overfitting_score,
                        "pct_valid_windows": wf_result.pct_valid_windows,
                        "n_windows": len(wf_result.windows),
                        "validated": wf_result.is_strategy_validated,
                    })

                    logger.info(
                        "  WF result: avg_test_sharpe=%.3f, validated=%s, windows=%d (persisted)",
                        wf_result.avg_test_sharpe,
                        wf_result.is_strategy_validated,
                        len(wf_result.windows),
                    )
                else:
                    # Standard optimization
                    progress_cb = TrialProgressCallback(config.optuna.n_trials)
                    opt_config = OptimizationConfig(
                        strategy_class=strategy_cls,
                        data=df,
                        n_trials=config.optuna.n_trials,
                        sampler=config.optuna.sampler,
                        pruner=config.optuna.pruner,
                        objective_metric=config.optuna.objective,
                        composite_weights=config.optuna.composite_weights,
                        cash=config.cash,
                        commission=commission,
                        # F1: thread the asset symbol + event-gate config so a YAML gate is honoured in
                        # standard optimization mode (was inert — symbol was the "OPT" placeholder and no
                        # event_gate was passed, so the runner always saw config.event_gate=None).
                        symbol=symbol,
                        event_gate=config.event_gate,
                    )
                    opt_result = optimize(opt_config, callbacks=[progress_cb])
                    best = opt_result.best_result

                    # ── Persist best result to ResultStore ──
                    store.save_trial(
                        strategy_name=strategy_name,
                        class_name=strategy_name,
                        symbol=symbol,
                        params=opt_result.best_params or {},
                        result=best,
                        interval=config.time.interval,
                        cash=config.cash,
                        commission=commission,
                        is_train=True,
                        batch_job_id=batch_job_id,  # F-001 fix
                    )

                    all_results.append({
                        "symbol": symbol,
                        "strategy": strategy_name,
                        "mode": "optimization",
                        "total_return": best.total_return,
                        "sharpe_ratio": best.sharpe_ratio,
                        "max_drawdown": best.max_drawdown,
                        "win_rate": best.win_rate,
                        "trade_count": best.trade_count,
                        "profit_factor": best.profit_factor,
                        "best_params": opt_result.best_params,
                        "best_value": opt_result.best_value,
                        "n_trials": opt_result.n_trials,
                        "sharpe_ci_low": best.sharpe_ci_low,      # R11 (valconf): Sharpe sampling precision
                        "sharpe_ci_high": best.sharpe_ci_high,
                    })

                    logger.info(
                        "  Best: sharpe=%.3f, return=%.2f%%, params=%s (persisted)",
                        best.sharpe_ratio,
                        best.total_return,
                        opt_result.best_params,
                    )

            except Exception as exc:
                logger.error(
                    "  Failed %s x %s: %s", symbol, strategy_name, exc,
                )
                error_reporter.add_error(
                    f"backtest:{symbol}:{strategy_name}", exc,
                )

            # Report progress after each combination
            if progress_callback:
                try:
                    progress_callback(combo_idx)
                except Exception:
                    pass

    # ------------------------------------------------------------------ #
    # 4. Error summary
    # ------------------------------------------------------------------ #
    if error_reporter.errors:
        logger.warning("\n%s", error_reporter.summary())
        error_reporter.save()

    return all_results


# ---------------------------------------------------------------------- #
# CLI main
# ---------------------------------------------------------------------- #


def main() -> None:
    """Parse CLI arguments and run the backtesting pipeline."""
    signal.signal(signal.SIGINT, _handle_sigint)

    parser = argparse.ArgumentParser(
        description="AI Trading Backtesting Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --preset quick\n"
            "  %(prog)s --config my_config.yaml\n"
            "  %(prog)s --asset AAPL MSFT --strategy SMACrossover --trials 200\n"
            "  %(prog)s --preset standard --walk-forward --no-plots\n"
        ),
    )

    parser.add_argument(
        "--config", type=str, default=None,
        help="Path to YAML/JSON config file",
    )
    parser.add_argument(
        "--preset", type=str, choices=["quick", "standard", "full"],
        default=None,
        help="Use a preset configuration (default: quick)",
    )
    parser.add_argument(
        "--asset", type=str, nargs="+", metavar="SYM",
        help="Override symbols (e.g. --asset AAPL MSFT)",
    )
    parser.add_argument(
        "--strategy", type=str, nargs="+", metavar="NAME",
        help="Override strategies (e.g. --strategy SMACrossover RSIMeanReversion)",
    )
    parser.add_argument(
        "--trials", type=int, default=None,
        help="Override number of Optuna trials",
    )
    parser.add_argument(
        "--jobs", type=int, default=None,
        help="Number of parallel workers (0 = auto)",
    )
    parser.add_argument(
        "--lookback", type=str, default=None,
        help="Override lookback period (e.g. 1y, 6m, 90d)",
    )
    parser.add_argument(
        "--walk-forward", action="store_true", default=False,
        help="Enable walk-forward validation",
    )
    parser.add_argument(
        "--no-plots", action="store_true", default=False,
        help="Disable plot generation",
    )
    parser.add_argument(
        "--verbose", action="store_true", default=False,
        help="Enable verbose (DEBUG) logging",
    )

    args = parser.parse_args()

    # Setup logging
    setup_backtest_logging(verbose=args.verbose)

    # Build config
    try:
        config = _build_config(args)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(1)

    # Print banner
    print("=" * 70)
    print("  AI Trading Backtesting Framework")
    print("=" * 70)
    print(f"  Symbols:    {', '.join(config.assets.symbols)}")
    print(f"  Strategies: {', '.join(config.strategy.names)}")
    print(f"  Lookback:   {config.time.lookback}")
    print(f"  Trials:     {config.optuna.n_trials}")
    print(f"  Walk-fwd:   {'ON' if config.walk_forward.enabled else 'OFF'}")
    print(f"  Workers:    {config.n_workers or 'auto'}")
    print("=" * 70)

    # Run pipeline
    t0 = time.time()
    try:
        results = run_pipeline(config)
    except KeyboardInterrupt:
        print("\nAborted by user.")
        sys.exit(130)
    elapsed = time.time() - t0

    # Print summary
    _print_summary(results, elapsed)


if __name__ == "__main__":
    main()
