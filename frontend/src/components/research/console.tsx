// ATSX-16 (C-2): Agent Console components — implements AGENT-CONSOLE-WIREFRAME.md.
// Pure Tailwind dark theme; mono for IDs/numbers. Trust-first (Sharpe demoted).
"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { RunControls } from "@/lib/research/hooks";
import {
  Candidate,
  Hypothesis,
  phaseToPill,
  QualitySummary,
  ResearchEvent,
  ResearchState,
} from "@/lib/research/types";

// ── small helpers ─────────────────────────────────────────────────────

function pct(used: number, max: number): number {
  if (max <= 0) return 0;
  return Math.min(100, Math.round((used / max) * 100));
}

function fmtDuration(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) seconds = 0;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

const PILL_STYLES: Record<string, string> = {
  running: "bg-blue-900 text-blue-300 animate-pulse",
  paused: "bg-orange-900 text-orange-300",
  completed: "bg-green-900 text-green-300",
  stopped: "bg-red-900 text-red-300",
  failed: "bg-red-900 text-red-300",
  connecting: "bg-gray-800 text-gray-400",
};

// ── TopBar ────────────────────────────────────────────────────────────

export function TopBar({
  state,
  goalId,
  controls,
}: {
  state: ResearchState | null;
  goalId: string;
  controls?: RunControls;
}) {
  const pill = state ? phaseToPill(state.status, state.phase) : "connecting";
  const title = state?.goal_text || "Research run";
  const status = state?.status;
  const btn = "px-2 py-1 rounded text-xs font-semibold disabled:opacity-40";
  return (
    <div className="flex items-center justify-between border-b border-gray-800 bg-gray-950 px-4 py-3">
      <div className="flex items-center gap-3 min-w-0">
        <Link href="/dashboard/research" className="text-sm text-gray-400 hover:text-gray-200 shrink-0">
          ← Runs
        </Link>
        <span className="truncate text-sm font-medium text-gray-100" title={title}>
          {title}
        </span>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {/* A-9 Director controls — gated by run status */}
        {controls && status === "running" && (
          <>
            <button onClick={controls.pause} disabled={controls.busy} className={`${btn} bg-gray-800 hover:bg-gray-700 text-gray-200`}>
              Pause
            </button>
            <button onClick={controls.stop} disabled={controls.busy} className={`${btn} bg-red-900/70 hover:bg-red-800 text-red-200`}>
              Stop
            </button>
          </>
        )}
        {controls && status === "paused" && (
          <>
            <button onClick={controls.resume} disabled={controls.busy} className={`${btn} bg-blue-700 hover:bg-blue-600 text-white`}>
              Resume
            </button>
            <button onClick={controls.stop} disabled={controls.busy} className={`${btn} bg-red-900/70 hover:bg-red-800 text-red-200`}>
              Stop
            </button>
          </>
        )}
        <span className={`text-[10px] uppercase font-semibold px-2 py-1 rounded ${PILL_STYLES[pill]}`}>
          ● {pill}
        </span>
        {state && ["completed", "stopped", "failed", "interrupted"].includes(state.status) && (
          <Link
            href={`/dashboard/research/runs/${goalId}/report`}
            className="px-2 py-1 rounded text-xs bg-gray-800 hover:bg-gray-700 text-gray-200"
          >
            View Report
          </Link>
        )}
      </div>
    </div>
  );
}

// ── BudgetHUD ─────────────────────────────────────────────────────────

function Meter({ label, value, max, suffix, danger }: {
  label: string; value: number; max: number; suffix?: string; danger?: boolean;
}) {
  const p = pct(value, max);
  const barColor = danger || p >= 80 ? "bg-yellow-500" : "bg-blue-500";
  return (
    <div className="flex flex-col gap-1 min-w-[120px]">
      <div className="flex justify-between text-[11px]">
        <span className="text-gray-500 uppercase">{label}</span>
        <span className="font-mono text-gray-300">
          {value}
          {suffix ? "" : `/${max}`}
          {suffix || ""}
        </span>
      </div>
      <div className="h-1.5 bg-gray-800 rounded overflow-hidden">
        <div className={`h-full ${barColor} transition-all`} style={{ width: `${p}%` }} />
      </div>
    </div>
  );
}

