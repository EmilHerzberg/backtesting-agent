"""ATSX-10 (A-2) — durable persistence for the autonomous research loop.

Non-invasive observer: the research loop is unchanged. The API run driver
(router._run_and_track) creates a research_runs row at start, then a periodic
flusher mirrors the live ResearchState + buffered events into the
research_* tables. On restart, runs still marked ``running`` are orphaned
(their background task is gone) and flipped to ``interrupted``; the read
endpoints fall back to the DB so state survives a process restart.

All writes go through a module-level lock so concurrent runs don't trip
SQLite's single-writer lock.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select, update

from src.backend.db.engine import async_session
from src.backend.ai.research.db_models import (
    ResearchCandidateDB,
    ResearchEventDB,
    ResearchFailureDB,
    ResearchHypothesisDB,
    ResearchLineageDB,
    ResearchRunDB,
)
from src.backend.ai.research.report_generator import serialize_report

logger = logging.getLogger(__name__)

# Serialize all research-table writes (SQLite is single-writer).
_write_lock = asyncio.Lock()


def _json(obj: Any) -> str:
    try:
        return json.dumps(obj, default=str)
    except Exception:  # noqa: BLE001 — never let serialization kill a run
        return "{}"


def _utc_iso(dt: datetime | None) -> str | None:
    """M53: SQLite drops tzinfo on round-trip, so a ``DateTime(timezone=True)`` column reads back
    naive even though the stored value IS UTC. Re-attach UTC before serialization so the frontend's
    ``new Date(...)`` doesn't parse an offset-less string as LOCAL time (every event would be wrong by
    the user's UTC offset). Idempotent for already-aware datetimes."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    return str(dt)


async def create_run_row(goal_id: str, user_id: int, req: Any) -> None:
    """Insert the research_runs row when a run starts."""
    async with _write_lock, async_session() as session:
        session.add(
            ResearchRunDB(
                goal_id=goal_id,
                user_id=user_id,
                goal_text=req.goal_text,
                asset_pool_json=_json(req.asset_pool),
                strategy_families_json=_json(req.strategy_families),
                status="running",
                phase="goal_received",
                max_runs=req.max_runs,
                max_eur=req.max_eur,
                max_seconds=req.max_seconds,
                target_candidates=req.target_candidates,
                agent_mode=getattr(req, "agent_mode", "rule_based"),
                provider=getattr(req, "provider", None) or "",
                model=getattr(req, "model", None) or "",
                seed=getattr(req, "seed", 0),
                rigor=getattr(req, "rigor", ""),
                enable_oos=bool(getattr(req, "enable_oos", False)),
                mode=getattr(req, "mode", "robustness"),
                window_start=getattr(req, "window_start", None) or "",
                window_end=getattr(req, "window_end", None) or "",
                started_at=datetime.now(timezone.utc),
                # train_end is set by the loop (select-on-train split); back-filled in persist_snapshot.
            )
        )
        await session.commit()


