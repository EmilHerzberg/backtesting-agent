// ATSX-15 (C-0): TS mirrors of the Pydantic research-loop responses.
// Single-sourced contract for the new Research screens (Console, Dossier).
// Mirrors src/backend/ai/research/router.py response models.

export interface ResearchState {
  phase: string;
  goal_text: string;
  current_asset: string;
  total_iterations: number;
  candidates_count: number;
  budget_used_runs: number;
  budget_remaining_runs: number;
  failure_count: number;
  error_message: string;
  // A-3 additions:
  status: string; // running | completed | failed | interrupted
  used_eur: number;
  agent_mode?: string; // W4 F-5: effective mode the run executed
  mode?: string; // P1: robustness | regime
  window_start?: string;
  window_end?: string;
  train_end?: string; // M31: regime select-on-train split — candidate metrics are measured on [window_start, train_end], hold-out is [train_end, window_end]
  provider_type?: string; // P2: effective LLM provider type
  leakage?: string; // P2 (F-11): run provider leakage state (mechanism_only|risk|unvalidated)
  max_seconds: number;
  started_at: string | null;
  current_lineage: string;
}

export interface ResearchEvent {
  id: number;
  ts: string;
  kind: string; // normalized wireframe taxonomy
  raw_kind: string;
  phase: string;
  lineage_id: string;
  title: string;
  detail: Record<string, unknown>;
  strategy_hash: string | null;
}

export interface Candidate {
  strategy_hash: string;
  run_id: string;
  template_id: string;
  security_id: string;
  sharpe_annual: number;
  total_return: number;
  max_drawdown: number;
  n_trades: number;
  critic_confidence: string;
  oos_outcome: string; // PASS | FAIL | PENDING
  oos?: Record<string, unknown>; // valconf §5.6 — OOS confidence tier + Sharpe CI (evidence beside the verdict)
  validation_status?: string; // P1 Chunk C — "unvalidated" for regime, "" robustness
  confidence?: string; // F-13 unified confidence (regime)
  decay?: Record<string, unknown>; // C2 — out-of-regime decay (P2-4: before/after slices)
  weaknesses?: { gate?: string; value?: number; threshold?: number; reason?: string }[]; // idea-surfacing (regime)
  holdout?: Record<string, unknown>; // P2 — within-regime forward-slice hold-out result (regime)
  quality?: QualitySummary; // confidence-surfacing — statistical-quality summary (both modes)
}

// Confidence-surfacing (CONFIDENCE-SURFACING-SPEC v2). Headlines the reliable per-run signals;
// the DSR is a caveated multiple-testing overlay (provisional on our run sizes).
export interface QualitySummary {
  tier: string; // robustness: strong|moderate|weak|provisional · regime: validated|moderate|low|very_low|failed
  headline: string; // plain-language, digit-free for the ambiguous magnitudes
  per_trade_t: number | null; // smart-activity per-trade edge t-stat
  per_trade_tier: string; // adequate | thin | ...
  benchmark_excess: number | null; // excess return vs buy-and-hold (fraction)
  oos: string; // PASS | FAIL | PENDING | OFF
  dsr: { value: number | null; trials: number; provisional: boolean } | null;
  mode: string; // robustness | regime (keeps robust vs UNVALIDATED unmissable — C-5)
}

export interface Hypothesis {
  hypothesis_id: string;
  economic_rationale: string;
  claimed_mechanism: string;
  falsifiable_prediction: string;
  prior_strength: string;
  proposed_template_id: string;
}

export interface GateResult {
  gate_id: string;
  status: string;
  value: number | null;
  threshold: number | null;
  details: Record<string, unknown>;
}

export interface Critique {
  confidence: string;
  recommendation: string;
  weaknesses: string[];
  prose: string;
}

export interface OOSVerdict {
  outcome: string; // PASS | FAIL | PENDING
  lineage_id: string;
  evaluated_at: string;
}

export interface RegimeSegment {
  type: string; // bull | bear | sideways
  return: number;
  sharpe: number;
  n_bars: number;
}

// ATSX-27: per-candidate evidence drill-downs for the dossier.
export interface CandidateArtifacts {
  regime_analysis: Record<string, RegimeSegment>;
  benchmark: { buy_hold_return?: number; buy_hold_sharpe?: number };
  equity_curve: number[];
}

// ATSX-26: one node of the lineage tree.
export interface LineageNode {
  lineage_id: string;
  parent_lineage_id: string | null;
  root_strategy_hash: string | null;
  declared_by: string;
  created_at: string | null;
}

export interface FailureItem {
  strategy_hash: string;
  template_id: string;
  security_id: string;
  failed_gate: string;
  failure_reason: string;
  critic_notes: string;
  gate_details: Record<string, unknown>;
}

export interface Graveyard {
  total: number;
  by_cause: Record<string, number>;
  failures: FailureItem[];
}

export interface ReportSection {
  key: string;
  title: string;
  numeric_fields: Record<string, unknown>;
  narrative: string;
}

export interface Report {
  status: string;
  goal_text: string;
  available: boolean;
  sections: ReportSection[];
}

export interface RunListItem {
  goal_id: string;
  goal_text: string;
  status: string;
  phase: string;
  used_runs: number;
  max_runs: number;
  candidates_count: number;
  failure_count: number;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface CoverageCell {
  security_id: string;
  template_id: string;
  survived: number;
  died: number;
  total: number;
}

export interface DirectorStats {
  audit_trial_count: number;
  valid_research_trial_count: number;
  candidates_found: number;
  total_runs: number;
  runs_by_status: Record<string, number>;
  failures_recorded: number;
  oos_passed: number;
  oos_failed: number;
  coverage: CoverageCell[];
}

export interface RunCreated {
  goal_id: string;
  status: string;
  goal_text: string;
  asset_pool: string[];
  strategy_families: string[];
  max_runs: number;
  target_candidates: number;
}

export interface ScopePreview {
  interpreted: { symbol_pool: string[]; strategy_pool: string[] };
  cost: { eur: number; runs: number; duration_seconds: number };
  source_annotations: Record<string, string>;
  mode: string;
  notes: string;
}

// A run is "terminal" (stop polling) when it is no longer making progress.
export const TERMINAL_STATUSES = new Set([
  "completed",
  "failed",
  "interrupted",
  "stopped",
]);

export function isTerminalStatus(status: string | undefined): boolean {
  return status != null && TERMINAL_STATUSES.has(status);
}

// Collapse a ResearchPhase into a run-level status pill (per wireframe §3.1).
export function phaseToPill(
  status: string,
  phase: string,
): "running" | "paused" | "completed" | "stopped" | "failed" | "connecting" {
  if (status === "completed") return "completed";
  if (status === "failed") return "failed";
  if (status === "interrupted" || status === "stopped") return "stopped";
  if (status === "paused") return "paused";
  if (phase === "idle" || phase === "" ) return "connecting";
  return "running";
}
