"""Confidence-surfacing — quality_summary unit tests (CONFIDENCE-SURFACING-SPEC v2 §6)."""

from __future__ import annotations

import pytest

from src.backend.ai.research.quality import quality_summary


def _report(activity=None, benchmark=None, dsr=None):
    results = []
    if activity is not None:
        results.append({"gate_id": "minimum_activity", "status": "PASS", "details": activity})
    if benchmark is not None:
        results.append({"gate_id": "benchmark_relative", "status": "PASS", "details": benchmark})
    if dsr is not None:
        results.append({"gate_id": "deflated_sharpe", "status": "PASS", "details": dsr})
    return {"results": results}


# 1 — strong: adequate tier + positive excess + OOS PASS.
def test_strong():
    q = quality_summary(
        _report(activity={"tier": "adequate", "t_stat": 2.4}, benchmark={"excess_return": 0.06}),
        oos="PASS", mode="robustness",
    )
    assert q["tier"] == "strong"
    assert "passed out-of-sample" in q["headline"]
    assert q["per_trade_t"] == 2.4


# 2 — OOS FAIL forces weak even with a strong edge.
def test_oos_fail_forces_weak():
    q = quality_summary(
        _report(activity={"tier": "adequate", "t_stat": 3.0}, benchmark={"excess_return": 0.10}),
        oos="FAIL", mode="robustness",
    )
    assert q["tier"] == "weak"
    assert "FAILED out-of-sample" in q["headline"]


# 2b — thin tier + positive excess → moderate; no excess → weak.
def test_moderate_and_weak():
    mod = quality_summary(
        _report(activity={"tier": "thin", "t_stat": 1.2}, benchmark={"excess_return": 0.03}),
        oos="OFF", mode="robustness",
    )
    assert mod["tier"] == "moderate"
    weak = quality_summary(
        _report(activity={"tier": "adequate", "t_stat": 2.0}, benchmark={"excess_return": -0.02}),
        oos="OFF", mode="robustness",
    )
    assert weak["tier"] == "weak"
    assert "did not beat buy-and-hold" in weak["headline"]


# OFF/PENDING are neutral (CF-2): a strong edge still grades strong without OOS.
def test_oos_off_neutral():
    q = quality_summary(
        _report(activity={"tier": "adequate", "t_stat": 2.4}, benchmark={"excess_return": 0.06}),
        oos="", mode="robustness",
    )
    assert q["oos"] == "OFF"
    assert q["tier"] == "strong"


# 3 — DSR provisional: flag OR trials<20 OR defaulted variance; solid only otherwise.
def test_dsr_provisional_paths():
    flagged = quality_summary(_report(dsr={"dsr": 0.9, "n_trials": 8, "provisional": True}), mode="robustness")
    assert flagged["dsr"]["provisional"] is True

    few = quality_summary(_report(dsr={"dsr": 0.97, "n_trials": 15, "sr_variance": 0.02}), mode="robustness")
    assert few["dsr"]["provisional"] is True  # trials < 20

    # M24: the gate now emits an explicit sr_variance_defaulted flag; quality reads that instead of
    # sniffing the magic 0.001 value (a genuinely-measured 0.001 must NOT be mislabeled provisional).
    defaulted = quality_summary(
        _report(dsr={"dsr": 0.97, "n_trials": 50, "sr_variance": 0.001, "sr_variance_defaulted": True}),
        mode="robustness",
    )
    assert defaulted["dsr"]["provisional"] is True  # defaulted variance flagged explicitly (CS-4/M24)

    solid = quality_summary(_report(dsr={"dsr": 0.97, "n_trials": 50, "sr_variance": 0.02}), mode="robustness")
    assert solid["dsr"]["provisional"] is False
    assert solid["dsr"]["value"] == 0.97


@pytest.mark.finding("M24")
def test_measured_variance_equal_to_floor_is_not_provisional():
    """P1-12: a genuinely-measured 0.001 variance (flag False) must NOT be provisional — the fix reads
    the explicit sr_variance_defaulted flag, not a magic-value sniff of 0.001 (which would fail here)."""
    r = quality_summary(
        _report(dsr={"dsr": 0.97, "n_trials": 50, "sr_variance": 0.001, "sr_variance_defaulted": False}),
        mode="robustness",
    )
    assert r["dsr"]["provisional"] is False


def test_dsr_absent_is_none():
    q = quality_summary(_report(activity={"tier": "adequate", "t_stat": 2.0}), mode="robustness")
    assert q["dsr"] is None


# 4 — regime content (C-5): tier from confidence/validation_status; UNVALIDATED framing dominates.
def test_regime_unvalidated_carries_framing():
    q = quality_summary(
        _report(activity={"tier": "thin", "t_stat": 1.1}),
        mode="regime", confidence="moderate", validation_status="unvalidated",
        weaknesses=[{"gate": "cost_stress"}],
    )
    assert q["tier"] == "moderate"
    assert "UNVALIDATED" in q["headline"]
    assert "1 weakness flagged" in q["headline"]


def test_regime_validated_and_failed():
    val = quality_summary({}, mode="regime", validation_status="regime_validated", confidence="moderate")
    assert val["tier"] == "validated" and "VALIDATED" in val["headline"]
    fail = quality_summary({}, mode="regime", validation_status="regime_failed", confidence="very_low")
    assert fail["tier"] == "failed" and "FAILED" in fail["headline"]


# nullable / no-crash (CF-3/CF-4): an empty report grades "provisional", never crashes.
def test_empty_report_provisional():
    q = quality_summary({}, mode="robustness")
    assert q["tier"] == "provisional"
    assert q["per_trade_t"] is None and q["benchmark_excess"] is None and q["dsr"] is None