async def persist_snapshot(rec: Any) -> None:
    """Mirror the live RunRecord/ResearchState + new buffered rows into the DB.

    Idempotent on rows already written (cursors on the RunRecord track how
    many events/candidates/failures have been flushed).
    """
    try:
        async with _write_lock, async_session() as session:
            run = (
                await session.execute(
                    select(ResearchRunDB).where(ResearchRunDB.goal_id == rec.goal_id)
                )
            ).scalar_one_or_none()
            if run is None:
                return

            st = rec.state
            run.status = rec.status
            if rec.error:
                run.error_message = rec.error
            if rec.finished_at is not None:
                run.finished_at = rec.finished_at
            if rec.report is not None:
                try:
                    run.report_json = _json(serialize_report(rec.report))
                except Exception:  # noqa: BLE001
                    logger.exception("report serialization failed for %s", rec.goal_id)
            if st is not None:
                run.phase = str(st.phase)
                run.current_asset = st.current_asset
                run.current_lineage = st.current_lineage_id
                run.used_runs = st.budget.used_runs
                run.used_eur = float(st.budget.used_eur)
                run.train_end = getattr(st, "train_end", "") or ""   # P2: select-on-train split boundary
                run.provider_type = getattr(st, "provider_type", "") or ""   # P2: leakage-marker provenance
                run.model_id = getattr(st, "model_id", "") or ""             # H31: per-model leakage badge

            # H27: advance the flush cursors in LOCALS; write them back to rec.* only AFTER the commit
            # succeeds, so a failed/rolled-back commit is retried next tick — never silently dropped
            # (the pre-commit increment permanently lost those rows on any commit error).
            p_events = rec.persisted_events
            p_hypotheses = rec.persisted_hypotheses
            p_candidates = rec.persisted_candidates
            p_failures = rec.persisted_failures
            p_lineage = rec.persisted_lineage_count

            # Append newly buffered events.
            events = rec.events
            while p_events < len(events):
                ev = events[p_events]
                payload = ev.get("payload") or {}
                session.add(
                    ResearchEventDB(
                        goal_id=rec.goal_id,
                        kind=ev.get("kind", ""),
                        phase=run.phase,
                        lineage_id=run.current_lineage,
                        detail_json=_json(payload),
                        strategy_hash=payload.get("strategy_hash"),
                    )
                )
                p_events += 1

            # Append newly found candidates + failures from the live state.
            if st is not None:
                # Proposals first (the per-attempt record; failures/candidates reference it).
                while p_hypotheses < len(st.hypotheses):
                    h = st.hypotheses[p_hypotheses]
                    session.add(
                        ResearchHypothesisDB(
                            goal_id=rec.goal_id,
                            hypothesis_id=h.hypothesis_id,
                            author=h.author,
                            economic_rationale=h.economic_rationale,
                            claimed_mechanism=h.claimed_mechanism,
                            falsifiable_prediction=h.falsifiable_prediction,
                            proposed_template_id=h.proposed_template_id,
                            proposed_param_ranges_json=_json(h.proposed_param_ranges),
                            prior_strength=h.prior_strength,
                        )
                    )
                    p_hypotheses += 1

                # OOS outcomes arrive after a candidate is created — map by hash.
                oos_map = {o.strategy_hash: o.outcome for o in st.oos_results}
                while p_candidates < len(st.candidates):
                    c = st.candidates[p_candidates]
                    session.add(
                        ResearchCandidateDB(
                            goal_id=rec.goal_id,
                            strategy_hash=c.strategy_hash,
                            run_artifact_id=c.run_id,
                            template_id=c.template_id,
                            security_id=c.security_id,
                            sharpe_annual=c.sharpe_annual,
                            total_return=c.total_return,
                            max_drawdown=c.max_drawdown,
                            n_trades=c.n_trades,
                            critic_confidence=c.critic_confidence,
                            critique_json=_json(c.critique),
                            gate_report_json=_json(c.gate_report_summary),
                            artifacts_json=_json({
                                "regime_analysis": c.regime_analysis,
                                "benchmark": c.benchmark,
                                "equity_curve": c.equity_curve,
                            }),
                            oos_outcome=oos_map.get(c.strategy_hash, "PENDING"),
                            lineage_id=getattr(c, "lineage_id", "") or run.current_lineage,  # M47: creation-time lineage
                            hypothesis_id=c.hypothesis_id,
                            params_json=_json(c.params),
                            validation_status=getattr(c, "validation_status", ""),
                            confidence=getattr(c, "confidence", ""),
                            decay_json=_json(getattr(c, "decay", {})),
                            weaknesses_json=_json(getattr(c, "weaknesses", [])),
                            holdout_json=_json(getattr(c, "holdout", {})),   # P2
                        )
                    )
                    p_candidates += 1

                # Back-fill oos_outcome for candidates whose OOS result arrived
                # after they were first persisted (cheap — candidates are few).
                for sh, outcome in oos_map.items():
                    await session.execute(
                        update(ResearchCandidateDB)
                        .where(
                            ResearchCandidateDB.goal_id == rec.goal_id,
                            ResearchCandidateDB.strategy_hash == sh,
                            ResearchCandidateDB.oos_outcome != outcome,
                        )
                        .values(oos_outcome=outcome)
                    )

                while p_failures < len(st.all_failures):
                    f = st.all_failures[p_failures]
                    session.add(
                        ResearchFailureDB(
                            goal_id=rec.goal_id,
                            strategy_hash=f.strategy_hash,
                            template_id=f.template_id,
                            security_id=f.security_id,
                            failed_gate=f.failed_gate or "",
                            gate_details_json=_json(f.gate_details),
                            critic_notes=f.critic_notes or "",
                            failure_reason=f.failure_reason,
                            hypothesis_id=f.hypothesis_id,
                            params_json=_json(f.params),
                        )
                    )
                    p_failures += 1

                # G4: lineage tree — a snapshot (replace on growth, not append-only).
                if st.lineage_nodes and len(st.lineage_nodes) != p_lineage:
                    await session.execute(
                        delete(ResearchLineageDB).where(ResearchLineageDB.goal_id == rec.goal_id)
                    )
                    for n in st.lineage_nodes:
                        session.add(
                            ResearchLineageDB(
                                goal_id=rec.goal_id,
                                lineage_id=n.get("lineage_id", ""),
                                parent_lineage_id=n.get("parent_lineage_id"),
                                root_strategy_hash=n.get("root_strategy_hash"),
                                declared_by=n.get("declared_by", ""),
                                node_created_at=str(n.get("created_at") or ""),
                            )
                        )
                    p_lineage = len(st.lineage_nodes)

            await session.commit()
            # H27: commit succeeded — NOW advance the durable cursors. If the commit above raised,
            # we never reach here, so the same rows are retried on the next flush.
            rec.persisted_events = p_events
            rec.persisted_hypotheses = p_hypotheses
            rec.persisted_candidates = p_candidates
            rec.persisted_failures = p_failures
            rec.persisted_lineage_count = p_lineage
    except Exception:  # noqa: BLE001 — persistence must never crash the run
        logger.exception("persist_snapshot failed for run %s", getattr(rec, "goal_id", "?"))


