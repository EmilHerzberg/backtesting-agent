// Start a Run — configure + launch. 6 Simple controls + AI mode (W4) + Advanced + mandatory Preview.
// Honest: rule-based is €0; AI modes show a per-run cost estimate before launch.
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { request } from "@/lib/api";
import { RunCreated, ScopePreview } from "@/lib/research/types";
import { AgentMode, estimateEur, estimateLabel } from "@/lib/research/cost";
import { InfoIcon, LeakageBadge } from "@/components/info-icon";

const MAX_EUR = 50; // StartRunRequest default € cap

const BUDGETS = {
  quick: { label: "Quick", max_runs: 8, max_seconds: 300, hint: "~8 backtests · ~5 min" },
  medium: { label: "Medium", max_runs: 20, max_seconds: 600, hint: "~20 backtests · ~10 min" },
  deep: { label: "Deep", max_runs: 50, max_seconds: 1800, hint: "~50 backtests · ~30 min" },
} as const;
type BudgetKey = keyof typeof BUDGETS;

const RIGORS = {
  exploratory: { label: "Exploratory", hint: "Relaxed gates — usually surfaces something on a first pass.", oos: false, oosLocked: false },
  standard: { label: "Standard", hint: "Calibrated for daily-bar data; OOS on by default.", oos: true, oosLocked: false },
  strict: { label: "Strict", hint: "Tightens DSR / performance / cost gates and forces OOS on.", oos: true, oosLocked: true },
} as const;
type RigorKey = keyof typeof RIGORS;

const STYLES = [
  { id: "trend_following", label: "Trend-following" },
  { id: "mean_reversion", label: "Mean-reversion" },
  { id: "multi_factor", label: "Multi-factor" },
];

const AI_MODES = {
  rule_based: { label: "Rule-based", hint: "Deterministic, no AI — €0." },
  ai_assisted: { label: "AI-assisted", hint: "An LLM Critic reviews survivors + writes the report." },
  full_ai: { label: "Full-AI", hint: "An LLM Strategist proposes, an LLM Critic reviews + writes the report." },
} as const;
type AiModeKey = keyof typeof AI_MODES;

interface Catalog {
  templates: { id: string; family: string; params: Record<string, [number, number]> }[];
  families: { id: string; templates: string[] }[];
  baskets: { id: string; label: string; tickers: string[] }[];
  known_symbols: string[];
  rigor_presets: string[];
}
interface Provider { id: number; name: string; provider_type: string; is_active: boolean; leakage?: string }
interface Model { model_id: string; display_name: string; provider: string; input_price: number | null; output_price: number | null; supports_reasoning?: boolean; leakage?: string }