export function BudgetHUD({ state }: { state: ResearchState | null }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!state?.started_at) return;
    const start = new Date(state.started_at).getTime();
    const tick = () => setElapsed((Date.now() - start) / 1000);
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [state?.started_at]);

  if (!state) {
    return <div className="h-12 border-b border-gray-800 bg-gray-950 animate-pulse" />;
  }
  const maxRuns = state.budget_used_runs + state.budget_remaining_runs;
  const failsDanger = state.failure_count >= 3;
  return (
    <div className="flex flex-wrap items-center gap-6 border-b border-gray-800 bg-gray-950 px-4 py-2">
      <Meter label="Runs" value={state.budget_used_runs} max={maxRuns} />
      <Meter label="Cost €" value={Number(state.used_eur.toFixed(4))} max={0} suffix=" €" />
      {state.agent_mode && state.agent_mode !== "rule_based" && (
        <span
          className="text-[10px] uppercase font-semibold px-2 py-0.5 rounded bg-blue-950 text-blue-300"
          title="effective AI mode"
        >
          {state.agent_mode.replace("_", "-")}
        </span>
      )}
      {state.mode === "regime" && (
        <span
          className="text-[10px] uppercase font-semibold px-2 py-0.5 rounded bg-amber-950 text-amber-300 border border-amber-800"
          // M31: when a select-on-train split exists, candidate metrics are measured on the TRAIN slice
          // [window_start, train_end]; label that (not the full window) and note the hold-out. No split → full window.
          title={
            state.train_end
              ? `regime-fit — metrics on train slice ${state.window_start} → ${state.train_end}; hold-out → ${state.window_end} — NOT robustness-validated`
              : `regime-fit window ${state.window_start} → ${state.window_end} — NOT robustness-validated`
          }
        >
          {state.train_end
            ? <>regime · train {state.window_start}→{state.train_end} · hold-out →{state.window_end} · UNVALIDATED</>
            : <>regime · {state.window_start}→{state.window_end} · UNVALIDATED</>}
        </span>
      )}
      {state.leakage === "risk" && (
        <span
          className="text-[10px] uppercase font-semibold px-2 py-0.5 rounded bg-amber-950 text-amber-300 border border-amber-800"
          title={`This run used a leakage-risk provider (${state.provider_type}) — data-leakage risk for backtest selection. Its candidates may be over-optimistic.`}
        >
          ⚠ {state.provider_type} · leakage risk
        </span>
      )}
      <div className="flex flex-col gap-1 min-w-[120px]">
        <div className="flex justify-between text-[11px]">
          <span className="text-gray-500 uppercase">Time</span>
          <span className="font-mono text-gray-300">
            {fmtDuration(elapsed)}/{fmtDuration(state.max_seconds)}
          </span>
        </div>
        <div className="h-1.5 bg-gray-800 rounded overflow-hidden">
          <div className="h-full bg-blue-500 transition-all" style={{ width: `${pct(elapsed, state.max_seconds)}%` }} />
        </div>
      </div>
      <div className="text-[11px]">
        <span className="text-gray-500 uppercase">Iter </span>
        <span className="font-mono text-gray-300">{state.total_iterations}</span>
      </div>
      <div className="text-[11px]">
        <span className="text-gray-500 uppercase">Fails </span>
        <span className={`font-mono ${failsDanger ? "text-red-400" : "text-gray-300"}`}>
          ⚠ {state.failure_count}
          {failsDanger ? " · circuit-breaker armed" : ""}
        </span>
      </div>
    </div>
  );
}

// ── PipelineRail ──────────────────────────────────────────────────────