async def mark_orphaned_runs_interrupted() -> int:
    """On startup: any run still 'running' lost its task on restart → interrupted."""
    async with _write_lock, async_session() as session:
        result = await session.execute(
            update(ResearchRunDB)
            .where(ResearchRunDB.status == "running")
            .values(status="interrupted")
        )
        await session.commit()
        n = result.rowcount or 0
        if n:
            logger.info("Marked %d orphaned research run(s) as interrupted", n)
        return n


async def load_run_for_state(goal_id: str, user_id: int) -> dict[str, Any] | None:
    """Read a run's persisted state (for the GET fallback after restart).

    Returns a plain dict (no detached ORM instances) or None if missing/not owned.
    """
    async with async_session() as session:
        run = (
            await session.execute(
                select(ResearchRunDB).where(ResearchRunDB.goal_id == goal_id)
            )
        ).scalar_one_or_none()
        if run is None or run.user_id != user_id:
            return None
        n_cand = (
            await session.execute(
                select(func.count()).select_from(ResearchCandidateDB).where(
                    ResearchCandidateDB.goal_id == goal_id
                )
            )
        ).scalar() or 0
        n_fail = (
            await session.execute(
                select(func.count()).select_from(ResearchFailureDB).where(
                    ResearchFailureDB.goal_id == goal_id
                )
            )
        ).scalar() or 0
        return {
            "phase": run.phase,
            "goal_text": run.goal_text,
            "current_asset": run.current_asset,
            "used_runs": run.used_runs,
            "max_runs": run.max_runs,
            "used_eur": run.used_eur,
            "max_seconds": run.max_seconds,
            "current_lineage": run.current_lineage,
            "status": run.status,
            "started_at": _utc_iso(run.started_at),   # M53: UTC-marked so the frontend doesn't read it as local
            "error_message": run.error_message,
            "candidates_count": int(n_cand),
            "failure_count": int(n_fail),
            "agent_mode": run.agent_mode,                    # D1: surface on the persisted path too
            "mode": run.mode,                                # P1 Chunk C
            "window_start": run.window_start,
            "window_end": run.window_end,
            "provider_type": run.provider_type,              # P2: leakage marker
            "model_id": run.model_id,                        # H31: per-model leakage badge
        }


async def load_candidates(goal_id: str, user_id: int) -> list[dict[str, Any]] | None:
    """Read a run's persisted candidates (GET fallback). None if not owned/missing."""
    async with async_session() as session:
        owns = (
            await session.execute(
                select(ResearchRunDB.user_id).where(ResearchRunDB.goal_id == goal_id)
            )
        ).scalar_one_or_none()
        if owns is None or owns != user_id:
            return None
        rows = (
            await session.execute(
                select(ResearchCandidateDB).where(ResearchCandidateDB.goal_id == goal_id)
            )
        ).scalars().all()
        return [
            {
                "strategy_hash": r.strategy_hash,
                "run_id": r.run_artifact_id,
                "template_id": r.template_id,
                "security_id": r.security_id,
                "sharpe_annual": r.sharpe_annual,
                "total_return": r.total_return,
                "max_drawdown": r.max_drawdown,
                "n_trades": r.n_trades,
                "critic_confidence": r.critic_confidence,
                "oos_outcome": r.oos_outcome,
                "validation_status": r.validation_status,   # P1 Chunk C firewall
                "confidence": r.confidence,
                "decay": json.loads(r.decay_json or "{}"),   # C2
                "weaknesses": json.loads(r.weaknesses_json or "[]"),   # idea-surfacing
                "holdout": json.loads(r.holdout_json or "{}"),   # P2 hold-out
                "gate_report": json.loads(r.gate_report_json or "{}"),  # confidence-surfacing (popped in router)
            }
            for r in rows
        ]


