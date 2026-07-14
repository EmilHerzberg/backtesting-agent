"""ATSX-09 (B) — persistence schema for the autonomous research loop.

Four tables, owned by the ``ai.research`` module, registered on
``Base.metadata`` via the bootstrap composition root so ``create_all``
creates them (the established pattern for new tables — see bootstrap.py).

The loop (ATSX-10 / A-2) is the writer; the router endpoints are readers.
Heavy blobs (per-bar returns, full equity curves) stay in the existing
results/parquet store and are referenced here, not duplicated.

Link column: every child row carries ``goal_id`` (the public run id, also
``research_runs.goal_id``). Following the codebase convention, cross-table
references are logical FKs (indexed columns), not enforced ForeignKey
constraints (SQLite does not enforce them by default anyway).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.backend.db.base import Base, _utc_now


class ResearchRunDB(Base):
    """One autonomous research run (the durable mirror of RunRecord/ResearchState)."""

    __tablename__ = "research_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goal_id: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)

    goal_text: Mapped[str] = mapped_column(Text, default="")
    asset_pool_json: Mapped[str] = mapped_column(Text, default="[]")
    strategy_families_json: Mapped[str] = mapped_column(Text, default="[]")

    status: Mapped[str] = mapped_column(String(20), default="running")  # running|completed|failed|interrupted
    phase: Mapped[str] = mapped_column(String(30), default="goal_received")
    current_asset: Mapped[str] = mapped_column(String(40), default="")
    current_lineage: Mapped[str] = mapped_column(String(64), default="")

    max_runs: Mapped[int] = mapped_column(Integer, default=0)
    max_eur: Mapped[float] = mapped_column(Float, default=0.0)
    max_seconds: Mapped[int] = mapped_column(Integer, default=0)
    used_runs: Mapped[int] = mapped_column(Integer, default=0)
    used_eur: Mapped[float] = mapped_column(Float, default=0.0)
    # M57 (model-honesty): hard LLM-call failures that forced a rule-based/templated fallback. > 0 on an
    # AI run ⇒ the run silently degraded; the persisted /state path reads this so a reloaded (post-restart)
    # run stays honest, matching the live path + the report banner. (Migration entry in bootstrap._MIGRATIONS.)
    llm_failures: Mapped[int] = mapped_column(Integer, default=0)
    target_candidates: Mapped[int] = mapped_column(Integer, default=3)

    # G3: how the run was configured (reproducibility + honesty — "how was this run run?")
    agent_mode: Mapped[str] = mapped_column(String(20), default="rule_based")
    provider: Mapped[str] = mapped_column(String(60), default="")
    model: Mapped[str] = mapped_column(String(80), default="")
    seed: Mapped[int] = mapped_column(Integer, default=0)
    rigor: Mapped[str] = mapped_column(String(20), default="")
    enable_oos: Mapped[bool] = mapped_column(Boolean, default=False)
    # P1 Chunk C — regime mode + effective window
    mode: Mapped[str] = mapped_column(String(20), default="robustness")
    window_start: Mapped[str] = mapped_column(String(20), default="")
    window_end: Mapped[str] = mapped_column(String(20), default="")
    train_end: Mapped[str] = mapped_column(String(20), default="")  # P2: regime select-on-train split boundary
    provider_type: Mapped[str] = mapped_column(String(30), default="")  # P2: effective LLM provider (leakage marker)
    model_id: Mapped[str] = mapped_column(String(60), default="")        # H31: effective model (per-model leakage)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str] = mapped_column(Text, default="")
    report_json: Mapped[str] = mapped_column(Text, default="{}")  # A-8: serialized FinalReport
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class ResearchEventDB(Base):
    """Append-only activity stream — one row per loop phase transition."""

    __tablename__ = "research_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goal_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    phase: Mapped[str] = mapped_column(String(30), default="")
    lineage_id: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(String(200), default="")
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    strategy_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ResearchCandidateDB(Base):
    """A strategy that survived gates + critic (durable mirror of Candidate)."""

    __tablename__ = "research_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goal_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    strategy_hash: Mapped[str] = mapped_column(String(64), default="")
    run_artifact_id: Mapped[str] = mapped_column(String(64), default="")
    template_id: Mapped[str] = mapped_column(String(60), default="")
    security_id: Mapped[str] = mapped_column(String(40), default="")

    sharpe_annual: Mapped[float] = mapped_column(Float, default=0.0)
    total_return: Mapped[float] = mapped_column(Float, default=0.0)
    max_drawdown: Mapped[float] = mapped_column(Float, default=0.0)
    n_trades: Mapped[int] = mapped_column(Integer, default=0)
    critic_confidence: Mapped[str] = mapped_column(String(20), default="low")

    critique_json: Mapped[str] = mapped_column(Text, default="{}")
    gate_report_json: Mapped[str] = mapped_column(Text, default="{}")
    artifacts_json: Mapped[str] = mapped_column(Text, default="{}")  # ATSX-27: regime/benchmark/equity
    oos_outcome: Mapped[str] = mapped_column(String(10), default="PENDING")  # PASS|FAIL|PENDING
    lineage_id: Mapped[str] = mapped_column(String(64), default="")
    hypothesis_id: Mapped[str] = mapped_column(String(64), default="", index=True)  # -> research_hypotheses
    params_json: Mapped[str] = mapped_column(Text, default="{}")                    # the actual chosen params
    # P1 Chunk C — regime firewall (empty for robustness candidates)
    validation_status: Mapped[str] = mapped_column(String(20), default="")
    confidence: Mapped[str] = mapped_column(String(20), default="")
    decay_json: Mapped[str] = mapped_column(Text, default="{}")
    weaknesses_json: Mapped[str] = mapped_column(Text, default="[]")   # idea-surfacing — soft-failed gates
    holdout_json: Mapped[str] = mapped_column(Text, default="{}")      # P2 — within-regime hold-out result
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class ResearchFailureDB(Base):
    """A strategy that died in the gates/critic — the graveyard (mirror of FailureContext)."""

    __tablename__ = "research_failures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goal_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    strategy_hash: Mapped[str] = mapped_column(String(64), default="")
    template_id: Mapped[str] = mapped_column(String(60), default="")
    security_id: Mapped[str] = mapped_column(String(40), default="")
    failed_gate: Mapped[str] = mapped_column(String(60), default="", index=True)
    gate_details_json: Mapped[str] = mapped_column(Text, default="{}")
    critic_notes: Mapped[str] = mapped_column(Text, default="")
    failure_reason: Mapped[str] = mapped_column(Text, default="")
    hypothesis_id: Mapped[str] = mapped_column(String(64), default="", index=True)  # -> research_hypotheses
    params_json: Mapped[str] = mapped_column(Text, default="{}")                    # the actual chosen params
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class ResearchHypothesisDB(Base):
    """The proposal/reasoning record — one row per attempt (durable mirror of Hypothesis).

    Failures + candidates reference it by ``hypothesis_id`` so a killed/surviving
    attempt resolves to *what was proposed and why*.
    """

    __tablename__ = "research_hypotheses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goal_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    hypothesis_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    author: Mapped[str] = mapped_column(String(40), default="")
    economic_rationale: Mapped[str] = mapped_column(Text, default="")
    claimed_mechanism: Mapped[str] = mapped_column(Text, default="")
    falsifiable_prediction: Mapped[str] = mapped_column(Text, default="")
    proposed_template_id: Mapped[str] = mapped_column(String(60), default="")
    proposed_param_ranges_json: Mapped[str] = mapped_column(Text, default="{}")
    prior_strength: Mapped[str] = mapped_column(String(20), default="low")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class ResearchLineageDB(Base):
    """G4: one node of the run's lineage tree (durable mirror of state.lineage_nodes)."""

    __tablename__ = "research_lineage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goal_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    lineage_id: Mapped[str] = mapped_column(String(64), default="")
    parent_lineage_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    root_strategy_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    declared_by: Mapped[str] = mapped_column(String(40), default="")
    node_created_at: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class ResearchCoverageDB(Base):
    """Cross-run space-filling coverage map (v1). One upserted row per VISITED cell of a template's
    hyperparameter grid, so new runs sample UNVISITED cells instead of re-testing near-duplicates.
    Brand-new table → create_all builds it; NO bootstrap._MIGRATIONS entry needed (that is only for
    columns added to EXISTING tables). Reconstructable from research_candidates+research_failures
    (coverage.backfill_coverage) — a denormalized accelerator, never the sole source of truth.

    Keyed per (scope_key=user_id, template_id, security_id, window_key, cell_id): the tested space is
    inherently per-asset (the strategy hash folds in security_id) and per-template (disjoint param dims);
    window_key namespaces robustness ("") vs each regime window. See docs/design/COVERAGE-MEMORY-V1.md.
    """

    __tablename__ = "research_coverage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_key: Mapped[str] = mapped_column(String(40), index=True, default="0")     # user_id (multiplicity/tenant isolation)
    template_id: Mapped[str] = mapped_column(String(60), index=True, default="")
    security_id: Mapped[str] = mapped_column(String(40), index=True, default="")    # asset
    window_key: Mapped[str] = mapped_column(String(48), default="")                 # "" = robustness (fixed window); "<ws>:<we>" = regime
    grid_version: Mapped[str] = mapped_column(String(8), default="v1")              # binning scheme version (re-tuning never collides)
    cell_id: Mapped[str] = mapped_column(String(64), default="")
    exemplar_hash: Mapped[str] = mapped_column(String(64), default="")              # one strategy_hash that landed here (join to candidates/failures)
    visit_count: Mapped[int] = mapped_column(Integer, default=0)
    # v1 deliberately stores NO per-cell performance (Sharpe / survived / died). Coverage is a pure SPATIAL
    # memory — recording performance here would invite a future writer to steer sampling toward high-Sharpe
    # cells (exploitation → overfitting, the exact thing coverage must NOT do). Any performance-aware
    # scoring is a v2 decision that ships WITH its cross-run multiple-testing correction, not before.
    last_goal_id: Mapped[str] = mapped_column(String(40), default="")
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
