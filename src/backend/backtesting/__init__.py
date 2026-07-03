"""Backtesting capability — public facade (Modularisation Phase 3).

Consumers (e.g. the ai capability) should import the backtesting public API from
this package root rather than reaching into deep submodules — this is the contract
boundary that lets the engine internals move without breaking callers.

Re-exports are *lazy* (PEP 562 ``__getattr__``): importing this package is cheap
and pulls a submodule only when the corresponding name is first accessed, so there
is no eager-import cost or cycle risk.
"""
from __future__ import annotations

import importlib
from typing import Any

# Public name -> defining submodule.
_EXPORTS: dict[str, str] = {
    # results
    "ResultStore": "src.backend.backtesting.results.store",
    "ResultQuery": "src.backend.backtesting.results.query",
    "FilterCriteria": "src.backend.backtesting.results.query",
    "BTTrial": "src.backend.backtesting.results.models",
    "BTStrategy": "src.backend.backtesting.results.models",
    "RegimeAnalyzer": "src.backend.backtesting.results.regime",
    # engine
    "BacktestConfig": "src.backend.backtesting.engine.runner",
    "run_backtest": "src.backend.backtesting.engine.runner",
    # pipeline / CLI
    "run_pipeline": "src.backend.backtesting.cli",
    "_resolve_strategy_class": "src.backend.backtesting.cli",
    # data providers
    "create_aggregated_provider": "src.backend.marketdata.provider",
    "YahooProvider": "src.backend.marketdata.provider",
    # analysis
    "run_cost_sweep": "src.backend.backtesting.analysis.cost_sensitivity",
    # deployment-readiness quality check (backtest-result analysis; consumed by
    # trading's deployment flow and the ai goal orchestrator) — moved here in Phase 7
    "run_quality_check": "src.backend.backtesting.quality_check",
    # config schema
    "BacktestFullConfig": "src.backend.backtesting.config.schema",
    "AssetsConfig": "src.backend.backtesting.config.schema",
    "TimeConfig": "src.backend.backtesting.config.schema",
    "StrategyConfig": "src.backend.backtesting.config.schema",
    "CostsConfigYaml": "src.backend.backtesting.config.schema",
    "OptunaConfig": "src.backend.backtesting.config.schema",
    "WalkForwardYaml": "src.backend.backtesting.config.schema",
    "OutputConfig": "src.backend.backtesting.config.schema",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:  # PEP 562
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(module_path), name)


def __dir__() -> list[str]:
    return sorted(__all__)
