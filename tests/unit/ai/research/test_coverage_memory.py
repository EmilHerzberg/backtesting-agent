"""Functional acceptance tests for cross-run coverage memory v1 (ATDD contract).

See docs/design/COVERAGE-MEMORY-V1.md. AT-7 (overfitting-neutrality) is the headline quality gate that the
post-v1 focused review interrogates. Tests are grouped by acceptance criterion.
"""
from __future__ import annotations


import numpy as np
import pytest

from types import SimpleNamespace

from src.backend.ai.research import coverage as cov
from src.backend.ai.research.agent_llm import LLMHandle
from src.backend.ai.research.coverage import (
    CoverageMap,
    bin_params,
    cell_center,
    feasible_cells,
)
from src.backend.ai.research.strategist import (
    LLMStrategist,
    RuleBasedStrategist,
    _repair_params,
)


async def _propose_n(strat, n, asset="AAPL", families=("multi_factor",)):
    cells = []
    for _ in range(n):
        _, spec = await strat.propose(asset, list(families), [], {})
        cells.append(bin_params(spec["template_id"], spec["params"]))
    return cells


def _spread(template_id, cell_ids):
    """Mean nearest-neighbour distance among a set of cells (bigger = better spread)."""
    ns = cov._dim_ns(template_id)
    vecs = [cov._cell_vec(c) for c in set(cell_ids)]
    if len(vecs) < 2:
        return 0.0
    return sum(min(cov._dist(v, w, ns) for w in vecs if w != v) for v in vecs) / len(vecs)


# ── AT-1: the grid collapses near-duplicates, separates meaningful steps ───────────────────────────
@pytest.mark.finding("coverage-v1")
def test_at1_grid_collapses_near_duplicates_and_separates_meaningful_steps():
    # periods (v3: slow ratio 0.02): a +0.5% change (100→100.5) is the SAME cell; +10% is DIFFERENT.
    assert bin_params("sma_crossover", {"fast_period": 15, "slow_period": 100}) == \
           bin_params("sma_crossover", {"fast_period": 15, "slow_period": 100.5})
    assert bin_params("sma_crossover", {"fast_period": 15, "slow_period": 100}) != \
           bin_params("sma_crossover", {"fast_period": 15, "slow_period": 110})
    # thresholds (v3 calibrated 0.25-pt bins, scale-free tail): 20 vs 20.1 = same cell; 20 vs 20.5 = different.
    assert bin_params("rsi_reversion", {"period": 14, "buy_threshold": 20.0, "sell_threshold": 70.0}) == \
           bin_params("rsi_reversion", {"period": 14, "buy_threshold": 20.1, "sell_threshold": 70.0})
    assert bin_params("rsi_reversion", {"period": 14, "buy_threshold": 20.0, "sell_threshold": 70.0}) != \
           bin_params("rsi_reversion", {"period": 14, "buy_threshold": 20.5, "sell_threshold": 70.0})


@pytest.mark.finding("coverage-v1")
def test_at1_massive_collapse_of_the_raw_space():
    # The whole point: a huge raw space collapses to a MEANINGFUL cell count. Under the v3 warehouse-measured
    # grid (26 integer periods × 100 × 63 threshold bins ≈ 165k) the collapse from the ~1.6e8 raw lattice is
    # still ~3 orders of magnitude — the space is honestly LARGE because rsi thresholds measured scale-free.
    assert 100_000 <= len(feasible_cells("rsi_reversion")) <= 200_000
    assert 2_000 <= len(feasible_cells("sma_crossover")) <= 5_000


# ── C2 (noise-floor validation): integer-governed oscillator periods get one cell per integer ──────
@pytest.mark.finding("coverage-v1")
def test_c2_integer_governed_rsi_period_is_one_cell_per_integer():
    # A +1-integer RSI-period change flips >>5% of positions at EVERY base (measured), so the resolution is
    # integer, not the log ratio — every integer must be its own cell (28 vs 29 must NOT merge).
    cells = {bin_params("rsi_reversion", {"period": p, "buy_threshold": 30.0, "sell_threshold": 70.0})
             for p in range(5, 31)}
    assert len(cells) == 26                                    # 26 integers 5..30, none merged
    assert cov._mode("rsi_reversion", "period") == "int"
    assert cov._mode("sma_crossover", "slow_period") == "log"  # ratio-governed periods are unchanged


