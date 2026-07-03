"use client";

// Account-settings (F-12): the reasoning + mechanism-only explainer, grounded in our leakage research
// (3 states, measured-vs-assumed). See docs/bt-agent/LEAKAGE-CLASSIFICATION-GROUNDED.md.
export const MECHANISM_ONLY_EXPLAINER =
  "Use a validated mechanism-only reasoning model for strategy selection. Mechanism-only models (validated in " +
  "our research: DeepSeek Reasoner, BytePlus Seed 2.0 Pro) reason from the mechanism you give them, not from " +
  "memorised market history — so they can't inflate a backtest by ‘recalling’ which strategies worked. " +
  "Leakage-risk models (Gemini — measured; GPT / Claude — assumed, untested) may leak outcomes into selection → " +
  "a contaminated, over-optimistic backtest. ‘Unrated’ models (e.g. MiniMax, Qwen, Moonshot, Zhipu, DeepSeek " +
  "Chat) weren't evaluated — no safety claim either way. Prefer mechanism-only for selection; use leakage-risk " +
  "models only as a research oracle.";

// Per-provider-type summary (mirrors the backend provider_leakage) — for marking the add-key dropdown before a
// key exists. The API is authoritative for existing keys/models.
export const PROVIDER_LEAKAGE: Record<string, string> = {
  openai: "risk", gemini: "risk", anthropic: "risk",
  deepseek: "mechanism_only", byteplus: "mechanism_only",
  // minimax / qwen / zhipu / moonshot → unvalidated (default)
};

// A hoverable info icon. Defaults to the mechanism-only explainer.
export function InfoIcon({ text = MECHANISM_ONLY_EXPLAINER, label = "info" }: { text?: string; label?: string }) {
  return (
    <span
      tabIndex={0}
      role="img"
      aria-label={label}
      title={text}
      className="inline-flex items-center justify-center w-4 h-4 rounded-full border border-gray-600 text-gray-400 text-[10px] font-semibold cursor-help align-middle select-none"
    >
      i
    </span>
  );
}

const _BADGE = "inline-flex items-center gap-1 text-[10px] uppercase px-1.5 py-0.5 rounded border";

// 3-state leakage marker (F-11): risk / mechanism_only / unvalidated. Grounded in the research.
export function LeakageBadge({ state }: { state?: string }) {
  if (state === "risk")
    return (
      <span title="Data-leakage risk for backtest selection (measured for Gemini; assumed/untested for GPT & Claude). Use only as a research oracle."
        className={`${_BADGE} bg-amber-950 text-amber-300 border-amber-800`}>⚠ leakage risk</span>
    );
  if (state === "mechanism_only")
    return (
      <span title="Validated mechanism-only — reasons from the mechanism, not memorised outcomes. Recommended for strategy selection."
        className={`${_BADGE} bg-teal-950 text-teal-300 border-teal-800`}>✓ mechanism-only</span>
    );
  if (state === "unvalidated")
    return (
      <span title="Not evaluated for leakage in our research — no safety claim either way; treat with caution."
        className={`${_BADGE} bg-gray-800 text-gray-400 border-gray-700`}>· unrated</span>
    );
  return null;
}
