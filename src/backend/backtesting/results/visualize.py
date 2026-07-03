"""Interactive Plotly visualizations for backtest results."""

from __future__ import annotations

import logging
from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.backend.backtesting.results.models import BTStrategy, BTTrial
from src.backend.backtesting.results.store import ResultStore

logger = logging.getLogger(__name__)


class ResultVisualizer:
    """Generate interactive HTML charts from stored backtest trials."""

    def __init__(self, store: ResultStore) -> None:
        self._store = store

    # ------------------------------------------------------------------ #
    # Equity curve overlay
    # ------------------------------------------------------------------ #

    def equity_curve_plot(
        self,
        trial_ids: list[int],
        output: str = "equity.html",
    ) -> go.Figure:
        """Plot equity curves for multiple trials, overlaid on the same axes.

        Args:
            trial_ids: Trial primary keys whose equity curves to plot.
            output: File path for the saved HTML chart.

        Returns:
            The Plotly ``Figure`` object.
        """
        fig = go.Figure()

        for tid in trial_ids:
            trial = self._store.get_trial(tid)
            if trial is None:
                logger.warning("Trial %d not found, skipping.", tid)
                continue
            if trial.equity_curve is None or not trial.equity_curve.values:
                logger.warning("Trial %d has no equity curve, skipping.", tid)
                continue

            label = (
                f"{trial.strategy.name if trial.strategy else '?'} "
                f"#{trial.id} ({trial.symbol})"
            )
            fig.add_trace(
                go.Scatter(
                    y=trial.equity_curve.values,
                    mode="lines",
                    name=label,
                )
            )

        fig.update_layout(
            title="Equity Curves",
            xaxis_title="Bar Index",
            yaxis_title="Equity",
            template="plotly_white",
        )
        self.save_plot(fig, output)
        return fig

    # ------------------------------------------------------------------ #
    # Strategy x Symbol heatmap
    # ------------------------------------------------------------------ #

    def heatmap(
        self,
        metric: str = "sharpe_ratio",
        output: str = "heatmap.html",
    ) -> go.Figure:
        """Strategy-vs-symbol performance heatmap.

        Each cell shows the *best* value of *metric* for that
        (strategy, symbol) pair across all stored trials.

        Args:
            metric: Column name on :class:`BTTrial` to display.
            output: File path for the saved HTML chart.

        Returns:
            The Plotly ``Figure`` object.
        """
        trials = self._store.get_all_trials()
        if not trials:
            logger.warning("No trials in store; heatmap is empty.")
            return go.Figure()

        # Aggregate best metric per (strategy, symbol)
        best: dict[tuple[str, str], float] = {}
        for t in trials:
            strat_name = t.strategy.name if t.strategy else "unknown"
            key = (strat_name, t.symbol)
            value = getattr(t, metric, None)
            if value is None:
                continue
            if key not in best or value > best[key]:
                best[key] = value

        strategies = sorted({k[0] for k in best})
        symbols = sorted({k[1] for k in best})

        z: list[list[float | None]] = []
        for strat in strategies:
            row: list[float | None] = []
            for sym in symbols:
                row.append(best.get((strat, sym)))
            z.append(row)

        fig = go.Figure(
            data=go.Heatmap(
                z=z,
                x=symbols,
                y=strategies,
                colorscale="RdYlGn",
                text=[[f"{v:.2f}" if v is not None else "" for v in row] for row in z],
                texttemplate="%{text}",
                hovertemplate=(
                    "Strategy: %{y}<br>Symbol: %{x}<br>"
                    + metric
                    + ": %{z:.3f}<extra></extra>"
                ),
            )
        )
        fig.update_layout(
            title=f"Heatmap: best {metric} per Strategy x Symbol",
            xaxis_title="Symbol",
            yaxis_title="Strategy",
            template="plotly_white",
        )
        self.save_plot(fig, output)
        return fig

    # ------------------------------------------------------------------ #
    # Parameter sensitivity
    # ------------------------------------------------------------------ #

    def parameter_sensitivity(
        self,
        strategy_name: str,
        symbol: str,
        param_name: str,
        metric: str = "sharpe_ratio",
        output: str = "sensitivity.html",
    ) -> go.Figure:
        """Scatter plot of a single parameter value vs. a performance metric.

        Args:
            strategy_name: Filter trials to this strategy.
            symbol: Filter trials to this symbol.
            param_name: Key inside :attr:`BTTrial.parameters` to plot on x-axis.
            metric: :class:`BTTrial` column to plot on y-axis.
            output: File path for the saved HTML chart.

        Returns:
            The Plotly ``Figure`` object.
        """
        trials = self._store.get_strategy_trials(strategy_name)

        x_vals: list[float] = []
        y_vals: list[float] = []

        for t in trials:
            if t.symbol != symbol:
                continue
            if t.parameters is None or param_name not in t.parameters:
                continue
            metric_val = getattr(t, metric, None)
            if metric_val is None:
                continue
            x_vals.append(float(t.parameters[param_name]))
            y_vals.append(float(metric_val))

        fig = go.Figure(
            data=go.Scatter(
                x=x_vals,
                y=y_vals,
                mode="markers",
                marker=dict(
                    size=8,
                    color=y_vals,
                    colorscale="Viridis",
                    showscale=True,
                ),
                text=[f"{param_name}={x}" for x in x_vals],
                hovertemplate=(
                    f"{param_name}: %{{x}}<br>{metric}: %{{y:.3f}}<extra></extra>"
                ),
            )
        )
        fig.update_layout(
            title=f"Parameter Sensitivity: {param_name} vs {metric} ({strategy_name}/{symbol})",
            xaxis_title=param_name,
            yaxis_title=metric,
            template="plotly_white",
        )
        self.save_plot(fig, output)
        return fig

    # ------------------------------------------------------------------ #
    # Train vs Test scatter
    # ------------------------------------------------------------------ #

    def train_vs_test(
        self,
        strategy_name: str | None = None,
        output: str = "train_test.html",
    ) -> go.Figure:
        """Scatter plot comparing train vs test Sharpe ratio for walk-forward results.

        Each point represents a walk-forward window.  Points below the
        diagonal indicate overfitting.

        Args:
            strategy_name: Optional filter to a single strategy.
            output: File path for the saved HTML chart.

        Returns:
            The Plotly ``Figure`` object.
        """
        all_trials = self._store.get_all_trials()

        # Group by (strategy, symbol, train_start, test_start) to pair
        # train/test rows that belong to the same walk-forward window.
        from collections import defaultdict

        groups: dict[tuple, dict[str, BTTrial]] = defaultdict(dict)

        for t in all_trials:
            if t.train_start is None or t.test_start is None:
                continue
            strat_name = t.strategy.name if t.strategy else "unknown"
            if strategy_name is not None and strat_name != strategy_name:
                continue
            key = (strat_name, t.symbol, t.train_start, t.test_start)
            label = "train" if t.is_train else "test"
            groups[key][label] = t

        train_sharpes: list[float] = []
        test_sharpes: list[float] = []
        labels: list[str] = []

        for key, pair in groups.items():
            if "train" not in pair or "test" not in pair:
                continue
            ts = pair["train"].sharpe_ratio or 0.0
            te = pair["test"].sharpe_ratio or 0.0
            train_sharpes.append(ts)
            test_sharpes.append(te)
            labels.append(f"{key[0]} / {key[1]}")

        fig = go.Figure()

        # Diagonal reference line
        if train_sharpes:
            lo = min(min(train_sharpes), min(test_sharpes))
            hi = max(max(train_sharpes), max(test_sharpes))
            fig.add_trace(
                go.Scatter(
                    x=[lo, hi],
                    y=[lo, hi],
                    mode="lines",
                    line=dict(dash="dash", color="grey"),
                    name="Perfect generalization",
                    showlegend=True,
                )
            )

        fig.add_trace(
            go.Scatter(
                x=train_sharpes,
                y=test_sharpes,
                mode="markers",
                marker=dict(size=10),
                text=labels,
                hovertemplate=(
                    "Train Sharpe: %{x:.3f}<br>Test Sharpe: %{y:.3f}"
                    "<br>%{text}<extra></extra>"
                ),
                name="Windows",
            )
        )

        fig.update_layout(
            title="Train vs Test Sharpe Ratio (Walk-Forward)",
            xaxis_title="Train Sharpe",
            yaxis_title="Test Sharpe",
            template="plotly_white",
        )
        self.save_plot(fig, output)
        return fig

    # ------------------------------------------------------------------ #
    # Utility
    # ------------------------------------------------------------------ #

    @staticmethod
    def save_plot(fig: go.Figure, output: str) -> None:
        """Write a Plotly figure to an HTML file, creating parent dirs."""
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.write_html(str(path))
        logger.info("Saved plot to %s", path.resolve())