@pytest.mark.finding("coverage-v1")
def test_c1_multi_indicator_is_uncalibrated_and_coarse():
    # C1: multi_indicator is near-dead (0-11 in-market bars/9y) → uncalibratable. Its grid is deliberately
    # COARSE (few distinct strategies), NOT the ~13k the fine analogs implied, and it is flagged so v2 floors
    # its unreliable count out of the deflated-Sharpe N.
    assert "multi_indicator" in cov._UNCALIBRATED
    assert len(feasible_cells("multi_indicator")) < 300       # coarse (was ~13k with fine analogs)


# ── AT-2: feasibility — the SMA dead corner is excluded and every kept cell is self-consistent ─────
@pytest.mark.finding("coverage-v1")
def test_at2_dead_corner_excluded_and_feasible_cells_are_self_mapping():
    feas = feasible_cells("sma_crossover")
    # a fast-large / slow-small corner cell must NOT be drawable (its center repairs into another cell)
    dead = bin_params("sma_crossover", {"fast_period": 50, "slow_period": 20})
    center = cell_center("sma_crossover", dead)
    assert center["slow_period"] < center["fast_period"] + 5          # genuinely infeasible pre-repair
    assert dead not in feas
    # invariant: every drawable cell's center stays in its own cell after _repair_params
    for cid in feas:
        c = cell_center("sma_crossover", cid)
        assert bin_params("sma_crossover", _repair_params("sma_crossover", dict(c))) == cid


@pytest.mark.finding("coverage-v1")
def test_at2_feasible_cells_are_a_valid_drawable_subset():
    # feasible ⊆ the per-dim product, non-empty, and every drawable cell SELF-MAPS (its center bins back to
    # itself). Cells are dropped either by a constraint repair (sma) OR when the calibrated grid is finer than
    # the integer resolution so a cell has no distinct integer representative — both correct exclusions.
    for t in ("sma_crossover", "rsi_reversion", "bollinger_breakout", "macd_cross", "multi_indicator"):
        feas = feasible_cells(t)
        total = int(np.prod(cov._dim_ns(t)))
        assert 0 < len(feas) <= total, (t, len(feas), total)
        for cid in sorted(feas)[:300]:                        # sample keeps the big templates fast
            c = cell_center(t, cid)
            assert bin_params(t, _repair_params(t, dict(c))) == cid, (t, cid)


# ── AT-7: OVERFITTING-NEUTRALITY (the quality gate) ────────────────────────────────────────────────
@pytest.mark.finding("coverage-v1")
def test_at7_sampler_never_consults_performance():
    # Structural guard (widened per the v1 review): EVERY function on the selection path — cell pick AND
    # template rank AND the region/center helpers — must reference NO performance signal (steering by
    # performance = exploitation = overfitting). Token list broadened beyond "sharpe" to the common
    # aliases a future exploitation signal might use.
    # Check the NAMES each selection function actually references (co_names — attrs/globals it reads),
    # not raw source, so a docstring saying "never performance" can't false-trip. Catches a real
    # `self.best_sharpe` / `row.pnl` read; the broad token list covers common exploitation-signal aliases.
    perf_tokens = ("sharpe", "performance", "profit", "survived", "died",
                   "pnl", "edge", "score", "fitness", "reward", "alpha", "best_")
    guarded = (CoverageMap.pick_cell, CoverageMap.mark, CoverageMap.pct_covered,
               CoverageMap.unexplored_regions, cov.feasible_cells, cov.bin_params, cov.cell_center,
               cov._dist, RuleBasedStrategist._choose_spacefilling)
    for fn in guarded:
        referenced = " ".join(fn.__code__.co_names).lower()
        assert not any(tok in referenced for tok in perf_tokens), (fn.__name__, referenced)
    m = CoverageMap()
    assert "sharpe" not in "".join(vars(m).keys()).lower()   # in-memory map has no performance field


@pytest.mark.finding("coverage-v1")
def test_at7_coverage_table_has_no_performance_column():
    # Architectural neutrality (stronger than the source grep): the persisted coverage row physically
    # carries NO performance column, so no future writer can populate a Sharpe the sampler might read.
    from src.backend.ai.research.db_models import ResearchCoverageDB
    cols = {c.name.lower() for c in ResearchCoverageDB.__table__.columns}
    banned = ("sharpe", "return", "profit", "pnl", "survived", "died", "best", "score", "edge", "alpha")
    assert not any(b in c for c in cols for b in banned), cols


