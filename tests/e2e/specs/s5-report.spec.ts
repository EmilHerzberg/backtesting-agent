import { expect, test } from "@playwright/test";
import { bootstrapLoggedIn } from "../helpers/auth";
import { pollUntilTerminal, startRunApi } from "../helpers/run";

// S5 — the final report: after a run completes the Reporter's FinalReport becomes available and the page (which
// polls until available) renders its sections. Covers useReport's poll-until-available termination + render.
test.describe("S5 — final report", () => {
  test("report becomes available and renders sections", async ({ page, context, request }) => {
    const { token } = await bootstrapLoggedIn(context, request);
    const goalId = await startRunApi(request, token);
    await pollUntilTerminal(request, token, goalId);

    await page.goto(`/dashboard/research/runs/${goalId}/report`);
    await expect(page.getByRole("heading", { name: /Research Report/i })).toBeVisible();

    // The page polls /report every 2s until available. When it renders, the honest "falsification report"
    // banner appears (only shown for an AVAILABLE report), which proves the poll-until-available + render path.
    await expect(page.getByText(/falsification report/i)).toBeVisible({ timeout: 30_000 });
  });
});