const PHASE_ROWS: { label: string; phase: string; seat: string }[] = [
  { label: "Strategist", phase: "proposing", seat: "Quant Researcher" },
  { label: "Data", phase: "data_preparing", seat: "Data Engineer" },
  { label: "Executor", phase: "executing", seat: "Quant Developer" },
  { label: "Gatekeeper", phase: "gating", seat: "Risk / QC" },
  { label: "Critic", phase: "critiquing", seat: "Adversarial Reviewer" },
  { label: "OOS Lockbox", phase: "oos_evaluating", seat: "Lockbox" },
  { label: "Orchestrator", phase: "deciding", seat: "Research Director" },
  { label: "Reporter", phase: "reporting", seat: "Narrator" },
];

export function PipelineRail({
  state,
  hypothesis,
}: {
  state: ResearchState | null;
  hypothesis: Hypothesis | null;
}) {
  const activeIdx = state ? PHASE_ROWS.findIndex((r) => r.phase === state.phase) : -1;
  return (
    <div className="flex flex-col gap-1 border-r border-gray-800 bg-gray-950 p-4 overflow-y-auto">
      <div className="text-xs uppercase font-semibold text-gray-500 mb-2">Pipeline</div>
      {PHASE_ROWS.map((row, i) => {
        const isActive = i === activeIdx;
        const isDone = activeIdx >= 0 && i < activeIdx;
        const glyph = isActive ? "▶" : isDone ? "✓" : "·";
        const color = isActive
          ? "text-blue-300"
          : isDone
            ? "text-gray-400"
            : "text-gray-600";
        return (
          <div
            key={row.phase}
            className={`flex items-center gap-2 rounded px-2 py-1.5 ${
              isActive ? "border border-blue-700 bg-blue-950/30 animate-pulse" : ""
            }`}
            title={row.seat}
          >
            <span className={`font-mono w-4 ${color}`}>{glyph}</span>
            <span className={`text-sm ${color}`}>{row.label}</span>
          </div>
        );
      })}

      <div className="border-t border-gray-800 mt-3 pt-3 space-y-1 text-[11px]">
        <div className="flex justify-between">
          <span className="text-gray-500">Lineage</span>
          <span className="font-mono text-gray-400">{state?.current_lineage?.slice(0, 8) || "—"}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Asset</span>
          <span className="font-mono text-gray-300">{state?.current_asset || "—"}</span>
        </div>
      </div>

      {hypothesis && (
        <div className="mt-3 rounded border border-purple-900/40 bg-purple-950/10 p-2 text-[11px] space-y-1">
          <div className="text-purple-300 uppercase font-semibold text-[10px]">Hypothesis</div>
          <div className="text-gray-300 line-clamp-3">{hypothesis.economic_rationale}</div>
          <div className="text-gray-500">prior: {hypothesis.prior_strength}</div>
        </div>
      )}
    </div>
  );
}

// ── ActivityStream ────────────────────────────────────────────────────

const KIND_GLYPH: Record<string, { g: string; c: string }> = {
  propose: { g: "✎", c: "text-purple-400" },
  data: { g: "▦", c: "text-slate-400" },
  execute: { g: "▶", c: "text-blue-400" },
  gate_pass: { g: "✓", c: "text-green-400" },
  gate_fail: { g: "✗", c: "text-red-400" },
  critique: { g: "⚔", c: "text-amber-400" },
  oos: { g: "🔒", c: "text-green-400" },
  decide: { g: "◆", c: "text-gray-400" },
  report: { g: "📄", c: "text-green-400" },
  goal: { g: "◎", c: "text-gray-400" },
};

// A gate failure or a rejecting critique loops back to the Strategist — the tight
// falsification loop. Detect it from the event alone (no backend change needed).
export function isFailureLoopback(ev: ResearchEvent): boolean {
  if (ev.kind === "gate_fail") return true;
  if (ev.kind === "critique") {
    return String(ev.detail?.recommendation ?? "").toLowerCase().includes("reject");
  }
  return false;
}