@pytest.mark.finding("coverage-v1")
def test_at7_summary_is_spread_only_no_cherry_pick_menu():
    m = CoverageMap()
    rng = np.random.default_rng(3)
    for _ in range(5):
        c = m.pick_cell("sma_crossover", "AAPL", rng)
        m.mark("sma_crossover", "AAPL", c)
    s = m.summary()
    # spread stats + the honesty caveat ONLY — NO per-cell/per-strategy performance ranking
    assert set(s.keys()) == {"novelty_rate", "cells_visited", "pct_covered_by_template", "grid_version", "caveat"}
    # the per-template datum is a COVERAGE FRACTION in [0,1], never a performance number to sort on
    assert all(0.0 <= v <= 1.0 for v in s["pct_covered_by_template"].values())


@pytest.mark.finding("coverage-v1")
def test_f1_reachable_is_canonical_superset_of_feasible():
    # F1: reachable_cells (the canonical distinct-strategy count for the denominator + v2 N) is a superset of
    # feasible_cells (the maximin draw domain). They differ ONLY at sma's constraint boundary (2 cells); the
    # other four templates are identical.
    from src.backend.ai.research.coverage import reachable_cells
    for t in ("sma_crossover", "rsi_reversion", "bollinger_breakout", "macd_cross", "multi_indicator"):
        assert feasible_cells(t) <= reachable_cells(t)
    assert len(reachable_cells("sma_crossover")) == 3572 and len(feasible_cells("sma_crossover")) == 3569
    for t in ("rsi_reversion", "bollinger_breakout", "macd_cross", "multi_indicator"):
        assert reachable_cells(t) == feasible_cells(t)


@pytest.mark.finding("coverage-v1")
def test_pct_covered_never_exceeds_one():
    # Quant-review fix: the saturation/LLM path can mark a cell outside the canonical set, which used to push
    # pct_covered above 100%. The denominator is reachable_cells and visited ⊆ reachable → ratio ≤ 1.0.
    from src.backend.ai.research.coverage import reachable_cells
    m = CoverageMap()
    for c in reachable_cells("sma_crossover"):
        m.mark("sma_crossover", "AAPL", c)
    m.mark("sma_crossover", "AAPL", "v2:99-99")        # a bogus out-of-set cell
    assert m.pct_covered("sma_crossover", "AAPL") == pytest.approx(1.0)
    assert m.pct_covered("sma_crossover", "AAPL") <= 1.0


@pytest.mark.finding("coverage-v1")
def test_at7_summary_ships_cross_run_honesty_caveat():
    # The review's HIGH finding: coverage % accumulates across runs but significance is per-run only.
    # summary() must ship a plain-language caveat that says so — no silent lying-by-omission.
    s = CoverageMap().summary()
    cav = s["caveat"].lower()
    assert "per" in cav or "that run" in cav              # significance is per-run…
    assert "out-of-sample" in cav or "re-validate" in cav  # …treat a campaign winner as a hypothesis
    assert not any(ch.isdigit() for ch in s["caveat"])   # digit-free (safe for the report narrative)


# ── AT-8 (map half): novelty rate is computed ──────────────────────────────────────────────────────
@pytest.mark.finding("coverage-v1")
def test_at8_novelty_rate_drops_as_space_saturates():
    m = CoverageMap()
    rng = np.random.default_rng(3)
    # fresh picks are all novel → rate 1.0
    for _ in range(8):
        c = m.pick_cell("sma_crossover", "AAPL", rng)
        assert c is not None
        m.mark("sma_crossover", "AAPL", c)
    assert m.novelty_rate() == pytest.approx(1.0)
    # re-marking already-visited cells drops novelty
    for c in list(m.visited[("sma_crossover", "AAPL")])[:8]:
        m.mark("sma_crossover", "AAPL", c)
    assert m.novelty_rate() < 1.0


# ── maximin picker: farthest-point spreads, respects feasibility, saturates cleanly ────────────────
@pytest.mark.finding("coverage-v1")
def test_maximin_picks_are_feasible_unvisited_and_saturate_to_none():
    m = CoverageMap()
    rng = np.random.default_rng(3)
    feas = feasible_cells("macd_cross")
    picked = set()
    while True:
        c = m.pick_cell("macd_cross", "KO", rng)
        if c is None:
            break
        assert c in feas and c not in picked      # always feasible + never a repeat
        picked.add(c)
        m.mark("macd_cross", "KO", c)
    assert picked == set(feas)                     # exhausts exactly the feasible set, then returns None