async def load_candidate_detail(
    goal_id: str, strategy_hash: str, user_id: int
) -> dict[str, Any] | None:
    """Read one candidate's full detail (gates/critique/oos) for the dossier.

    Ownership-checked via the owning run. Returns None if run not owned, the
    sentinel ``{"_missing": True}`` if the run is owned but the candidate is
    absent (so the caller can 404 the candidate, not the run).
    """
    async with async_session() as session:
        owns = (
            await session.execute(
                select(ResearchRunDB.user_id).where(ResearchRunDB.goal_id == goal_id)
            )
        ).scalar_one_or_none()
        if owns is None or owns != user_id:
            return None
        row = (
            await session.execute(
                select(ResearchCandidateDB).where(
                    ResearchCandidateDB.goal_id == goal_id,
                    ResearchCandidateDB.strategy_hash == strategy_hash,
                )
            )
        ).scalars().first()
        if row is None:
            return {"_missing": True}

        def _loads(s: str) -> Any:
            try:
                return json.loads(s)
            except Exception:  # noqa: BLE001
                return {}

        return {
            "strategy_hash": row.strategy_hash,
            "template_id": row.template_id,
            "security_id": row.security_id,
            "sharpe_annual": row.sharpe_annual,
            "total_return": row.total_return,
            "max_drawdown": row.max_drawdown,
            "n_trades": row.n_trades,
            "critic_confidence": row.critic_confidence,
            "critique": _loads(row.critique_json),
            "gate_report": _loads(row.gate_report_json),
            "artifacts": _loads(row.artifacts_json or "{}"),
            "oos_outcome": row.oos_outcome,
            "lineage_id": row.lineage_id,
        }


async def load_runs_list(user_id: int, limit: int = 100) -> list[dict[str, Any]]:
    """List a user's runs (newest first) for the runs history (C-6)."""
    async with async_session() as session:
        runs = (
            await session.execute(
                select(ResearchRunDB)
                .where(ResearchRunDB.user_id == user_id)
                .order_by(ResearchRunDB.id.desc())
                .limit(limit)
            )
        ).scalars().all()
        if not runs:
            return []
        goal_ids = [r.goal_id for r in runs]
        # Per-run candidate + failure counts in two grouped queries.
        cand_counts = dict(
            (
                await session.execute(
                    select(ResearchCandidateDB.goal_id, func.count())
                    .where(ResearchCandidateDB.goal_id.in_(goal_ids))
                    .group_by(ResearchCandidateDB.goal_id)
                )
            ).all()
        )
        fail_counts = dict(
            (
                await session.execute(
                    select(ResearchFailureDB.goal_id, func.count())
                    .where(ResearchFailureDB.goal_id.in_(goal_ids))
                    .group_by(ResearchFailureDB.goal_id)
                )
            ).all()
        )
        return [
            {
                "goal_id": r.goal_id,
                "goal_text": r.goal_text,
                "status": r.status,
                "phase": r.phase,
                "used_runs": r.used_runs,
                "max_runs": r.max_runs,
                "candidates_count": int(cand_counts.get(r.goal_id, 0)),
                "failure_count": int(fail_counts.get(r.goal_id, 0)),
                "created_at": _utc_iso(r.created_at),
                "started_at": _utc_iso(r.started_at),
                "finished_at": _utc_iso(r.finished_at),
                "provider_type": r.provider_type,   # P2: leakage marker
                "model_id": r.model_id,             # H31: per-model leakage badge
            }
            for r in runs
        ]