export function ActivityItem({
  ev,
  goalId,
  failureIdx,
}: {
  ev: ResearchEvent;
  goalId: string;
  failureIdx?: number;
}) {
  const meta = KIND_GLYPH[ev.kind] || { g: "•", c: "text-gray-500" };
  const ts = ev.ts ? new Date(ev.ts).toLocaleTimeString() : "";
  const clickable = ev.strategy_hash && ["execute", "gate_pass", "gate_fail", "critique"].includes(ev.kind);
  const body = (
    <div className="flex gap-2 py-2 border-b border-gray-800/60">
      <span className={`font-mono ${meta.c} shrink-0 w-4`}>{meta.g}</span>
      <div className="min-w-0 flex-1">
        <div className="flex justify-between gap-2">
          <span className="text-sm text-gray-200 truncate">{ev.title || ev.kind}</span>
          <span className="font-mono text-[10px] text-gray-600 shrink-0">{ts}</span>
        </div>
        {ev.lineage_id && (
          <div className="text-[10px] text-gray-600 font-mono">lineage {ev.lineage_id.slice(0, 8)}</div>
        )}
      </div>
    </div>
  );
  return (
    <div>
      {clickable ? (
        <Link
          href={`/dashboard/research/runs/${goalId}/candidates/${ev.strategy_hash}`}
          className="block hover:bg-gray-900/50 -mx-2 px-2 rounded"
        >
          {body}
        </Link>
      ) : (
        body
      )}
      {failureIdx != null && (
        // Makes the loop legible (Wireframe AC#2): the failure routes back to the Strategist.
        <div className="flex items-center gap-1.5 pl-6 pb-2 -mt-0.5 text-[11px] text-red-400/70">
          <span className="font-mono">↳</span>
          <span>back to Strategist · failure ctx #{failureIdx}</span>
        </div>
      )}
    </div>
  );
}

export function ActivityStream({ events, goalId }: { events: ResearchEvent[]; goalId: string }) {
  // Cumulative failure ordinal (chronological) so each loop-back reads "failure ctx #N",
  // reconciling with state.failure_count. events arrive oldest-first.
  const failureOrdinals = new Map<number, number>();
  let nFail = 0;
  for (const ev of events) {
    if (isFailureLoopback(ev)) {
      nFail += 1;
      failureOrdinals.set(ev.id, nFail);
    }
  }
  return (
    <div className="flex flex-col bg-gray-950 overflow-y-auto p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs uppercase font-semibold text-gray-500">Activity</span>
        <span className="text-[10px] text-gray-600">{events.length} events</span>
      </div>
      {events.length === 0 ? (
        <div className="text-sm text-gray-600 py-8 text-center">Waiting for the agent to act…</div>
      ) : (
        // reverse-chron: newest on top
        [...events]
          .reverse()
          .map((ev) => (
            <ActivityItem key={ev.id} ev={ev} goalId={goalId} failureIdx={failureOrdinals.get(ev.id)} />
          ))
      )}
    </div>
  );
}

// ── EvidencePanel ─────────────────────────────────────────────────────

const OOS_BADGE: Record<string, string> = {
  PASS: "bg-green-900 text-green-300",
  FAIL: "bg-red-900 text-red-300",
  PENDING: "bg-gray-800 text-gray-400",
};

// Confidence-surfacing (CONFIDENCE-SURFACING-SPEC v2) — the unified statistical-quality chip.
// C-5: regime tiers are styled amber/teal/red — NEVER the robustness green/blue — so an
// UNVALIDATED regime idea can never read as trustworthy as a robustness survivor.
function qualityStyle(q: QualitySummary): string {
  if (q.mode === "regime") {
    if (q.tier === "validated") return "bg-teal-900 text-teal-300 border border-teal-700";
    if (q.tier === "failed") return "bg-red-900 text-red-300";
    return "bg-amber-950 text-amber-300 border border-amber-800"; // every UNVALIDATED regime tier
  }
  const R: Record<string, string> = {
    strong: "bg-green-900 text-green-300 border border-green-700",
    moderate: "bg-blue-900 text-blue-300",
    weak: "bg-gray-800 text-gray-400",
    provisional: "bg-gray-800 text-gray-500 italic",
  };
  return R[q.tier] || "bg-gray-800 text-gray-400";
}