# ── AT-3: within-run space-filling spreads wider than uniform ──────────────────────────────────────
@pytest.mark.finding("coverage-v1")
async def test_at3_coverage_spreads_wider_than_uniform_within_a_run():
    n = 30
    cov_cells = await _propose_n(RuleBasedStrategist(seed=3, coverage=CoverageMap()), n)
    uni_cells = await _propose_n(RuleBasedStrategist(seed=3, coverage=None), n)
    assert len(set(cov_cells)) == n                              # coverage never repeats a cell
    assert _spread("multi_indicator", cov_cells) > _spread("multi_indicator", uni_cells)  # maximin spreads


# ── AT-4: cross-run memory — run B (same seed) digs DIFFERENT ground than run A ─────────────────────
@pytest.mark.finding("coverage-v1")
async def test_at4_cross_run_memory_makes_run_b_disjoint_from_run_a():
    # Run A explores; its visited set is "persisted" (we reuse the same CoverageMap for B, as load_coverage would).
    shared = CoverageMap()
    a_cells = await _propose_n(RuleBasedStrategist(seed=3, coverage=shared), 20)
    b_cells = await _propose_n(RuleBasedStrategist(seed=3, coverage=shared), 20)   # SAME seed, memory loaded
    assert set(a_cells).isdisjoint(set(b_cells))                # B never re-treads A's cells — the fix

    # Contrast: with coverage OFF and the same seed, the two runs are IDENTICAL (the bug this fixes).
    off_a = await _propose_n(RuleBasedStrategist(seed=3, coverage=None), 20)
    off_b = await _propose_n(RuleBasedStrategist(seed=3, coverage=None), 20)
    assert off_a == off_b


# ── AT-5: flag OFF ⇒ behaviour identical to the current baseline ────────────────────────────────────
@pytest.mark.finding("coverage-v1")
async def test_at5_flag_off_is_unchanged_baseline():
    a = await _propose_n(RuleBasedStrategist(seed=7, coverage=None), 12, families=("trend_following",))
    b = await _propose_n(RuleBasedStrategist(seed=7, coverage=None), 12, families=("trend_following",))
    assert a == b
    # and the OFF path adds no coverage provenance to the spec
    _, spec = await RuleBasedStrategist(seed=7, coverage=None).propose("AAPL", ["trend_following"], [], {})
    assert "cell_id" not in spec and "coverage_saturated" not in spec


# ── AT-6: LLM soft nudge — regions surfaced, cell-collision NOT rejected (no billed-call waste) ─────
class _MockProvider:
    def __init__(self, content):
        self.content = content

    async def chat_completion(self, req):
        return SimpleNamespace(content=self.content,
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10, total_tokens=20))


@pytest.mark.finding("coverage-v1")
async def test_at6_llm_render_surfaces_unexplored_regions():
    fb = RuleBasedStrategist(seed=1, coverage=CoverageMap())
    strat = LLMStrategist(LLMHandle(provider=None, model="m", input_price_per_m=0.0, output_price_per_m=0.0),
                          None, fb)
    rendered = strat._render("AAPL", ["rsi_reversion"], [], {})
    assert "unexplored_regions" in rendered and "coverage_hint" in rendered


@pytest.mark.finding("coverage-v1")
async def test_at6_llm_proposal_on_a_visited_cell_is_kept_not_rejected():
    import json

    params = {"period": 14, "buy_threshold": 30.0, "sell_threshold": 70.0}
    cell = bin_params("rsi_reversion", params)
    m = CoverageMap()
    m.mark("rsi_reversion", "AAPL", cell, strategy_hash="some-other-point-in-this-cell")  # cell already visited
    fb = RuleBasedStrategist(seed=1, coverage=m)
    body = json.dumps({"template_id": "rsi_reversion", "params": params,
                       "economic_rationale": "mean reversion", "claimed_mechanism": "x",
                       "falsifiable_prediction": "y"})
    strat = LLMStrategist(LLMHandle(provider=_MockProvider(body), model="m",
                                    input_price_per_m=0.0, output_price_per_m=0.0),
                          None, fb)
    hyp, spec = await strat.propose("AAPL", ["rsi_reversion"], [], {})
    assert hyp.author == "llm_strategist"          # the LLM point was ACCEPTED despite the visited cell…
    assert strat.fallback_after_bill == 0          # …no billed-but-discarded fallback (budget-safe)


