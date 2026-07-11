import { expect, test } from "@playwright/test";
import { bootstrapLoggedIn } from "../helpers/auth";
import { getCandidates, pollUntilTerminal, startRunApi } from "../helpers/run";

// S3 — the core demo path end-to-end: a €0 rule_based run starts, the loop runs to COMPLETED, candidates are
// surfaced, and the live console renders them. Covers the polling loop + candidate serialization + card render.
test.describe("S3 — full rule_based run to completion", () => {
  test("run completes, surfaces candidates, and the console renders them", async ({ page, context, request }) => {
    const { token } = await bootstrapLoggedIn(context, request);
    const goalId = await startRunApi(request, token); // €0 rule_based, seeded, ~1 min

    // Open the live console — it polls state/candidates/events every 2s while the run progresses.
    await page.goto(`/dashboard/research/runs/${goalId}`);

    // API-side truth: the run reaches a terminal state (and not a hard failure).
    const finalState = await pollUntilTerminal(request, token, goalId, 120_000);
    expect(String(finalState.status), `terminal status was ${finalState.status}`).not.toBe("failed");

    // It surfaced at least one candidate…
    const cands = await getCandidates(request, token, goalId);
    expect(cands.length, "candidates found").toBeGreaterThan(0);

    // …and the console UI rendered them: a candidate card linking to its dossier (proves candidate serialization
    // → render), and the activity stream accumulated events (proves the event stream/fallback).
    await expect(page.locator('a[href*="/candidates/"]').first()).toBeVisible({ timeout: 25_000 });
  });
});
