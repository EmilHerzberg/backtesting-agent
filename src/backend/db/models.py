"""Database models — lazy re-export hub (Modularisation Phase 2/4/7).

Every table model lives in its owner module's ``db_models.py`` (each imports
``Base`` from :mod:`src.backend.db.base`). This module re-exports them all so the
historical import path ``from src.backend.db.models import XxxDB`` keeps working
for every existing call site — including the ``event_context`` model files, which
import ``Base`` and ``_utc_now`` from here.

**Phase 7:** the model re-exports are now *lazy* (PEP 562 ``__getattr__``). The
kernel must not statically depend on any capability (import-linter contract
``kernel-db-independence`` + the leaf/boundary contracts), but a static
``from owner.db_models import X`` here would create exactly such an edge — and a
phantom transitive edge for *every* module that imports this hub (even just for
``Base``). Resolving model classes lazily means this module's only static import
is ``db.base`` (kernel), so no capability edge exists in the import graph.

Table *registration* (importing every owner ``db_models`` so they attach to
``Base.metadata``) is owned by the composition root :mod:`src.backend.bootstrap`,
which is the one place allowed to import every feature module.

``Base`` and ``_utc_now`` stay eager: they are needed at class-definition time
(``class X(Base)``) by the owner model modules and by event_context.
"""
from __future__ import annotations

import importlib
from typing import Any

# Eager kernel re-export — safe (db.base is Layer 0) and required at import time.
from src.backend.db.base import Base, _utc_now

# Lazy model re-exports: public name -> owner module that defines the class.
_MODEL_EXPORTS: dict[str, str] = {
    # auth
    "UserDB": "src.backend.auth.db_models",
    # broker
    "BrokerAccountDB": "src.backend.broker.db_models",
    # trading (agents + trades)
    "AgentConfigDB": "src.backend.trading.db_models",
    "AgentDecisionLogDB": "src.backend.trading.db_models",
    "TradeDB": "src.backend.trading.db_models",
    # trading (deployments)
    "PaperDeploymentDB": "src.backend.trading.deployment_models",
    "LiveDeploymentDB": "src.backend.trading.deployment_models",
    # backtesting
    "BatchJobDB": "src.backend.backtesting.db_models",
    "WaterfallReportDB": "src.backend.backtesting.db_models",
    # marketdata
    "PriceCacheDB": "src.backend.marketdata.db_models",
    "DataProviderDB": "src.backend.marketdata.db_models",
    # ai / research-orchestration
    "PromptTemplateDB": "src.backend.ai.db_models",
    "AIProviderDB": "src.backend.ai.db_models",
    "AIModelDB": "src.backend.ai.db_models",
    "ToolCallLogDB": "src.backend.ai.db_models",
    "ExperimentBudgetDB": "src.backend.ai.db_models",
    "ExperimentQueueDB": "src.backend.ai.db_models",
    "ResearchReportDB": "src.backend.ai.db_models",
    "ResearchSessionDB": "src.backend.ai.db_models",
    "ResearchSessionEventDB": "src.backend.ai.db_models",
    "ResearchSessionInsightDB": "src.backend.ai.db_models",
    "BacktestPlanDB": "src.backend.ai.db_models",
    "AutoResearchGoalDB": "src.backend.ai.db_models",
    "AgentRationaleDB": "src.backend.ai.db_models",
    "NotificationDB": "src.backend.ai.db_models",
}

__all__ = ["Base", "_utc_now", *_MODEL_EXPORTS]


def __getattr__(name: str) -> Any:  # PEP 562 — lazy, so no static capability edge
    module_path = _MODEL_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(module_path), name)


def __dir__() -> list[str]:
    return sorted(__all__)