# ── AT-9: persistence round-trip + backfill ────────────────────────────────────────────────────────
async def _shared_engine():
    from sqlalchemy import StaticPool
    from sqlalchemy.ext.asyncio import create_async_engine

    from src.backend.db.init_db import create_tables
    eng = create_async_engine("sqlite+aiosqlite:///:memory:",
                              connect_args={"check_same_thread": False}, poolclass=StaticPool)
    await create_tables(eng)
    return eng


@pytest.mark.finding("coverage-v1")
async def test_at9_persist_load_roundtrip_and_backfill(monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.backend.ai.research import db_models
    from src.backend.ai.research.coverage import backfill_coverage, load_coverage, persist_coverage
    from src.backend.db import engine as engine_mod
    from src.backend.db.init_db import drop_tables

    eng = await _shared_engine()
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(engine_mod, "async_session", factory)
    try:
        # visit some cells, persist, load into a fresh map → same visited set
        m = CoverageMap()
        rng = np.random.default_rng(3)
        for _ in range(6):
            c = m.pick_cell("sma_crossover", "AAPL", rng)
            m.mark("sma_crossover", "AAPL", c, strategy_hash="h" + c)
        assert await persist_coverage("0", "", m) == 6
        m2 = await load_coverage("0", ["AAPL"], "")
        assert m2.visited[("sma_crossover", "AAPL")] == m.visited[("sma_crossover", "AAPL")]
        # persist is idempotent (upsert → visit_count++, no new rows)
        assert await persist_coverage("0", "", m) == 0

        # backfill reconstructs cells from a historical candidate/failure row
        import json as _json
        async with factory() as s:
            s.add(db_models.ResearchRunDB(goal_id="g1", user_id=7, mode="robustness"))
            s.add(db_models.ResearchFailureDB(goal_id="g1", strategy_hash="hh", template_id="macd_cross",
                                              security_id="KO", params_json=_json.dumps(
                                                  {"fast": 8, "slow": 30, "signal_period": 9})))
            await s.commit()
        assert await backfill_coverage("7", "") >= 1
        m3 = await load_coverage("7", ["KO"], "")
        assert ("macd_cross", "KO") in m3.visited
    finally:
        await drop_tables(eng)
        await eng.dispose()


# ── AT-10: a saturated space SIGNALS but does NOT auto-stop ─────────────────────────────────────────
@pytest.mark.finding("coverage-v1")
async def test_at10_saturation_signals_but_does_not_stop():
    m = CoverageMap()
    for c in feasible_cells("multi_indicator"):          # exhaust the whole feasible space up front
        m.mark("multi_indicator", "AAPL", c)
    strat = RuleBasedStrategist(seed=3, coverage=m)
    hyp, spec = await strat.propose("AAPL", ["multi_factor"], [], {})
    assert spec["coverage_saturated"] is True            # honestly signals saturation…
    assert spec["template_id"] == "multi_indicator" and spec["params"]   # …but still proposes (no stall/stop)


# ── AT-8 (report half) + AT-7 (run level): a real run surfaces SPREAD telemetry, no cherry-pick menu ─
@pytest.mark.finding("coverage-v1")
async def test_at8_run_surfaces_coverage_spread_telemetry(monkeypatch, frozen_ohlcv):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.backend.ai.research.report_generator import serialize_report
    from src.backend.ai.research.run import run_research
    from src.backend.db import engine as engine_mod
    from src.backend.db.init_db import drop_tables

    eng = await _shared_engine()
    monkeypatch.setattr(engine_mod, "async_session",
                        async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False))
    try:
        report = await run_research(
            goal="coverage smoke", assets=["AAPL", "MSFT"], fetch_fn=frozen_ohlcv,
            max_runs=12, target_candidates=3, rigor="exploratory", seed=3,
            agent_mode="rule_based", enable_oos=False, coverage_memory=True, user_id=1)
        ident = next(s for s in serialize_report(report)["sections"] if s["key"] == "strategy_identity")
        c = ident["numeric_fields"].get("coverage")
        assert c and "novelty_rate" in c and c["cells_visited"] > 0 and c["grid_version"] == "v3"
        # spread only: the per-template map holds COVERAGE FRACTIONS, and there is no performance ranking key
        assert all(0.0 <= v <= 1.0 for v in c["pct_covered_by_template"].values())
        assert not any(k in c for k in ("best_sharpe", "best_cell", "ranking", "top_cells"))
        # the cross-run honesty caveat reaches the user in the (digit-free) report narrative
        assert "does not correct" in ident["narrative"].lower() or "re-validate" in ident["narrative"].lower()
    finally:
        await drop_tables(eng)
        await eng.dispose()
