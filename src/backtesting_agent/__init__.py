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
    "ResultStore": "backtesting_agent.results.store",
    "ResultQuery": "backtesting_agent.results.query",
    "FilterCriteria": "backtesting_agent.results.query",
    "BTTrial": "backtesting_agent.results.models",
    "BTStrategy": "backtesting_agent.results.models",
    "RegimeAnalyzer": "backtesting_agent.results.regime",
    # engine
    "BacktestConfig": "backtesting_agent.engine.runner",
    "run_backtest": "backtesting_agent.engine.runner",
    # pipeline / CLI
    "run_pipeline": "backtesting_agent.cli",
    "_resolve_strategy_class": "backtesting_agent.cli",
    # data providers
    "create_aggregated_provider": "backtesting_agent.marketdata.provider",
    "YahooProvider": "backtesting_agent.marketdata.provider",
    # analysis
    "run_cost_sweep": "backtesting_agent.analysis.cost_sensitivity",
    # deployment-readiness quality check (backtest-result analysis; consumed by
    # trading's deployment flow and the ai goal orchestrator) — moved here in Phase 7
    "run_quality_check": "backtesting_agent.quality_check",
    # config schema
    "BacktestFullConfig": "backtesting_agent.config.schema",
    "AssetsConfig": "backtesting_agent.config.schema",
    "TimeConfig": "backtesting_agent.config.schema",
    "StrategyConfig": "backtesting_agent.config.schema",
    "CostsConfigYaml": "backtesting_agent.config.schema",
    "OptunaConfig": "backtesting_agent.config.schema",
    "WalkForwardYaml": "backtesting_agent.config.schema",
    "OutputConfig": "backtesting_agent.config.schema",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:  # PEP 562
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(module_path), name)


def __dir__() -> list[str]:
    return sorted(__all__)