function qualityLabel(q: QualitySummary): string {
  if (q.mode === "regime") {
    // The firewall word is on the chip itself (not just the tooltip) — C-5.
    if (q.tier === "validated") return "VALIDATED · regime";
    if (q.tier === "failed") return "FAILED hold-out";
    return `UNVALIDATED · ${q.tier}`;
  }
  return `quality: ${q.tier}`;
}

// F-6/F-7/F-10: prominent on the card, both modes; tooltip carries the plain-language "why".
export function QualityBadge({ q }: { q?: QualitySummary }) {
  if (!q || !q.tier) return null;
  return (
    <span
      className={`text-[10px] uppercase font-semibold px-1.5 py-0.5 rounded ${qualityStyle(q)}`}
      title={q.headline}
    >
      {qualityLabel(q)}
    </span>
  );
}

// P2-4: out-of-regime decay measured just BEFORE and just AFTER the regime window (fade-in/out).
function DecayChip({ decay }: { decay?: Record<string, unknown> }) {
  if (!decay) return null;
  const before = (decay.before as { retained_fraction?: number } | null | undefined)?.retained_fraction;
  const after = (decay.after as { retained_fraction?: number } | null | undefined)?.retained_fraction;
  if (typeof before !== "number" && typeof after !== "number") return null;
  const fmt = (x?: number) => (typeof x === "number" ? `${Math.round(x * 100)}%` : "—");
  return (
    <span
      className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-gray-800 text-gray-400"
      title="fraction of the in-regime edge retained just before / just after the regime window (out-of-regime decay)"
    >
      decay b:{fmt(before)} a:{fmt(after)}
    </span>
  );
}