# ---------------------------------------------------------------------- #
# ATS-219 / E5-S3-T3 — Optuna-driven parameter sensitivity
# ---------------------------------------------------------------------- #


def plot_parameter_sensitivity(study) -> dict[str, go.Figure]:
    """Generate Optuna's full set of parameter-sensitivity plots for a study.

    Returns a dict with whichever of the four standard Optuna views the study
    can render (some require >= 2 parameters or >= N completed trials):

      * ``importance``  — bar chart of which parameters drive the objective
      * ``contour``     — 2D interaction surface between top parameters
      * ``slice``       — per-parameter scatter against objective
      * ``history``     — best-value-so-far over trial index

    Args:
        study: A live ``optuna.Study`` (typically the one held inside
            :class:`OptimizationConfig` after ``optimize()`` returned).

    Returns:
        Dict ``{name: plotly Figure}``. Plots that cannot be produced (e.g.
        single-parameter study) are silently omitted.
    """
    from optuna.visualization import (
        plot_contour,
        plot_optimization_history,
        plot_param_importances,
        plot_slice,
    )

    plots: dict[str, go.Figure] = {}

    # Each plot can fail independently — e.g. plot_contour requires >= 2 params,
    # plot_param_importances requires >= 2 completed trials. Catch and skip.
    for name, factory in (
        ("importance", lambda: plot_param_importances(study)),
        ("contour", lambda: plot_contour(study)),
        ("slice", lambda: plot_slice(study)),
        ("history", lambda: plot_optimization_history(study)),
    ):
        try:
            plots[name] = factory()
        except (ValueError, RuntimeError) as exc:  # noqa: BLE001
            logger.debug("Skipping %s plot: %s", name, exc)
        except Exception as exc:  # noqa: BLE001 — Optuna throws various
            logger.debug("Skipping %s plot: %s", name, exc)

    return plots


def save_sensitivity_plots(study, output_dir: str = "plots") -> dict[str, str]:
    """Write every sensitivity plot for *study* to its own HTML file.

    Returns a dict mapping the plot name to the resulting file path.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for name, fig in plot_parameter_sensitivity(study).items():
        path = out / f"sensitivity_{name}.html"
        fig.write_html(str(path))
        written[name] = str(path)
        logger.info("Saved %s plot to %s", name, path.resolve())
    return written
