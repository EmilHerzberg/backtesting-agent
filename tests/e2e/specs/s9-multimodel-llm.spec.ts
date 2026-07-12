import fs from "fs";
import path from "path";
import { expect, test } from "@playwright/test";
import { BACKEND, apiLogin, apiRegisterVerify, uniqueEmail } from "../helpers/auth";
import { getReport, pollUntilTerminal, startRunApi } from "../helpers/run";

// S9 — PAID, GATED. Runs the SAME small full_ai scenario across each configured provider (Gemini / Claude /
// ChatGPT / DeepSeek) and records the outcome, so a provider that crashes the LLM-agent wiring, returns
// unparseable output, produces an empty report, or mis-reports leakage shows up in a side-by-side artifact.
//
// Gated: only runs with E2E_LLM=1 AND the provider's key env var set. Never runs on CI / unattended.
// Keys: E2E_OPENAI_KEY, E2E_ANTHROPIC_KEY (Claude), E2E_GEMINI_KEY, E2E_DEEPSEEK_KEY.

const LLM_ON = process.env.E2E_LLM === "1";

// REASONING models, tiered by cost (per the run decision): o3 / claude-sonnet (mid-tier reasoning, NOT the
// $15/$75 Opus) / gemini-3-pro / deepseek-reasoner (frontier R1, cheap). Override any with E2E_<PROVIDER>_MODEL.
// Defaults are pre-flight-validated REASONING models. NOTE gemini uses gemini-2.5-pro (the catalog's
// gemini-3-pro is Vertex-only and 404s on an AI-Studio key). Anthropic/Moonshot are included but need a
// funded/valid key. Override any with E2E_<PROVIDER>_MODEL; keys via the keyEnv below.
const PROVIDERS = [
  { name: "openai", type: "openai", keyEnv: "E2E_OPENAI_KEY", modelEnv: "E2E_OPENAI_MODEL", defaultModel: "o3" },
  { name: "claude", type: "anthropic", keyEnv: "E2E_ANTHROPIC_KEY", modelEnv: "E2E_ANTHROPIC_MODEL", defaultModel: "claude-sonnet-4-6" },
  { name: "gemini", type: "gemini", keyEnv: "E2E_GEMINI_KEY", modelEnv: "E2E_GEMINI_MODEL", defaultModel: "gemini-2.5-pro" },
  { name: "deepseek", type: "deepseek", keyEnv: "E2E_DEEPSEEK_KEY", modelEnv: "E2E_DEEPSEEK_MODEL", defaultModel: "deepseek-reasoner" },
  { name: "zhipu", type: "zhipu", keyEnv: "E2E_ZAI_KEY", modelEnv: "E2E_ZAI_MODEL", defaultModel: "glm-5" },
  { name: "moonshot", type: "moonshot", keyEnv: "E2E_MOONSHOT_KEY", modelEnv: "E2E_MOONSHOT_MODEL", defaultModel: "kimi-k2.5-thinking" },
  { name: "byteplus", type: "byteplus", keyEnv: "E2E_BYTEPLUS_KEY", modelEnv: "E2E_BYTEPLUS_MODEL", defaultModel: "seed-2-0-pro-260328" },
];
type ProviderCfg = (typeof PROVIDERS)[number];

// An explicit env override wins; else the validated per-provider default (do NOT consult the catalog — its
// gemini entry is Vertex-only and would wrongly reject the working gemini-2.5-pro).
function pickModel(p: ProviderCfg): string {
  return process.env[p.modelEnv] || p.defaultModel;
}

// Write each result to the artifact AS IT COMPLETES (read-modify-write, dedup by provider). A module-level
// array + afterAll loses data when Playwright restarts the worker after a failing test; and this lets an
// incremental re-run (e.g. one provider) update just that row while keeping the rest.
const ARTIFACT = path.resolve(__dirname, "..", "..", "..", "results", "e2e-model-comparison.json");
function appendResult(record: Record<string, unknown>): void {
  fs.mkdirSync(path.dirname(ARTIFACT), { recursive: true });
  let doc: { scenario: string; models: Record<string, unknown>[] } = { scenario: "S9", models: [] };
  try {
    doc = JSON.parse(fs.readFileSync(ARTIFACT, "utf8"));
  } catch {
    /* first write */
  }
  doc.models = (doc.models || []).filter((m) => m.provider !== record.provider);
  doc.models.push(record);
  fs.writeFileSync(ARTIFACT, JSON.stringify(doc, null, 2));
}

