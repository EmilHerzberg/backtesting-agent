"""PF5 tamper trip-wire: the live gate constants must match the frozen artifact.

Any drift between the code and docs/design/coverage-v2-gate-config.json fails
this test — forcing a DELIBERATE re-freeze commit (artifact + code together),
never a silent retune. This is the never-loosen invariant in executable form.
"""

import json

import pytest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
CFG = json.loads(
    (_REPO / "docs" / "design" / "coverage-v2-gate-config.json").read_text()
)["pf5_freeze"]


def test_dsr_gate_constants_match_the_freeze():
    from src.backend.backtesting.gates.deflated_sharpe import DeflatedSharpeGate
    f = CFG["dsr_gate"]
    assert DeflatedSharpeGate.gate_version == f["gate_version"]
    assert DeflatedSharpeGate.THRESHOLD == f["threshold"]
    assert DeflatedSharpeGate.PROVISIONAL_BELOW == f["provisional_below"]
    assert DeflatedSharpeGate.V_NULL_INFLATION == f["v_null_inflation"]


def test_oos_lockbox_constants_match_the_freeze():
    from src.backend.ai.research import loop
    f = CFG["oos_lockbox"]
    assert loop.VALIDATE_T == f["validate_t"]
    assert loop.OOS_MIN_SHARPE_DEFAULT == f["quality_floor_default"]
    assert list(loop.OOS_MIN_SHARPE_BAND) == f["quality_floor_band"]
    assert loop.OOS_TOTAL_RETURN_FLOOR == f["total_return_floor_default"]


def test_coverage_constants_match_the_freeze():
    from src.backend.ai.research.coverage import GRID_VERSION
    assert GRID_VERSION == CFG["coverage_v2"]["grid_version"]


def test_fb4_constants_match_the_freeze():
    from src.backend.backtesting.lockbox.service import (
        CAMPAIGN_ALPHA_FAMILY,
        CAMPAIGN_OOS_BUDGET,
        OOSLockboxService,
    )
    f = CFG["fb4_campaign_oos_control"]
    assert CAMPAIGN_OOS_BUDGET == f["campaign_oos_budget"]
    assert CAMPAIGN_ALPHA_FAMILY == f["campaign_alpha_family"]
    # the FIXED budget-sized family bar (review fix) — pinned so the formula cannot drift
    assert OOSLockboxService.campaign_adjusted_t(0) == pytest.approx(3.083, abs=0.005)
    assert OOSLockboxService.campaign_adjusted_t(49) == OOSLockboxService.campaign_adjusted_t(0)


def test_power_curve_evidence_hash_matches_the_freeze():
    # The provenance link is verifiable, not decorative: re-hash the on-disk evidence file.
    import hashlib
    curve = _REPO / "docs" / "design" / "coverage-v2-power-curve.json"
    prefix = CFG["d1_resolution"]["evidence_power_curve_sha256_prefix"]
    assert hashlib.sha256(curve.read_bytes()).hexdigest().startswith(prefix)


def test_api_and_run_defaults_defer_to_the_single_frozen_constant():
    # Contract fix: the 0.9 default lives in exactly ONE place (loop.py); the API and run layer
    # pass None -> resolved to the frozen constant, so the tamper-wire covers the whole chain.
    import inspect

    from src.backend.ai.research import run as run_mod
    from src.backend.ai.research.router import StartRunRequest
    assert StartRunRequest.model_fields["oos_min_sharpe"].default is None
    sig = inspect.signature(run_mod.run_research)
    assert sig.parameters["oos_min_sharpe"].default is None