export function CandidateCard({ c, goalId, rank }: { c: Candidate; goalId: string; rank: number }) {
  return (
    <Link
      href={`/dashboard/research/runs/${goalId}/candidates/${c.strategy_hash}`}
      className="block rounded border border-gray-800 bg-gray-900 p-2.5 hover:border-gray-700 space-y-1.5"
    >
      <div className="flex justify-between items-center">
        <span className="text-sm text-gray-200">
          <span className="text-gray-500 font-mono">{rank}</span> {c.security_id} · {c.template_id}
        </span>
      </div>
      <div className="flex gap-1.5 items-center flex-wrap">
        {c.validation_status ? (
          <>
            {/* regime-fit: the unified quality chip leads (UNVALIDATED · tier / VALIDATED / FAILED — C-5).
                No OOS in regime; the P2 hold-out is the within-regime validation. */}
            {c.quality?.tier ? (
              <QualityBadge q={c.quality} />
            ) : (
              <span
                className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-amber-950 text-amber-300 border border-amber-800"
                title="regime-fit: NOT robustness-validated"
              >
                UNVALIDATED · {c.confidence || c.critic_confidence}
              </span>
            )}
            <DecayChip decay={c.decay} />
            {/* valconf/B3: within-regime hold-out confidence — the graded tier + an honest 90% Sharpe CI.
                A band that straddles 0 means the edge isn't distinguishable from noise on this hold-out. */}
            {c.holdout && (c.holdout as Record<string, unknown>).confidence_tier
              ? (() => {
                  const h = c.holdout as Record<string, unknown>;
                  const num = (v: unknown) => (typeof v === "number" ? v : Number(v));
                  const ci =
                    h.ci_low != null && h.ci_high != null
                      ? ` [${num(h.ci_low).toFixed(2)}, ${num(h.ci_high).toFixed(2)}]`
                      : "";
                  const sh = h.holdout_sharpe != null ? ` · Sh ${num(h.holdout_sharpe).toFixed(2)}` : "";
                  // valconf in-market masking: the edge WHILE DEPLOYED (cash days excluded), same scale as Sh.
                  const imCi =
                    h.in_market_ci_low != null && h.in_market_ci_high != null
                      ? ` [${num(h.in_market_ci_low).toFixed(2)}, ${num(h.in_market_ci_high).toFixed(2)}]`
                      : "";
                  const im =
                    h.in_market_sharpe != null ? ` · deployed ${num(h.in_market_sharpe).toFixed(2)}${imCi}` : "";
                  return (
                    <span
                      className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-gray-800 text-gray-300 border border-gray-700"
                      title={`within-regime hold-out — basis ${String(h.basis ?? "?")}, ${String(
                        h.holdout_trades ?? "?",
                      )} trades; 90% Sharpe CI${ci || " n/a"}. "deployed" = the edge on in-market days only ` +
                        `(cash days excluded), same scale as Sh. Evidence, not a robustness verdict.`}
                    >
                      hold-out: {String(h.confidence_tier)}
                      {sh}
                      {ci}
                      {im}
                    </span>
                  );
                })()
              : null}
            {c.weaknesses && c.weaknesses.length > 0 && (
              <span
                className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-amber-950/60 text-amber-400"
                title={c.weaknesses.map((w) => `${w.gate}: ${w.reason || `${w.value} vs ${w.threshold}`}`).join(" · ")}
              >
                weak: {c.weaknesses.map((w) => w.gate).filter(Boolean).join(", ")}
              </span>
            )}
          </>
        ) : (
          <>
            {/* confidence-surfacing: the statistical-quality tier leads (F-6); Sharpe is NOT the headline */}
            <QualityBadge q={c.quality} />
            <span className={`text-[10px] uppercase px-1.5 py-0.5 rounded ${OOS_BADGE[c.oos_outcome] || OOS_BADGE.PENDING}`}>
              OOS {c.oos_outcome === "PENDING" ? "…" : c.oos_outcome}
            </span>
            {/* valconf/B2 §5.6: OOS lockbox evidence — the graded tier + an honest 90% Sharpe CI riding beside
                the PASS/FAIL/UNEVALUATED verdict. A band that straddles 0 means the edge isn't distinguishable
                from noise on the out-of-sample window (evidence, not a second verdict). */}
            {c.oos && (c.oos as Record<string, unknown>).confidence_tier
              ? (() => {
                  const o = c.oos as Record<string, unknown>;
                  const num = (v: unknown) => (typeof v === "number" ? v : Number(v));
                  const ci =
                    o.ci_low != null && o.ci_high != null
                      ? ` [${num(o.ci_low).toFixed(2)}, ${num(o.ci_high).toFixed(2)}]`
                      : "";
                  // valconf in-market masking: the OOS edge WHILE DEPLOYED (cash days excluded).
                  const imCi =
                    o.in_market_ci_low != null && o.in_market_ci_high != null
                      ? ` [${num(o.in_market_ci_low).toFixed(2)}, ${num(o.in_market_ci_high).toFixed(2)}]`
                      : "";
                  const im =
                    o.in_market_sharpe != null ? ` · deployed ${num(o.in_market_sharpe).toFixed(2)}${imCi}` : "";
                  return (
                    <span
                      className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-gray-800 text-gray-300 border border-gray-700"
                      title={`OOS lockbox — basis ${String(o.basis ?? "?")}; 90% Sharpe CI${
                        ci || " n/a"
                      }. "deployed" = the edge on in-market days only (cash days excluded), same scale. ` +
                        `Evidence, not a second robustness verdict.`}
                    >
                      oos: {String(o.confidence_tier)}
                      {ci}
                      {im}
                    </span>
                  );
                })()
              : null}
            <span className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">
              conf: {c.critic_confidence}
            </span>
          </>
        )}
      </div>
    </Link>
  );
}