export default function NewRunPage() {
  const router = useRouter();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [providersLoaded, setProvidersLoaded] = useState(false);
  const [models, setModels] = useState<Model[]>([]);

  const [goal, setGoal] = useState("");
  const [assets, setAssets] = useState<string[]>(["AAPL"]);
  const [assetInput, setAssetInput] = useState("");
  const [families, setFamilies] = useState<string[]>(["trend_following", "mean_reversion"]);
  const [rigor, setRigor] = useState<RigorKey>("standard");
  const [budget, setBudget] = useState<BudgetKey>("medium");
  const [oos, setOos] = useState(true);
  // P1 Chunk D — regime mode + window
  const [mode, setMode] = useState<"robustness" | "regime">("robustness");
  const [windowStart, setWindowStart] = useState("");
  const [windowEnd, setWindowEnd] = useState("");

  const [agentMode, setAgentMode] = useState<AiModeKey>("rule_based");
  const [providerName, setProviderName] = useState("");
  const [modelId, setModelId] = useState("");

  const [advanced, setAdvanced] = useState(false);
  const [maxRuns, setMaxRuns] = useState(20);
  const [maxSeconds, setMaxSeconds] = useState(600);
  const [target, setTarget] = useState(1);
  const [seed, setSeed] = useState(42);

  const [showKeyGate, setShowKeyGate] = useState(false);  // F-3: AI mode without a key
  const [stage, setStage] = useState<"config" | "preview">("config");
  const [preview, setPreview] = useState<ScopePreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    request<Catalog>("/research/catalog").then(setCatalog).catch(() => {});
    request<Provider[]>("/ai/providers")
      .then((p) => setProviders(p.filter((x) => x.is_active)))
      .catch(() => {})
      .finally(() => setProvidersLoaded(true));
    request<Model[]>("/ai/models").then(setModels).catch(() => {});
  }, []);
  useEffect(() => {
    setOos(RIGORS[rigor].oosLocked ? true : RIGORS[rigor].oos);
  }, [rigor]);
  useEffect(() => {
    setMaxRuns(BUDGETS[budget].max_runs);
    setMaxSeconds(BUDGETS[budget].max_seconds);
  }, [budget]);

  const hasProvider = providers.length > 0;
  const providerModels = useMemo(() => {
    const sp = providers.find((p) => p.name === providerName);
    if (!sp) return [];
    return models.filter((m) => m.provider === sp.provider_type && !/tts|speech|embed/i.test(m.model_id));
  }, [models, providers, providerName]);
  const selModel = providerModels.find((m) => m.model_id === modelId);
  const estimate = useMemo(() => estimateEur(agentMode as AgentMode, selModel, maxRuns, rigor), [agentMode, selModel, maxRuns, rigor]);

  // Default provider when switching to an AI mode; default to the cheapest model.
  useEffect(() => {
    if (agentMode !== "rule_based" && providers.length > 0 && !providerName) setProviderName(providers[0].name);
  }, [agentMode, providers, providerName]);
  useEffect(() => {
    if (providerModels.length > 0 && !providerModels.some((m) => m.model_id === modelId)) {
      const cheapest = [...providerModels].sort((a, b) => (a.input_price ?? 1e9) - (b.input_price ?? 1e9))[0];
      setModelId(cheapest?.model_id ?? "");
    }
  }, [providerModels, modelId]);

  const known = useMemo(() => new Set(catalog?.known_symbols ?? []), [catalog]);
  const familyTemplates = useMemo(
    () => (catalog?.templates ?? []).filter((t) => families.includes(t.family)),
    [catalog, families],
  );

  const toggleFamily = (id: string) =>
    setFamilies((f) => (f.includes(id) ? f.filter((x) => x !== id) : [...f, id]));
  const addAsset = (raw: string) => {
    const t = raw.trim().toUpperCase();
    if (t && !assets.includes(t)) setAssets((a) => [...a, t]);
    setAssetInput("");
  };
  const removeAsset = (t: string) => setAssets((a) => a.filter((x) => x !== t));
  const applyBasket = (id: string) => {
    const b = catalog?.baskets.find((x) => x.id === id);
    if (b) setAssets(Array.from(new Set(b.tickers.slice(0, 10))));
  };

  const resolvedCount = assets.filter((a) => known.has(a)).length;
  const aiReady = agentMode === "rule_based" || (!!providerName && !!modelId);
  const regimeReady = mode !== "regime" || (!!windowStart && !!windowEnd && windowStart < windowEnd);
  const modeBadge = agentMode === "rule_based" ? "rule-based · €0" : AI_MODES[agentMode].label;
  const wontUse =
    agentMode === "rule_based"
      ? "use any AI/LLM (rule-based) · optimise params (random-samples fixed ranges) · run walk-forward"
      : agentMode === "ai_assisted"
      ? "use AI to propose strategies (the Strategist stays rule-based) · optimise params · run walk-forward"
      : "run an optimizer or walk-forward (it picks params within fixed ranges)";

  const doPreview = async () => {
    // F-3: AI mode picked without a configured key → popup to Settings (rule-based never blocked).
    if (agentMode !== "rule_based" && !aiReady) {
      setShowKeyGate(true);
      return;
    }
    setError("");
    try {
      const p = await request<ScopePreview>(
        `/research/runs/preview?goal_text=${encodeURIComponent(goal || assets.join(" "))}&max_runs=${maxRuns}`,
      );
      setPreview(p);
      setStage("preview");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Fehler");
    }
  };

  const start = async () => {
    setBusy(true);
    setError("");
    try {
      const created = await request<RunCreated>("/research/runs", {
        method: "POST",
        body: JSON.stringify({
          goal_text: goal || `${families.join("/")} on ${assets.join(",")}`,
          asset_pool: assets,
          strategy_families: families,
          rigor,
          enable_oos: oos,
          seed,
          max_runs: maxRuns,
          max_seconds: maxSeconds,
          target_candidates: target,
          agent_mode: agentMode,
          provider: agentMode === "rule_based" ? null : providerName,
          model: agentMode === "rule_based" ? null : modelId,
          mode,
          window_start: mode === "regime" ? windowStart : null,
          window_end: mode === "regime" ? windowEnd : null,
        }),
      });
      router.push(`/dashboard/research/runs/${created.goal_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Fehler");
      setBusy(false);
    }
  };

  const seg = (active: boolean) =>
    `flex-1 px-3 py-2 rounded text-sm font-medium transition ${
      active ? "bg-blue-600 text-white" : "bg-gray-800 text-gray-300 hover:bg-gray-700"
    }`;

  // ── Preview stage ───────────────────────────────────────────────────
  if (stage === "preview") {
    return (
      <div className="max-w-2xl mx-auto p-6 space-y-5">
        <div className="flex items-center gap-3">
          <button onClick={() => setStage("config")} className="text-sm text-gray-400 hover:text-gray-200">
            ← Back
          </button>
          <h1 className="text-xl font-semibold text-gray-100">Preview scope</h1>
          <span className="text-[10px] uppercase font-semibold px-2 py-0.5 rounded bg-gray-800 text-gray-400">
            {modeBadge}
          </span>
        </div>
        {error && (
          <div className="rounded border border-red-900 bg-red-950/40 px-3 py-2 text-sm text-red-300">{error}</div>
        )}
        <div className="rounded border border-gray-800 bg-gray-900 p-4 text-sm space-y-2">
          <Row label="Goal" value={goal || "—"} />
          <Row label="Universe" value={`${assets.join(", ")}  (${resolvedCount}/${assets.length} known)`} />
          <Row label="Styles" value={families.map((f) => f.replace("_", "-")).join(", ")} />
          <Row label="Rigor" value={`${RIGORS[rigor].label} — ${RIGORS[rigor].hint}`} />
          <Row label="Budget" value={`${BUDGETS[budget].label} → ~${maxRuns} backtests · ~${Math.round(maxSeconds / 60)} min`} />
          <Row label="Mode" value={mode === "regime" ? `Regime-fit  ${windowStart} → ${windowEnd}  · UNVALIDATED` : "Robustness (2015–2023)"} />
          <Row label="OOS" value={mode === "regime" ? "OFF (regime mode — decay reported instead)" : (oos ? "ON (2024–2025 hold-out, terminal PASS/FAIL)" : "OFF")} />
          <Row label="AI mode" value={`${AI_MODES[agentMode].label}${agentMode !== "rule_based" ? ` · ${modelId}` : ""} — ${AI_MODES[agentMode].hint}`} />
          <Row label="Est. cost" value={estimateLabel(agentMode as AgentMode, estimate, MAX_EUR)} />
        </div>
        {/* Backend's interpretation of the free-text goal — the actual symbol/strategy pool it parsed, and
            its own scope estimate. This can differ from the structured inputs above, so surface it before launch. */}
        {preview && (
          <div className="rounded border border-blue-900/60 bg-blue-950/20 p-4 text-sm space-y-2">
            <div className="text-[11px] uppercase font-semibold tracking-wide text-blue-300">
              How the agent read your goal
            </div>
            <Row
              label="Symbol pool"
              value={preview.interpreted.symbol_pool.length ? preview.interpreted.symbol_pool.join(", ") : "—"}
            />
            <Row
              label="Strategy pool"
              value={
                preview.interpreted.strategy_pool.length
                  ? preview.interpreted.strategy_pool.map((s) => s.replace(/_/g, "-")).join(", ")
                  : "—"
              }
            />
            <Row
              label="Interpreted scope"
              value={`~${preview.cost.runs} backtests · ~${Math.max(1, Math.round(preview.cost.duration_seconds / 60))} min`}
            />
            {Object.keys(preview.source_annotations || {}).length > 0 && (
              <div className="text-[11px] text-gray-500">
                {Object.entries(preview.source_annotations).map(([k, v]) => (
                  <span key={k} className="mr-3">
                    <span className="text-gray-400">{k}</span>: {v}
                  </span>
                ))}
              </div>
            )}
            {preview.notes && <div className="text-[11px] text-gray-500">{preview.notes}</div>}
          </div>
        )}
        <div className="rounded border border-gray-800 bg-gray-950 p-4 text-[12px] space-y-2">
          <div>
            <span className="text-green-400 font-semibold">This run WILL:</span>{" "}
            <span className="text-gray-300">
              propose strategies, backtest them, run the quality-gate battery at the rigor you set, adversarially
              critique survivors{agentMode !== "rule_based" ? " (with an LLM)" : ""}, and write an honest report
              {agentMode !== "rule_based" ? " (LLM-written)" : ""}.
            </span>
          </div>
          <div>
            <span className="text-amber-400 font-semibold">This run will NOT:</span>{" "}
            <span className="text-gray-400">{wontUse}.</span>
          </div>
          {agentMode !== "rule_based" && (
            <div className="text-gray-500">
              Cost is an estimate — it depends on how many strategies clear your {RIGORS[rigor].label} gates and
              is capped at your €/time budget. Full-AI calls the model every trial; discarded proposals still bill.
            </div>
          )}
          <div className="text-gray-500">
            Gate honesty: 2 gates are no-ops today (lag-fragility, provider-capability) and pass automatically;
            DSR multiplicity is per-run only. Your rigor binds every other gate.
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setStage("config")} className="px-3 py-2 rounded text-sm bg-gray-800 hover:bg-gray-700 text-gray-200">
            ← Back
          </button>
          <button
            onClick={start}
            disabled={busy || assets.length === 0 || !aiReady || !regimeReady}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-white text-sm font-semibold disabled:opacity-50"
          >
            {busy ? "Starting…" : "Start run"}
          </button>
        </div>
      </div>
    );
  }

  // ── Config stage ────────────────────────────────────────────────────
  return (
    <div className="max-w-2xl mx-auto p-6 space-y-5">
      {showKeyGate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-md rounded-lg border border-gray-800 bg-gray-900 p-6 space-y-4">
            <h2 className="text-lg font-bold text-gray-100">AI-Modus braucht einen API-Key</h2>
            <p className="text-sm text-gray-400">
              Der Modus „{AI_MODES[agentMode].label}" nutzt ein LLM und braucht einen AI-API-Key. Hinterlege
              einen in den Einstellungen — oder nutze den kostenlosen regelbasierten Modus.
            </p>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => { setAgentMode("rule_based"); setShowKeyGate(false); }}
                className="px-4 py-2 text-sm bg-gray-800 hover:bg-gray-700 rounded text-gray-200"
              >
                Regelbasiert nutzen
              </button>
              <button
                onClick={() => router.push("/settings")}
                className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 rounded font-semibold"
              >
                Zu den Einstellungen →
              </button>
            </div>
          </div>
        </div>
      )}
      <div className="flex items-center gap-3">
        <Link href="/dashboard/research" className="text-sm text-gray-400 hover:text-gray-200">
          ← Runs
        </Link>
        <h1 className="text-xl font-semibold text-gray-100">New research run</h1>
        <span className="text-[10px] uppercase font-semibold px-2 py-0.5 rounded bg-gray-800 text-gray-400">
          {modeBadge}
        </span>
      </div>
      <p className="text-sm text-gray-500">
        An autonomous falsification run: it proposes strategies, backtests them, and tries to kill them.
      </p>
      {error && (
        <div className="rounded border border-red-900 bg-red-950/40 px-3 py-2 text-sm text-red-300">{error}</div>
      )}

      <div className="space-y-5 rounded border border-gray-800 bg-gray-900 p-4">
        {/* ① Goal */}
        <Field label="Goal" hint="Plain language. Labels the run and seeds the scope preview.">
          <input
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder='e.g. "robust mean-reversion for my financials"'
            className="w-full px-3 py-2 bg-gray-950 border border-gray-800 rounded text-sm placeholder:text-gray-700"
          />
        </Field>

        {/* ② Universe */}
        <Field label="Universe" hint="Pick a curated basket or type tickers; each is confirmed before start.">
          <div className="flex flex-wrap gap-1.5 mb-2">
            {assets.map((t) => (
              <span
                key={t}
                className={`inline-flex items-center gap-1 text-xs font-mono px-2 py-1 rounded ${
                  known.has(t) ? "bg-gray-800 text-gray-200" : "bg-amber-900/40 text-amber-300"
                }`}
              >
                {t} {known.has(t) ? "✓" : "⚠"}
                <button onClick={() => removeAsset(t)} className="text-gray-500 hover:text-gray-300">×</button>
              </span>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              value={assetInput}
              onChange={(e) => setAssetInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addAsset(assetInput);
                }
              }}
              placeholder="+ add ticker, Enter"
              className="flex-1 px-3 py-2 bg-gray-950 border border-gray-800 rounded text-sm font-mono placeholder:text-gray-700"
            />
            <select
              onChange={(e) => e.target.value && applyBasket(e.target.value)}
              value=""
              className="px-2 py-2 bg-gray-950 border border-gray-800 rounded text-sm text-gray-300"
            >
              <option value="">Basket ▾</option>
              {(catalog?.baskets ?? []).map((b) => (
                <option key={b.id} value={b.id}>{b.label} ({b.tickers.length})</option>
              ))}
            </select>
          </div>
          <div className="text-[11px] text-gray-600 mt-1">
            {resolvedCount}/{assets.length} known · ⚠ = will be attempted but not pre-verified
          </div>
        </Field>

        {/* ③ Strategy styles */}
        <Field label="Strategy styles" hint="Which families to try. Templates picked automatically (see Advanced).">
          <div className="flex flex-wrap gap-2">
            {STYLES.map((s) => (
              <button
                key={s.id}
                onClick={() => toggleFamily(s.id)}
                className={`px-3 py-1.5 rounded text-sm transition ${
                  families.includes(s.id) ? "bg-blue-900 text-blue-200 border border-blue-700" : "bg-gray-800 text-gray-400 hover:bg-gray-700"
                }`}
              >
                {families.includes(s.id) ? "✓ " : ""}{s.label}
              </button>
            ))}
          </div>
        </Field>

        {/* ④ Rigor */}
        <Field label="Rigor" hint={RIGORS[rigor].hint}>
          <div className="flex gap-2">
            {(Object.keys(RIGORS) as RigorKey[]).map((k) => (
              <button key={k} onClick={() => setRigor(k)} className={seg(rigor === k)}>
                {RIGORS[k].label}
              </button>
            ))}
          </div>
        </Field>

        {/* ⑤ Budget */}
        <Field label="Budget" hint={`${BUDGETS[budget].hint} — caps runs + time, not rigor.`}>
          <div className="flex gap-2">
            {(Object.keys(BUDGETS) as BudgetKey[]).map((k) => (
              <button key={k} onClick={() => setBudget(k)} className={seg(budget === k)}>
                {BUDGETS[k].label}
              </button>
            ))}
          </div>
        </Field>

        {/* ⑥ OOS */}
        <Field label="Out-of-sample check" hint="Holds out 2024–2025 and re-tests survivors once. Your 'is it curve-fit?' check.">
          <label className={`inline-flex items-center gap-2 text-sm ${RIGORS[rigor].oosLocked ? "opacity-60" : ""}`}>
            <input
              type="checkbox"
              checked={oos}
              disabled={RIGORS[rigor].oosLocked}
              onChange={(e) => setOos(e.target.checked)}
            />
            <span className="text-gray-300">{oos ? "On" : "Off"}{RIGORS[rigor].oosLocked ? " — forced on at Strict" : ""}{mode === "regime" ? " — off in regime mode" : ""}</span>
          </label>
        </Field>

        {/* Research mode (P1 regime) */}
        <Field label="Research mode" hint={mode === "regime"
          ? "Regime-fit: backtests a window YOU choose; the LLMs adapt to it. Results are labelled UNVALIDATED."
          : "Robustness: the fixed 2015–2023 window; survivors are not-yet-falsified across many regimes."}>
          <div className="flex gap-2">
            <button onClick={() => setMode("robustness")} className={seg(mode === "robustness")}>Robustness</button>
            <button onClick={() => setMode("regime")} className={seg(mode === "regime")}>Regime-fit</button>
          </div>
          {mode === "regime" && (
            <div className="mt-3 space-y-2">
              <div className="flex gap-2">
                <label className="flex-1 block">
                  <span className="text-[11px] uppercase font-semibold text-gray-500">Window start</span>
                  <input type="date" value={windowStart} onChange={(e) => setWindowStart(e.target.value)}
                    className="mt-1 w-full px-2 py-1.5 bg-gray-950 border border-gray-800 rounded text-sm font-mono" />
                </label>
                <label className="flex-1 block">
                  <span className="text-[11px] uppercase font-semibold text-gray-500">Window end</span>
                  <input type="date" value={windowEnd} onChange={(e) => setWindowEnd(e.target.value)}
                    className="mt-1 w-full px-2 py-1.5 bg-gray-950 border border-gray-800 rounded text-sm font-mono" />
                </label>
              </div>
              {!regimeReady && (
                <div className="text-[11px] text-amber-600">Set both dates; start must be before end.</div>
              )}
              <div className="rounded border border-amber-800 bg-amber-950/40 px-3 py-2 text-[12px] text-amber-300">
                ⚠ <b>Regime-fit — NOT robustness-validated.</b> Short windows can&apos;t be overfit-checked, so every
                candidate is labelled UNVALIDATED (an idea-finder, not a verdict). OOS is off in this mode; instead a
                decay characterization shows how much of the edge persists outside your window.{" "}
                <b>Tip:</b> put the regime&apos;s <i>character</i> in the goal (e.g. &quot;momentum in AI names&quot;),
                not specific dates — the model is given the window <i>length</i>, not the dates, to avoid look-ahead.
              </div>
            </div>
          )}
        </Field>

        {/* ⑦ AI mode (W4) */}
        <Field label="AI mode" hint={AI_MODES[agentMode].hint}>
          <div className="flex gap-2">
            {(Object.keys(AI_MODES) as AiModeKey[]).map((k) => {
              const needsKey = k !== "rule_based" && !hasProvider;
              return (
                <button
                  key={k}
                  // F-3: clickable even without a key — clicking an AI mode with no key pops the gate → Settings.
                  onClick={() => { if (needsKey) { setShowKeyGate(true); return; } setAgentMode(k); }}
                  title={needsKey ? "Braucht einen API-Key — klicken für Details" : ""}
                  className={seg(agentMode === k)}
                >
                  {AI_MODES[k].label}
                </button>
              );
            })}
          </div>
          {providersLoaded && !hasProvider && (
            <div className="text-[11px] text-amber-600 mt-1">
              Connect an LLM provider in AI settings to enable AI modes.
            </div>
          )}
          {agentMode !== "rule_based" && hasProvider && (
            <>
              <div className="flex gap-2 mt-2 items-center">
                <select
                  value={providerName}
                  onChange={(e) => setProviderName(e.target.value)}
                  className="flex-1 px-2 py-2 bg-gray-950 border border-gray-800 rounded text-sm text-gray-300"
                >
                  {providers.map((p) => <option key={p.id} value={p.name}>{p.name}</option>)}
                </select>
                <select
                  value={modelId}
                  onChange={(e) => setModelId(e.target.value)}
                  className="flex-1 px-2 py-2 bg-gray-950 border border-gray-800 rounded text-sm text-gray-300"
                >
                  {providerModels.length === 0 && <option value="">no models</option>}
                  {providerModels.map((m) => (
                    <option key={m.model_id} value={m.model_id}>
                      {m.display_name}{m.supports_reasoning ? " ✦ reasoning" : ""}
                    </option>
                  ))}
                </select>
                <InfoIcon />
              </div>
              {selModel?.leakage && (
                <div className="mt-1">
                  <LeakageBadge state={selModel.leakage} />
                </div>
              )}
            </>
          )}
          {agentMode !== "rule_based" && (
            <div className="text-[11px] text-gray-500 mt-1">
              Est. cost: {estimateLabel(agentMode as AgentMode, estimate, MAX_EUR)}
            </div>
          )}
        </Field>

        {/* Advanced */}
        <div>
          <button onClick={() => setAdvanced((a) => !a)} className="text-xs text-gray-500 hover:text-gray-300">
            {advanced ? "▾" : "▸"} Advanced (raw caps · seed · templates)
          </button>
          {advanced && (
            <div className="mt-3 space-y-3 border-l border-gray-800 pl-3">
              <div className="grid grid-cols-3 gap-2">
                <Num label="Max backtests" v={maxRuns} set={setMaxRuns} />
                <Num label="Max seconds" v={maxSeconds} set={setMaxSeconds} />
                <Num label="Target" v={target} set={setTarget} />
              </div>
              <div className="grid grid-cols-3 gap-2">
                <Num label="Seed" v={seed} set={setSeed} />
              </div>
              <div>
                <div className="text-[11px] uppercase font-semibold text-gray-500 mb-1">Templates (optional)</div>
                <div className="flex flex-wrap gap-1.5">
                  {familyTemplates.map((t) => (
                    <span key={t.id} className="text-[11px] font-mono px-2 py-1 rounded bg-gray-800 text-gray-400">
                      {t.id}
                    </span>
                  ))}
                  {familyTemplates.length === 0 && <span className="text-[11px] text-gray-600">pick styles above</span>}
                </div>
              </div>
              <div className="text-[11px] text-gray-600">
                Optimizer / walk-forward / per-param ranges are intentionally absent — the engine random-samples
                fixed ranges.
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="flex justify-end">
        <button
          onClick={doPreview}
          disabled={assets.length === 0 || families.length === 0 || !regimeReady}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-white text-sm font-semibold disabled:opacity-50"
        >
          Preview scope →
        </button>
      </div>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs uppercase font-semibold text-gray-400">{label}</div>
      {children && <div className="mt-1.5">{children}</div>}
      {hint && <div className="text-[11px] text-gray-600 mt-1">{hint}</div>}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2">
      <span className="text-gray-500 w-20 shrink-0">{label}</span>
      <span className="text-gray-300">{value}</span>
    </div>
  );
}

function Num({ label, v, set }: { label: string; v: number; set: (n: number) => void }) {
  return (
    <label className="block">
      <span className="text-[11px] uppercase font-semibold text-gray-500">{label}</span>
      <input
        type="number"
        value={v}
        onChange={(e) => set(Number(e.target.value))}
        className="mt-1 w-full px-2 py-1.5 bg-gray-950 border border-gray-800 rounded text-sm font-mono"
      />
    </label>
  );
}
