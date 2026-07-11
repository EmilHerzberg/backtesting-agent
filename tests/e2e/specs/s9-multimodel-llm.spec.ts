import fs from "fs";
import path from "path";
import { APIRequestContext, expect, test } from "@playwright/test";
import { BACKEND, apiLogin, apiRegisterVerify, uniqueEmail } from "../helpers/auth";
import { getReport, pollUntilTerminal, startRunApi } from "../helpers/run";

// S9 — PAID, GATED. Runs the SAME small full_ai scenario across each configured provider (Gemini / Claude /
// ChatGPT / DeepSeek) and records the outcome, so a provider that crashes the LLM-agent wiring, returns
// unparseable output, produces an empty report, or mis-reports leakage shows up in a side-by-side artifact.
//
// Gated: only runs with E2E_LLM=1 AND the provider's key env var set. Never runs on CI / unattended.
// Keys: E2E_OPENAI_KEY, E2E_ANTHROPIC_KEY (Claude), E2E_GEMINI_KEY, E2E_DEEPSEEK_KEY.

const LLM_ON = process.env.E2E_LLM === "1";

const PROVIDERS = [
  { name: "openai", type: "openai", keyEnv: "E2E_OPENAI_KEY", modelHint: /gpt-4o-mini|mini|gpt-4o/i },
  { name: "claude", type: "anthropic", keyEnv: "E2E_ANTHROPIC_KEY", modelHint: /haiku|claude/i },
  { name: "gemini", type: "gemini", keyEnv: "E2E_GEMINI_KEY", modelHint: /flash|gemini/i },
  { name: "deepseek", type: "deepseek", keyEnv: "E2E_DEEPSEEK_KEY", modelHint: /deepseek-chat|chat/i },
];

const comparison: Record<string, unknown>[] = [];

async function pickModel(request: APIRequestContext, token: string, type: string, hint: RegExp): Promise<string> {
  const res = await request.get(`${BACKEND}/api/ai/models`, { headers: { Authorization: `Bearer ${token}` } });
  const models: any[] = res.ok() ? await res.json() : [];
  const forType = models.filter((m) => String(m.provider || "").toLowerCase().includes(type));
  expect(forType.length, `provider ${type} exposes at least one model`).toBeGreaterThan(0);
  const chosen = forType.find((m) => hint.test(String(m.model_id || m.display_name || ""))) || forType[0];
  return String(chosen.model_id);
}

test.describe("S9 — multi-model full_ai comparison (paid, gated)", () => {
  test.skip(!LLM_ON, "set E2E_LLM=1 and provider key env vars to run the paid multi-model comparison");

  test.afterAll(async () => {
    const out = path.resolve(__dirname, "..", "..", "..", "results", "e2e-model-comparison.json");
    fs.mkdirSync(path.dirname(out), { recursive: true });
    fs.writeFileSync(out, JSON.stringify({ scenario: "S9", models: comparison }, null, 2));
    console.log(`\nS9 comparison → ${out}\n` + JSON.stringify(comparison, null, 2));
  });

  for (const p of PROVIDERS) {
    test(`${p.name}: full_ai run completes with an LLM-written report`, async ({ request }) => {
      const key = process.env[p.keyEnv];
      test.skip(!key, `no ${p.keyEnv} set — skipping ${p.name}`);

      const email = uniqueEmail(`s9_${p.name}`);
      await apiRegisterVerify(request, email);
      const token = await apiLogin(request, email);
      const authHdr = { Authorization: `Bearer ${token}` };

      const cr = await request.post(`${BACKEND}/api/ai/providers`, {
        headers: authHdr,
        data: { name: `${p.name}-e2e`, provider_type: p.type, api_key: key },
      });
      expect(cr.ok(), `configure ${p.name} -> ${cr.status()}: ${await cr.text()}`).toBeTruthy();

      const model = await pickModel(request, token, p.type, p.modelHint);

      // A small full_ai run — the LLM Strategist proposes, the LLM Critic reviews, the LLM Reporter writes.
      // Hard-capped at max_eur so it cannot overrun.
      const record: Record<string, unknown> = { provider: p.name, model };
      try {
        const goalId = await startRunApi(request, token, {
          goal_text: "a robust mean-reversion strategy on consumer staples",
          asset_pool: ["KO", "PG", "JNJ", "XOM"],
          strategy_families: ["mean_reversion"],
          agent_mode: "full_ai",
          provider: p.type,
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
      comparison.push(record);
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
    await request.post(`${BACKEND}/api/ai/providers`, {
      headers: authHdr,
      data: { name: `${p!.name}-pause`, provider_type: p!.type, api_key: process.env[p!.keyEnv] },
    });
    const model = await pickModel(request, token, p!.type, p!.modelHint);
    const goalId = await startRunApi(request, token, {
      goal_text: "mean reversion on staples", asset_pool: ["KO", "PG", "JNJ", "XOM"],
      strategy_families: ["mean_reversion", "trend_following"], agent_mode: "full_ai", provider: p!.type,
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
