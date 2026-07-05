"""Full YAML/JSON configuration schema for backtesting using Pydantic."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AssetsConfig(BaseModel):
    """Which symbols/assets to backtest."""

    symbols: list[str] = Field(default_factory=lambda: ["AAPL"])
    asset_type: str = "STOCK"


class TimeConfig(BaseModel):
    """Time range configuration."""

    lookback: str = "2y"
    start: str | None = None
    end: str | None = None
    interval: str = "1d"


class StrategyConfig(BaseModel):
    """Which strategies to evaluate."""

    names: list[str] = Field(default_factory=lambda: ["SMACrossover"])
    use_generator: bool = False
    max_indicators: int = 3


class CostsConfigYaml(BaseModel):
    """Transaction cost parameters."""

    commission_pct: float = 0.001
    spread_bps: float = 5.0
    slippage_bps: float = 2.0


class OptunaConfig(BaseModel):
    """Optuna hyperparameter optimization settings."""

    n_trials: int = 100
    sampler: str = "tpe"
    pruner: str = "median"
    objective: str = "composite"
    composite_weights: dict[str, float] = Field(
        # M4: max_drawdown is a FRACTION (F-013); -1.5 makes a bad drawdown meaningfully offset Sharpe
        # (a 50% DD ≈ -0.75) instead of degenerating to Sharpe-maximization at -0.4.
        default_factory=lambda: {"sharpe": 0.6, "max_drawdown": -1.5}
    )


class WalkForwardYaml(BaseModel):
    """Walk-forward validation settings."""

    enabled: bool = False
    train_size: str = "12m"
    test_size: str = "3m"
    step: str = "3m"
    validation_threshold: float = 0.0


class OutputConfig(BaseModel):
    """Output and persistence settings."""

    save_results: bool = True
    db_path: str = "data/backtesting.db"
    plots: bool = True
    plot_dir: str = "data/plots"
    export_csv: bool = False


class EventGateConfig(BaseModel):
    """ATS-2080 — Event-gate consumption settings for backtests.

    When ``enabled`` is True the backtest pre-loads gate decisions from
    ``event_gate_decisions`` for the (asset, date_range) window and applies
    them at each entry signal. ``min_event_importance`` and
    ``min_asset_severity`` define which persisted gates qualify as
    "actionable" — gates with weaker scores pass through without action.
    ``allowed_actions`` whitelists which gate actions the strategy honors;
    use this to evaluate BLOCK-only vs. REDUCE-only scenarios separately.
    ``override_per_event_type_windows`` lets a calibration / sensitivity
    backtest temporarily widen or narrow per-event-type windows without
    rewriting ``ec_event_types``.
    """

    enabled: bool = False
    min_event_importance: float = 0.7
    min_asset_severity: float = 0.45
    allowed_actions: list[str] = Field(
        default_factory=lambda: ["BLOCK_NEW_ENTRIES", "REDUCE_POSITION_SIZE"],
    )
    override_per_event_type_windows: dict[str, dict] | None = None


class BacktestFullConfig(BaseModel):
    """Top-level configuration combining all backtesting subsections."""

    assets: AssetsConfig = Field(default_factory=AssetsConfig)
    time: TimeConfig = Field(default_factory=TimeConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    costs: CostsConfigYaml = Field(default_factory=CostsConfigYaml)
    optuna: OptunaConfig = Field(default_factory=OptunaConfig)
    walk_forward: WalkForwardYaml = Field(default_factory=WalkForwardYaml)
    output: OutputConfig = Field(default_factory=OutputConfig)
    # ATS-2080 — optional event-gate consumer config. ``None`` (the
    # default) keeps every pre-2080 backtest behaviour-identical; setting
    # ``enabled=True`` activates the gate lookup path in the runner.
    event_gate: EventGateConfig | None = None
    cash: float = 10_000.0
    n_workers: int = 0  # 0 = auto-detect CPU count

    model_config = ConfigDict(extra="ignore")


def load_config(path: str) -> BacktestFullConfig:
    """Load a BacktestFullConfig from a YAML or JSON file.

    Args:
        path: File path ending in .yaml, .yml, or .json.

    Returns:
        Parsed BacktestFullConfig instance.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file format is unsupported.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    text = file_path.read_text(encoding="utf-8")

    if file_path.suffix in (".yaml", ".yml"):
        import yaml

        data = yaml.safe_load(text) or {}
    elif file_path.suffix == ".json":
        import json

        data = json.loads(text)
    else:
        raise ValueError(
            f"Unsupported config format '{file_path.suffix}'. "
            "Use .yaml, .yml, or .json."
        )

    return BacktestFullConfig(**data)