test.describe("S9 — multi-model full_ai comparison (paid, gated)", () => {
  test.skip(!LLM_ON, "set E2E_LLM=1 and provider key env vars to run the paid multi-model comparison");

  test.afterAll(() => {
    try {
      console.log(`\nS9 comparison → ${ARTIFACT}\n` + fs.readFileSync(ARTIFACT, "utf8"));
    } catch {
      /* nothing written (all skipped) */
    }
  });

  for (const p of PROVIDERS) {
    test(`${p.name}: full_ai run completes with an LLM-written report`, async ({ request }) => {
      const key = process.env[p.keyEnv];
      test.skip(!key, `no ${p.keyEnv} set — skipping ${p.name}`);

      const email = uniqueEmail(`s9_${p.name}`);
      await apiRegisterVerify(request, email);
      const token = await apiLogin(request, email);
      const authHdr = { Authorization: `Bearer ${token}` };

      // The runtime registry is keyed by the provider NAME; use a unique name (global registry, serial tests).
      const provName = `${p.name}-e2e-${Date.now()}`;
      const cr = await request.post(`${BACKEND}/api/ai/providers`, {
        headers: authHdr,
        data: { name: provName, provider_type: p.type, api_key: key },
      });
      expect(cr.ok(), `configure ${p.name} -> ${cr.status()}: ${await cr.text()}`).toBeTruthy();

      const model = pickModel(p);

      // A small full_ai run — the LLM Strategist proposes, the LLM Critic reviews, the LLM Reporter writes.
      // Hard-capped at max_eur so it cannot overrun. `provider` is the configured NAME (the registry key).
      const record: Record<string, unknown> = { provider: p.name, model };
      try {
        const goalId = await startRunApi(request, token, {
          goal_text: "a robust mean-reversion strategy on consumer staples",
          asset_pool: ["KO", "PG", "JNJ", "XOM"],
          strategy_families: ["mean_reversion"],
          agent_mode: "full_ai",
          provider: provName,
          model,
          max_runs: 5,
          max_seconds: 300,
          target_candidates: 1,
          rigor: "exploratory",
          enable_oos: false,
          mode: "robustness",
          seed: 3,
          max_eur: 1.0,
        });
        const finalState = await pollUntilTerminal(request, token, goalId, 360_000);
        const report = await getReport(request, token, goalId);
        const cands = await (await request.get(`${BACKEND}/api/research/runs/${goalId}/candidates`, { headers: authHdr })).json();
        const narrative = ((report?.sections as any[]) || []).map((s) => s.narrative || "").join(" ").trim();

        Object.assign(record, {
          status: finalState.status,
          agent_mode: finalState.agent_mode,
          model_id: finalState.model_id,
          used_eur: finalState.used_eur,
          cost_known: finalState.cost_known,
          leakage: finalState.leakage,
          candidates: Array.isArray(cands) ? cands.length : 0,
          report_available: !!report?.available,
          narrative_len: narrative.length,
        });
      } catch (e) {
        record.error = e instanceof Error ? e.message : String(e);
      }
      appendResult(record);
      console.log(`S9 ${p.name}:`, JSON.stringify(record));

      // The wiring must actually work for this provider (these fail loudly per-provider; the artifact still records all).
      expect(record.error, `${p.name} run threw`).toBeUndefined();
      expect(record.status, `${p.name} status`).not.toBe("failed");
      expect(record.agent_mode, `${p.name} ran in full_ai`).toBe("full_ai");
      expect(record.report_available, `${p.name} report available`).toBeTruthy();
      expect(Number(record.narrative_len), `${p.name} LLM narrative non-empty`).toBeGreaterThan(50);
      if (record.cost_known) {
        expect(Number(record.used_eur), `${p.name} used_eur > 0 (real spend)`).toBeGreaterThan(0);
      }
    });
  }

  // Pause/resume is only meaningful for a SLOW run — which full_ai is (LLM latency per trial). Uses the first
  // available provider; folds the control-loop coverage into a paid run rather than needing its own.
  test("pause / resume a live full_ai run", async ({ request }) => {
    const p = PROVIDERS.find((x) => process.env[x.keyEnv]);
    test.skip(!p, "no provider key set — skipping pause/resume");
    const email = uniqueEmail("s9_pause");
    await apiRegisterVerify(request, email);
    const token = await apiLogin(request, email);
    const authHdr = { Authorization: `Bearer ${token}` };
    const provName = `${p!.name}-pause-${Date.now()}`;
    await request.post(`${BACKEND}/api/ai/providers`, {
      headers: authHdr,
      data: { name: provName, provider_type: p!.type, api_key: process.env[p!.keyEnv] },
    });
    const model = pickModel(p!);
    const goalId = await startRunApi(request, token, {
      goal_text: "mean reversion on staples", asset_pool: ["KO", "PG", "JNJ", "XOM"],
      strategy_families: ["mean_reversion", "trend_following"], agent_mode: "full_ai", provider: provName,
      model, max_runs: 10, max_seconds: 360, target_candidates: 9, rigor: "exploratory",
      enable_oos: false, mode: "robustness", seed: 3, max_eur: 1.0,
    });

    await request.post(`${BACKEND}/api/research/runs/${goalId}/pause`, { headers: authHdr });
    await expect
      .poll(async () => (await (await request.get(`${BACKEND}/api/research/runs/${goalId}/state`, { headers: authHdr })).json()).status, { timeout: 60_000 })
      .toBe("paused");
    await request.post(`${BACKEND}/api/research/runs/${goalId}/resume`, { headers: authHdr });
    await expect
      .poll(async () => (await (await request.get(`${BACKEND}/api/research/runs/${goalId}/state`, { headers: authHdr })).json()).status, { timeout: 30_000 })
      .toBe("running");
    await request.post(`${BACKEND}/api/research/runs/${goalId}/stop`, { headers: authHdr }); // cleanup
  });
});