export function EvidencePanel({
  candidates,
  failureCount,
  hypothesis,
  goalId,
  running,
}: {
  candidates: Candidate[];
  failureCount: number;
  hypothesis: Hypothesis | null;
  goalId: string;
  running: boolean;
}) {
  return (
    <div className="flex flex-col gap-4 border-l border-gray-800 bg-gray-950 p-4 overflow-y-auto">
      <div>
        <div className="flex justify-between items-center mb-2">
          <span className="text-xs uppercase font-semibold text-gray-500">Candidates</span>
          <span className="font-mono text-sm text-gray-300">{candidates.length}</span>
        </div>
        <div className="space-y-2">
          {candidates.length === 0 ? (
            <div className="text-[11px] text-gray-600 py-2">
              {running ? "No survivors yet — the agent is still falsifying." : "No survivors."}
            </div>
          ) : (
            candidates.map((c, i) => (
              <CandidateCard key={c.strategy_hash} c={c} goalId={goalId} rank={i + 1} />
            ))
          )}
        </div>
      </div>

      <Link
        href={`/dashboard/research/runs/${goalId}/graveyard`}
        className="flex justify-between items-center rounded border border-gray-800 bg-gray-900 p-2.5 hover:border-gray-700"
      >
        <span className="text-xs uppercase font-semibold text-gray-500">Graveyard</span>
        <span className="font-mono text-sm text-gray-400">{failureCount} →</span>
      </Link>

      <Link
        href={`/dashboard/research/runs/${goalId}/lineage`}
        className="flex justify-between items-center rounded border border-gray-800 bg-gray-900 p-2.5 hover:border-gray-700"
      >
        <span className="text-xs uppercase font-semibold text-gray-500">Lineage</span>
        <span className="font-mono text-sm text-gray-400">→</span>
      </Link>

      {hypothesis && (
        <div>
          <div className="text-xs uppercase font-semibold text-gray-500 mb-2">Current Hypothesis</div>
          <div className="rounded border border-purple-900/40 bg-purple-950/10 p-3 space-y-2 text-[12px]">
            <div className="text-gray-200">{hypothesis.economic_rationale}</div>
            <div className="text-gray-400">
              <span className="text-gray-600">mechanism: </span>
              {hypothesis.claimed_mechanism}
            </div>
            <div className="text-gray-400">
              <span className="text-gray-600">prediction: </span>
              {hypothesis.falsifiable_prediction}
            </div>
            <span className="inline-block text-[10px] uppercase px-1.5 py-0.5 rounded bg-purple-900/40 text-purple-300">
              prior: {hypothesis.prior_strength}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

// ── RunStatusBanner ───────────────────────────────────────────────────

export function RunStatusBanner({ state }: { state: ResearchState }) {
  if (state.status === "completed") {
    // Honest framing: "N not-yet-falsified of M" — never claim proof.
    return (
      <div className="bg-green-950/40 border-b border-green-900 px-4 py-2 text-sm text-green-300">
        Run complete — {state.candidates_count} not-yet-falsified of {state.total_iterations} trials.
      </div>
    );
  }
  if (state.status === "failed" || state.status === "stopped" || state.status === "interrupted") {
    return (
      <div className="bg-red-950/40 border-b border-red-900 px-4 py-2 text-sm text-red-300">
        Run {state.status}
        {state.error_message ? ` — ${state.error_message}` : ""}
        {state.budget_used_runs === 0 ? " (budget may be too small — no runs executed)" : ""}
      </div>
    );
  }
  return null;
}

// ── NotLive empty state ───────────────────────────────────────────────

export function NotLivePanel({ goalId }: { goalId: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
      <div className="text-gray-400 max-w-md">
        This run is no longer live. Open its durable record:
      </div>
      <div className="flex gap-2">
        {/* only the durable, standalone pages that survive eviction (candidates render inline on the
            live console, which no longer exists here — there is no candidates-list route to link to). */}
        {["report", "lineage", "graveyard"].map((seg) => (
          <Link
            key={seg}
            href={`/dashboard/research/runs/${goalId}/${seg}`}
            className="px-3 py-1.5 rounded text-sm bg-gray-800 hover:bg-gray-700 text-gray-200 capitalize"
          >
            {seg}
          </Link>
        ))}
      </div>
    </div>
  );
}
