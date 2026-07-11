import { expect, test } from "@playwright/test";
import { bootstrapLoggedIn } from "../helpers/auth";
import { getCandidates, pollUntilTerminal, startRunApi } from "../helpers/run";

// S4 — the candidate dossier: for a REAL candidate from a completed run, the trust-first dossier headlines the
// OOS verdict and lists the quality gates (4 parallel fetches: gates/critique/oos/artifacts). Covers the dossier
// waterfall + gate/verdict render.
test.describe("S4 — candidate dossier", () => {
  test("dossier headlines the OOS verdict and lists the gates for a real candidate", async ({
    page,
    context,
    request,
  }) => {
    const { token } = await bootstrapLoggedIn(context, request);
    const goalId = await startRunApi(request, token);
    await pollUntilTerminal(request, token, goalId);
    const cands = await getCandidates(request, token, goalId);
    expect(cands.length, "run produced a candidate").toBeGreaterThan(0);
    const hash = cands[0].strategy_hash as string;

    await page.goto(`/dashboard/research/runs/${goalId}/candidates/${hash}`);

    // trust-first: the OOS verdict is the headline (PENDING here — robustness run without the lockbox).
    await expect(page.getByText(/OOS (PENDING|PASS|FAIL|UNEVALUATED)/).first()).toBeVisible();
    // the quality-gate battery is listed (every candidate is scored by the activity gate, among others).
    await expect(page.getByText("minimum_activity").first()).toBeVisible();
  });
});