async def aggregate_stats(user_id: int) -> dict[str, Any]:
    """Director-dashboard aggregates across a user's runs — honest, from the
    populated research_* tables (the TrialEventRegistry is NOT wired to research
    runs, so we do not pretend it is).
    """
    async with async_session() as session:
        runs = (
            await session.execute(
                select(ResearchRunDB).where(ResearchRunDB.user_id == user_id)
            )
        ).scalars().all()
        goal_ids = [r.goal_id for r in runs]
        runs_by_status: dict[str, int] = {}
        trials_attempted = 0
        for r in runs:
            runs_by_status[r.status] = runs_by_status.get(r.status, 0) + 1
            trials_attempted += r.used_runs or 0

        total_candidates = total_failures = 0
        oos_passed = oos_failed = 0
        coverage: list[dict[str, Any]] = []
        if goal_ids:
            total_candidates = (
                await session.execute(
                    select(func.count()).select_from(ResearchCandidateDB).where(
                        ResearchCandidateDB.goal_id.in_(goal_ids),
                        ResearchCandidateDB.validation_status == "",   # RD-2: exclude regime ideas (robustness only)
                    )
                )
            ).scalar() or 0
            total_failures = (
                await session.execute(
                    select(func.count()).select_from(ResearchFailureDB).where(
                        ResearchFailureDB.goal_id.in_(goal_ids)
                    )
                )
            ).scalar() or 0
            oos_passed = (
                await session.execute(
                    select(func.count()).select_from(ResearchCandidateDB).where(
                        ResearchCandidateDB.goal_id.in_(goal_ids),
                        ResearchCandidateDB.oos_outcome == "PASS",
                    )
                )
            ).scalar() or 0
            oos_failed = (
                await session.execute(
                    select(func.count()).select_from(ResearchCandidateDB).where(
                        ResearchCandidateDB.goal_id.in_(goal_ids),
                        ResearchCandidateDB.oos_outcome == "FAIL",
                    )
                )
            ).scalar() or 0

            # ATSX-26 coverage map: asset×strategy explored, survived vs died.
            cand_cov = (
                await session.execute(
                    select(
                        ResearchCandidateDB.security_id,
                        ResearchCandidateDB.template_id,
                        func.count(),
                    )
                    .where(ResearchCandidateDB.goal_id.in_(goal_ids),
                           ResearchCandidateDB.validation_status == "")   # RD-2: robustness candidates only
                    .group_by(ResearchCandidateDB.security_id, ResearchCandidateDB.template_id)
                )
            ).all()
            fail_cov = (
                await session.execute(
                    select(
                        ResearchFailureDB.security_id,
                        ResearchFailureDB.template_id,
                        func.count(),
                    )
                    .where(ResearchFailureDB.goal_id.in_(goal_ids))
                    .group_by(ResearchFailureDB.security_id, ResearchFailureDB.template_id)
                )
            ).all()
            cells: dict[tuple[str, str], dict[str, int]] = {}
            for sec, tpl, n in cand_cov:
                cells.setdefault((sec or "?", tpl or "?"), {"survived": 0, "died": 0})["survived"] += int(n)
            for sec, tpl, n in fail_cov:
                cells.setdefault((sec or "?", tpl or "?"), {"survived": 0, "died": 0})["died"] += int(n)
            coverage = sorted(
                (
                    {
                        "security_id": sec,
                        "template_id": tpl,
                        "survived": v["survived"],
                        "died": v["died"],
                        "total": v["survived"] + v["died"],
                    }
                    for (sec, tpl), v in cells.items()
                ),
                key=lambda c: c["total"],
                reverse=True,
            )

        # "valid research trial" = entered the gate pipeline (produced a gate-
        # evaluable outcome: survived as a candidate or died at a gate/critic).
        valid_trials = int(total_candidates) + int(total_failures)
        return {
            "total_runs": len(runs),
            "runs_by_status": runs_by_status,
            "audit_trial_count": trials_attempted,
            "valid_research_trial_count": valid_trials,
            "candidates_found": int(total_candidates),
            "failures_recorded": int(total_failures),
            "oos_passed": int(oos_passed),
            "oos_failed": int(oos_failed),
            "coverage": coverage,
        }


async def load_failures(goal_id: str, user_id: int) -> list[dict[str, Any]] | None:
    """Read a run's graveyard (A-7). None if run not owned/missing."""
    async with async_session() as session:
        owns = (
            await session.execute(
                select(ResearchRunDB.user_id).where(ResearchRunDB.goal_id == goal_id)
            )
        ).scalar_one_or_none()
        if owns is None or owns != user_id:
            return None
        rows = (
            await session.execute(
                select(ResearchFailureDB)
                .where(ResearchFailureDB.goal_id == goal_id)
                .order_by(ResearchFailureDB.id)
            )
        ).scalars().all()

        def _loads(s: str) -> Any:
            try:
                return json.loads(s)
            except Exception:  # noqa: BLE001
                return {}

        return [
            {
                "strategy_hash": r.strategy_hash,
                "template_id": r.template_id,
                "security_id": r.security_id,
                "failed_gate": r.failed_gate,
                "gate_details": _loads(r.gate_details_json),
                "critic_notes": r.critic_notes,
                "failure_reason": r.failure_reason,
                "hypothesis_id": r.hypothesis_id,
                "params": _loads(r.params_json),
            }
            for r in rows
        ]


