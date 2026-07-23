import { expect, test } from "@playwright/test";
import { BACKEND, bootstrapLoggedIn } from "../helpers/auth";
import { getReport, pollUntilTerminal, startRunApi } from "../helpers/run";

// S10 — the coverage-v2 chain, live through the REAL UI (Playwright) + API:
//   Run A (UI-driven, €0 rule_based): the new form knobs (coverage memory + campaign honesty
//     correction + advisory stage-1 + quality-floor slider) POST the right payload; the MON1
//     canary event fires and the MON3 amber banner renders on the run console; the run completes
//     with coverage telemetry in the report.
//   Run B (API, same user): cross-run accumulation — the persisted coverage grows, proving the
//     campaign memory (and thus the N-wire's input) really spans runs.
// The paid LLM leg lives in s11 (gated on E2E_LLM=1 + a provider key), mirroring S9.

const COVERAGE_RUN = {
  goal_text: "robust mean-reversion on consumer staples",
  asset_pool: ["KO", "PG"],
  strategy_families: ["mean_reversion"],
  rigor: "exploratory",
  enable_oos: true,
  seed: 7,
  max_runs: 25,
  max_seconds: 240,
  target_candidates: 1,
  agent_mode: "rule_based",
  provider: null as string | null,
  model: null as string | null,
  mode: "robustness",
  window_start: null as string | null,
  window_end: null as string | null,
  coverage_memory: true,
  coverage_dsr: true,
  soft_dsr: true,
  oos_min_sharpe: 0.8,
};

function coverageOf(report: Record<string, any> | null): Record<string, any> | null {
  // The report API serializes sections as a LIST; coverage telemetry lives in Strategy Identity.
  const sec = (report?.sections as Array<Record<string, any>> | undefined)?.find(
    (s) => /strategy identity/i.test(String(s.title || "")),
  );
  const c = sec?.numeric_fields?.coverage;
  return c && typeof c === "object" ? c : null;
}

test.describe("S10 — coverage-v2 end-to-end (UI + cross-run)", () => {
  test("run A: UI knobs → payload → canary banner → completion with coverage telemetry", async ({
    page,
    context,
    request,
  }) => {
    const { token } = await bootstrapLoggedIn(context, request);

    await page.goto("/dashboard/research/new");
    await page.getByPlaceholder(/robust mean-reversion/i).fill(COVERAGE_RUN.goal_text);

    // The new knobs (Track 5/6/7 UI) live under the collapsed Advanced section.
    await page.getByRole("button", { name: /Advanced \(raw caps/i }).click();
    await page
      .locator("label", { hasText: "remember which parameter regions" })
      .locator("input[type=checkbox]")
      .check();
    await page
      .locator("label", { hasText: "Campaign honesty correction" })
      .locator("input[type=checkbox]")
      .check();
    await page.locator("label", { hasText: "Advisory stage-1" }).locator("input[type=checkbox]").check();
    await page.locator("input[type=range]").fill("0.8");

    await page.getByRole("button", { name: /Preview scope/i }).click();
    await expect(page.getByText(/How the agent read your goal/i)).toBeVisible();

    // Assert the POST body carries the new flags — the UI→API contract, checked at the wire.
    const [req] = await Promise.all([
      page.waitForRequest((r) => r.url().includes("/api/research/runs") && r.method() === "POST"),
      page.getByRole("button", { name: /^Start run$/i }).click(),
    ]);
    const body = req.postDataJSON() as Record<string, unknown>;
    expect(body.coverage_memory).toBe(true);
    expect(body.coverage_dsr).toBe(true);
    expect(body.soft_dsr).toBe(true);
    expect(body.oos_min_sharpe).toBe(0.8);

    await expect(page).toHaveURL(/\/dashboard\/research\/runs\/[^/]+$/);
    const goalId = page.url().split("/").pop() as string;

    // MON3: the power-canary banner — deterministic here (the canary always proves vacuity at
    // this operating point), so the amber banner MUST appear on the live console.
    await expect(page.getByText(/Power canary/i)).toBeVisible({ timeout: 30_000 });

    const state = await pollUntilTerminal(request, token, goalId);
    expect(state?.status).toBe("completed");

    // The MON1 evidence is a first-class event in the persisted stream.
    const evRes = await request.get(`${BACKEND}/api/research/runs/${goalId}/events`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(evRes.ok()).toBeTruthy();
    const events = (await evRes.json()) as Array<Record<string, any>>;
    const canary = events.find((e) => (e.raw_kind || e.kind) === "mon1_canary");
    expect(canary, "mon1_canary event persisted").toBeTruthy();
    expect(canary?.detail?.vacuous).toBe(true);
    expect(canary?.detail?.canary_healthy).toBe(true);

    // Coverage telemetry reaches the report (v3 grid identity + visited cells).
    const report = await getReport(request, token, goalId);
    const cov = coverageOf(report);
    expect(cov, "coverage telemetry in report").toBeTruthy();
    expect(cov?.grid_version).toBe("v3");
    expect(cov?.cells_visited).toBeGreaterThan(0);

    // Stash for run B (worker-scoped state is fine: fullyParallel=false, workers=1).
    process.env.__S10_TOKEN = token;
    process.env.__S10_VISITED = String(cov?.cells_visited ?? 0);
  });

  test("run B: the campaign memory spans runs — visited cells accumulate", async ({ request }) => {
    const token = process.env.__S10_TOKEN as string;
    expect(token, "run A must have completed first (serial suite)").toBeTruthy();
    const visitedA = Number(process.env.__S10_VISITED || 0);

    const goalId = await startRunApi(request, token, { ...COVERAGE_RUN, seed: 8 });
    const state = await pollUntilTerminal(request, token, goalId);
    expect(state?.status).toBe("completed");

    const report = await getReport(request, token, goalId);
    const cov = coverageOf(report);
    expect(cov?.grid_version).toBe("v3");
    // Cross-run accumulation: run B's cumulative visited set STRICTLY exceeds run A's — the
    // persisted campaign memory (the N-wire's input) genuinely spans runs.
    expect(cov?.cells_visited).toBeGreaterThan(visitedA);
  });
});
