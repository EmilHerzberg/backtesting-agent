"""Regime P1 — run_research window routing + StartRunRequest validation (review fixes M1/S1/S2/S3)."""

import pytest
from pydantic import ValidationError

from src.backend.ai.research.router import StartRunRequest
from src.backend.ai.research.run import run_research


# ── StartRunRequest validation (the API boundary) ──

def test_request_robustness_default_ok():
    assert StartRunRequest(goal_text="x").mode == "robustness"


def test_request_regime_requires_both_window_bounds():
    with pytest.raises(ValidationError):
        StartRunRequest(goal_text="x", mode="regime", window_start="2022-01-01")  # missing end
    with pytest.raises(ValidationError):
        StartRunRequest(goal_text="x", mode="regime")                              # missing both


def test_request_regime_rejects_bad_dates_and_order():
    with pytest.raises(ValidationError):
        StartRunRequest(goal_text="x", mode="regime", window_start="not-a-date", window_end="2023-01-01")
    with pytest.raises(ValidationError):
        StartRunRequest(goal_text="x", mode="regime", window_start="2023-01-01", window_end="2022-01-01")


def test_request_rejects_unknown_mode():
    with pytest.raises(ValidationError):
        StartRunRequest(goal_text="x", mode="Regime")   # wrong case / unknown enum


def test_request_regime_valid_ok():
    r = StartRunRequest(goal_text="x", mode="regime", window_start="2022-01-01", window_end="2023-06-30")
    assert (r.window_start, r.window_end) == ("2022-01-01", "2023-06-30")


def test_request_robustness_ignores_window():
    # robustness with a window is allowed (window simply ignored downstream) — no error.
    assert StartRunRequest(goal_text="x", mode="robustness",
                           window_start="2022-01-01", window_end="2023-01-01").mode == "robustness"


# ── run_research guard (defense for direct callers; raises BEFORE the pipeline) ──

async def test_run_research_regime_partial_window_raises():
    with pytest.raises(ValueError):
        await run_research(goal="x", assets=["SPY"], mode="regime", window_start="2022-01-01")


async def test_run_research_regime_bad_order_raises():
    with pytest.raises(ValueError):
        await run_research(goal="x", assets=["SPY"], mode="regime",
                           window_start="2023-01-01", window_end="2022-01-01")


@pytest.mark.finding("M31")
def test_state_response_exposes_train_end():
    # M31: the /state response must carry train_end so the UI can label regime candidate metrics with the
    # train slice they were measured on, instead of the full window.
    from src.backend.ai.research.router import ResearchStateResponse

    assert "train_end" in ResearchStateResponse.model_fields   # pre-fix: field absent


@pytest.mark.finding("M52")
def test_create_run_rejects_unknown_enums_and_bad_budgets():
    # M52: agent_mode/rigor were free strings (silently coerced — a leakage marker set then 0 LLM calls;
    # rigor fell back to standard) and budgets were unbounded. Reject them up front.
    with pytest.raises((ValueError, ValidationError)):
        StartRunRequest(goal_text="x", agent_mode="turbo_mode")   # unknown agent_mode
    with pytest.raises((ValueError, ValidationError)):
        StartRunRequest(goal_text="x", rigor="ultra")             # unknown rigor
    with pytest.raises((ValueError, ValidationError)):
        StartRunRequest(goal_text="x", max_runs=0)                # non-positive run budget
    with pytest.raises((ValueError, ValidationError)):
        StartRunRequest(goal_text="x", max_eur=-5)                # negative euro cap
    # a valid request (incl. max_eur=0 = "no cap") still constructs
    StartRunRequest(goal_text="x", agent_mode="full_ai", rigor="strict", max_runs=10, max_eur=0.0)
