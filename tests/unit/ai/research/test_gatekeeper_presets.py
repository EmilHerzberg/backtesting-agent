"""M20 — rigor presets must bind the cost-stress floor coherently.

Review finding M20: `build_default_pipeline` scaled the perf floor and cost multiplier but never
touched `CostStressGate.MIN_STRESSED_SHARPE` (hardcoded 0.5). So a strategy with 0.3 <= Sharpe < 0.5
passed the exploratory perf floor (min_sharpe 0.3) and then deterministically hard-failed cost_stress
— the sub-0.5 exploratory tier could accept nothing. The fix adds `min_stressed_sharpe` to each
preset and applies it, keeping it <= the preset's `min_sharpe`.
"""
from __future__ import annotations

import pytest

from src.backend.ai.research.gatekeeper import RIGOR_PRESETS, build_default_pipeline
from src.backend.backtesting.gates.cost_stress_gate import CostStressGate


@pytest.mark.finding("M20")
@pytest.mark.parametrize("name", ["exploratory", "standard", "strict"])
def test_stressed_sharpe_floor_binds_and_is_coherent(name):
    preset = RIGOR_PRESETS[name]
    # Every preset carries a stressed-Sharpe floor, and it is <= its unstressed perf floor …
    assert "min_stressed_sharpe" in preset
    assert preset["min_stressed_sharpe"] <= preset["min_sharpe"]
    # … and build_default_pipeline actually applies it to the cost-stress gate (was hardcoded 0.5).
    pipeline = build_default_pipeline(preset)
    cost = next(g for g in pipeline.gates if isinstance(g, CostStressGate))
    assert cost.MIN_STRESSED_SHARPE == preset["min_stressed_sharpe"]


@pytest.mark.finding("M20")
def test_exploratory_below_half_sharpe_is_reachable():
    # A strategy at Sharpe ~0.35 (exploratory min_sharpe 0.3) must not be structurally killed by an
    # un-preset 0.5 cost-stress floor — with the preset applied the floor is below 0.35.
    preset = RIGOR_PRESETS["exploratory"]
    pipeline = build_default_pipeline(preset)
    cost = next(g for g in pipeline.gates if isinstance(g, CostStressGate))
    assert cost.MIN_STRESSED_SHARPE < 0.35
