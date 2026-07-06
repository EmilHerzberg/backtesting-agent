"""Phase 2/3 review fixes — regression tests for the confirmed-finding remediations.

Covers: pending-drops-oos-marker (quality PENDING branch), m21-errored-gate (facade surfaces it),
m32-research-loop-still-end-exclusive (_default_fetch end-inclusive), lockbox-init no-silent-downgrade.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.backend.ai.research.quality import quality_summary


def _report(activity=None, benchmark=None):
    results = []
    if activity is not None:
        results.append({"gate_id": "minimum_activity", "status": "PASS", "details": activity})
    if benchmark is not None:
        results.append({"gate_id": "benchmark_relative", "status": "PASS", "details": benchmark})
    return {"results": results}


def test_pending_surfaces_marker_and_stays_capped_at_moderate():
    # Live /candidates defaults a missing OOS outcome to PENDING; the H5 marker must still appear.
    q = quality_summary(
        _report(activity={"tier": "adequate", "t_stat": 2.4}, benchmark={"excess_return": 0.06}),
        oos="PENDING", mode="robustness",
    )
    assert q["tier"] == "moderate"                       # only oos==PASS earns "strong"
    assert "pending" in q["headline"].lower()            # in-sample/no-hold-out disclosure present


def test_gatekeeper_surfaces_errored_gate_through_facade():
    from src.backend.ai.research.gatekeeper import ResearchGatekeeper
    from src.backend.backtesting.gates.pipeline import Gate, GatePipeline, GateSeverity

    class _Boom(Gate):
        gate_id = "boom"
        cost_rank = 1
        severity = GateSeverity.HARD

        def check(self, ctx):
            raise RuntimeError("boom")

    gk = ResearchGatekeeper()
    gk.pipeline = GatePipeline([_Boom()])
    res = gk.evaluate(metrics={"n_trades": 10}, returns=[0.0] * 10, context={})
    # M21: the errored hard gate is attributed via the new facade key (was dropped → None downstream).
    assert res["errored_gate"] == "boom"
    assert res["passed"] is False


def test_default_fetch_makes_yfinance_end_inclusive(monkeypatch):
    import yfinance

    import src.backend.ai.research.run as runmod

    captured: dict = {}

    class _Ticker:
        def __init__(self, symbol):
            pass

        def history(self, start=None, end=None):
            captured["end"] = end
            idx = pd.date_range(start, periods=3, freq="D")
            return pd.DataFrame(
                {"Open": [1, 1, 1], "High": [1, 1, 1], "Low": [1, 1, 1], "Close": [1, 1, 1], "Volume": [1, 1, 1]},
                index=idx,
            )

    monkeypatch.setattr(yfinance, "Ticker", _Ticker)
    runmod._default_fetch("AAPL", "2020-01-01", "2020-12-31")
    # M32: yfinance end is EXCLUSIVE → pass end+1 day so the last requested bar (2020-12-31) is included.
    assert captured["end"] == "2021-01-01"


async def test_requested_oos_that_cannot_init_raises_not_silently_in_sample(monkeypatch):
    # A run explicitly requesting OOS must fail loudly if the lockbox can't be built — never degrade
    # to counting in-sample candidates as "validated".
    import src.backend.backtesting.lockbox.service as svc

    def _boom(*a, **k):
        raise RuntimeError("cannot open db")

    monkeypatch.setattr(svc, "OOSLockboxService", _boom)
    from src.backend.ai.research.run import run_research

    with pytest.raises(RuntimeError, match="OOS validation was requested"):
        await run_research(
            goal="x", assets=["AAPL"], max_runs=1, target_candidates=1,
            agent_mode="rule_based", enable_oos=True, oos_db_path="/nonexistent/x.db",
            fetch_fn=lambda *a, **k: pd.DataFrame(),
        )