async def load_hypotheses(goal_id: str, user_id: int) -> list[dict[str, Any]] | None:
    """Read a run's proposals — the AI's reasoning per attempt. None if not owned/missing."""
    async with async_session() as session:
        owns = (
            await session.execute(
                select(ResearchRunDB.user_id).where(ResearchRunDB.goal_id == goal_id)
            )
        ).scalar_one_or_none()
        if owns is None or owns != user_id:
            return None
        rows = (
            await session.execute(
                select(ResearchHypothesisDB)
                .where(ResearchHypothesisDB.goal_id == goal_id)
                .order_by(ResearchHypothesisDB.id)
            )
        ).scalars().all()

        def _loads(s: str) -> Any:
            try:
                return json.loads(s)
            except Exception:  # noqa: BLE001
                return {}

        return [
            {
                "hypothesis_id": r.hypothesis_id,
                "author": r.author,
                "economic_rationale": r.economic_rationale,
                "claimed_mechanism": r.claimed_mechanism,
                "falsifiable_prediction": r.falsifiable_prediction,
                "proposed_template_id": r.proposed_template_id,
                "proposed_param_ranges": _loads(r.proposed_param_ranges_json),
                "prior_strength": r.prior_strength,
            }
            for r in rows
        ]


async def load_lineage(goal_id: str, user_id: int) -> list[dict[str, Any]] | None:
    """Read a run's lineage tree (G4). None if not owned/missing."""
    async with async_session() as session:
        owns = (
            await session.execute(
                select(ResearchRunDB.user_id).where(ResearchRunDB.goal_id == goal_id)
            )
        ).scalar_one_or_none()
        if owns is None or owns != user_id:
            return None
        rows = (
            await session.execute(
                select(ResearchLineageDB)
                .where(ResearchLineageDB.goal_id == goal_id)
                .order_by(ResearchLineageDB.id)
            )
        ).scalars().all()
        return [
            {
                "lineage_id": r.lineage_id,
                "parent_lineage_id": r.parent_lineage_id,
                "root_strategy_hash": r.root_strategy_hash,
                "declared_by": r.declared_by,
                "created_at": r.node_created_at or None,
            }
            for r in rows
        ]


async def load_report(goal_id: str, user_id: int) -> dict[str, Any] | None:
    """Read a run's persisted FinalReport (A-8). None if not owned/missing."""
    async with async_session() as session:
        run = (
            await session.execute(
                select(ResearchRunDB).where(ResearchRunDB.goal_id == goal_id)
            )
        ).scalar_one_or_none()
        if run is None or run.user_id != user_id:
            return None
        try:
            report = json.loads(run.report_json or "{}")
        except Exception:  # noqa: BLE001
            report = {}
        return {
            "status": run.status,
            "goal_text": run.goal_text,
            "report": report,
        }


async def load_events(
    goal_id: str, user_id: int, since: int = 0, limit: int = 200
) -> list[dict[str, Any]] | None:
    """Read a run's activity-stream events with id > ``since`` (GET /events).

    Returns None if the run is missing or not owned by the user.
    """
    async with async_session() as session:
        owns = (
            await session.execute(
                select(ResearchRunDB.user_id).where(ResearchRunDB.goal_id == goal_id)
            )
        ).scalar_one_or_none()
        if owns is None or owns != user_id:
            return None
        rows = (
            await session.execute(
                select(ResearchEventDB)
                .where(ResearchEventDB.goal_id == goal_id, ResearchEventDB.id > since)
                .order_by(ResearchEventDB.id)
                .limit(limit)
            )
        ).scalars().all()
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                detail = json.loads(r.detail_json)
            except Exception:  # noqa: BLE001
                detail = {}
            out.append(
                {
                    "id": r.id,
                    "ts": _utc_iso(r.ts),
                    "kind": r.kind,
                    "phase": r.phase,
                    "lineage_id": r.lineage_id,
                    "detail": detail,
                    "strategy_hash": r.strategy_hash,
                }
            )
        return out
