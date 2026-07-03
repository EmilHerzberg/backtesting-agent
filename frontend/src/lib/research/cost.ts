// W4 — per-run LLM cost estimate (frontend). Pure + testable; split prompt/completion pricing.
// See W4-AGENT-MODE-SPEC.md. The post-run `used_eur` (from /runs/{id}/state) is the ground truth;
// this is a pre-launch guide shown as "up to".

export type AgentMode = "rule_based" | "ai_assisted" | "full_ai";

export interface ModelPrice {
  input_price: number | null; // EUR per 1M prompt tokens (null = unknown, NOT free)
  output_price: number | null; // EUR per 1M completion tokens
}

// per-call token estimates (W1/W2/W3B), split prompt vs completion
const TOK = {
  critic: { p: 1100, c: 200 },
  strat: { p: 700, c: 200 },   // W3B-F5: calibrated from the W2/W3 live smokes (~700, not 1300)
  report: { p: 700, c: 200 },  // W3B-F2: the Reporter — exactly ONE fixed call/run
} as const;
// gate-pass rate by rigor (W4-4): only gate-passing trials reach the Critic
const PASS: Record<string, number> = { exploratory: 0.3, standard: 0.15, strict: 0.03 };

/**
 * EUR estimate for a run. Returns:
 *  - 0     → rule_based, or a genuinely free model (both prices 0)
 *  - null  → UNKNOWN: a price is null (not configured) — never show this as €0 (W4S-1)
 *  - >0    → the estimate
 */
export function estimateEur(
  mode: AgentMode,
  model: ModelPrice | undefined,
  maxRuns: number,
  rigor: string,
): number | null {
  if (mode === "rule_based") return 0;
  if (!model) return null;
  const inP = model.input_price;
  const outP = model.output_price;
  if (inP == null || outP == null) return null; // null pricing != free
  const callEur = (t: { p: number; c: number }) => (t.p * inP + t.c * outP) / 1_000_000;
  const p = PASS[rigor] ?? 0.15;
  const critic = p * maxRuns * callEur(TOK.critic);
  const strat = mode === "full_ai" ? maxRuns * callEur(TOK.strat) : 0;
  const report = callEur(TOK.report); // W3B: one fixed Reporter call/run (ai_assisted + full_ai)
  return critic + strat + report; // 0 only if both prices are genuinely 0 (free)
}

/** Human label for the estimate, honest about unknown/free/capped. `maxEur` = the run's € cap. */
export function estimateLabel(
  mode: AgentMode,
  estimate: number | null,
  maxEur: number,
): string {
  if (mode === "rule_based") return "€0 — no AI";
  if (estimate === null) return "unknown — no pricing configured for this model";
  if (estimate === 0) return "€0 — free model";
  if (estimate > maxEur) return `will stop at your €${maxEur} budget (~€${estimate.toFixed(2)} otherwise)`;
  const shown = estimate < 0.0001 ? "< €0.0001" : `≈ €${estimate.toFixed(4)}`;
  return `${shown} — up to your €${maxEur} cap`;
}
