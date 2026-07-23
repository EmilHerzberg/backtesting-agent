import { expect, test } from "@playwright/test";
import { BACKEND, apiLogin, apiRegisterVerify, uniqueEmail } from "../helpers/auth";
import { getReport, pollUntilTerminal, startRunApi } from "../helpers/run";

// S11 — PAID, GATED (mirrors S9's gating): the coverage-v2 chain under a REAL LLM.
// One cheap reasoning provider, full_ai, with coverage memory + campaign correction + advisory
// stage-1 + quality floor all ON — verifying the LLM strategist coexists with the coverage
// nudge, the canary event fires, the run completes, and cost stays hard-capped (max_eur 1.0).
//
// Gate: E2E_LLM=1 AND one of the keys below. Never runs unattended.

const LLM_ON = process.env.E2E_LLM === "1";
const PROVIDERS = [
  { name: "deepseek", type: "deepseek", keyEnv: "E2E_DEEPSEEK_KEY", model: "deepseek-reasoner" },
  { name: "byteplus", type: "byteplus", keyEnv: "E2E_BYTEPLUS_KEY", model: "seed-2-0-pro-260328" },
  { name: "zhipu", type: "zhipu", keyEnv: "E2E_ZAI_KEY", model: "glm-5" },
];

test.describe("S11 — coverage-v2 under a real LLM (paid, gated)", () => {
  test("full_ai + coverage-v2 flags: completes, canary fires, cost capped", async ({ request }) => {
    const prov = PROVIDERS.find((p) => process.env[p.keyEnv]);
    test.skip(!LLM_ON, "E2E_LLM not set — paid leg skipped");
    test.skip(!prov, "no provider key set (E2E_DEEPSEEK_KEY / E2E_BYTEPLUS_KEY / E2E_ZAI_KEY)");
    const p = prov!;

    const email = uniqueEmail("s11");
    await apiRegisterVerify(request, email);
    const token = await apiLogin(request, email);
    const authHdr = { Authorization: `Bearer ${token}` };

    const provName = `${p.name}-s11-${Date.now()}`;
    const cr = await request.post(`${BACKEND}/api/ai/providers`, {
      headers: authHdr,
      data: { name: provName, provider_type: p.type, api_key: process.env[p.keyEnv] },
    });
    expect(cr.ok(), `configure ${p.name} -> ${cr.status()}`).toBeTruthy();

    const goalId = await startRunApi(request, token, {
      goal_text: "a robust mean-reversion strategy on consumer staples",
      asset_pool: ["KO", "PG"],
      strategy_families: ["mean_reversion"],
      agent_mode: "full_ai",
      provider: provName,
      model: p.model,
      max_runs: 6,
      max_seconds: 300,
      target_candidates: 1,
      rigor: "exploratory",
      enable_oos: true,
      mode: "robustness",
      seed: 11,
      max_eur: 1.0,
      coverage_memory: true,
      coverage_dsr: true,
      soft_dsr: true,
      oos_min_sharpe: 0.8,
    });

    const finalState = await pollUntilTerminal(request, token, goalId, 420_000);
    expect(finalState?.status, "run reached a clean terminal state").toBe("completed");

    // the canary evidence event exists alongside the LLM's own events
    const events = (await (
      await request.get(`${BACKEND}/api/research/runs/${goalId}/events`, { headers: authHdr })
    ).json()) as Array<Record<string, any>>;
    const canary = events.find((e) => (e.raw_kind || e.kind) === "mon1_canary");
    expect(canary?.detail?.vacuous).toBe(true);

    // coverage telemetry present; cost accounted and inside the hard cap
    const report = await getReport(request, token, goalId);
    const cov = ((report?.sections as Array<Record<string, any>> | undefined) || []).find((s) =>
      /strategy identity/i.test(String(s.title || "")),
    )?.numeric_fields?.coverage;
    expect(cov?.grid_version).toBe("v3");
    expect(Number(finalState?.used_eur ?? 0)).toBeLessThanOrEqual(1.0);
    console.log(
      `S11 ${p.name}: status=${finalState?.status} used_eur=${finalState?.used_eur} ` +
        `cost_known=${finalState?.cost_known} visited=${cov?.cells_visited} leakage=${JSON.stringify(finalState?.leakage)}`,
    );
  });
});
