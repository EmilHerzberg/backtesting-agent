import { expect, test } from "@playwright/test";
import { bootstrapLoggedIn } from "../helpers/auth";

// S2 — the start-run flow through the real UI: fill a goal → Preview (which must show the AGENT'S interpretation
// of the goal, the recently-fixed gap) → Launch → land on the run console. Covers the preview wiring + POST /runs.
test.describe("S2 — start-run preview + launch (UI)", () => {
  test("preview shows the agent's interpretation, then launches a run", async ({ page, context, request }) => {
    await bootstrapLoggedIn(context, request);

    await page.goto("/dashboard/research/new");
    await page.getByPlaceholder(/robust mean-reversion/i).fill("trend following on AAPL");

    // rule_based is the default AI mode; AAPL + two families are the defaults → Preview is enabled.
    await page.getByRole("button", { name: /Preview scope/i }).click();

    // The preview stage must render the BACKEND's interpretation (the fix): the "how the agent read your goal"
    // card with a symbol pool + an interpreted scope — not merely the user's own echoed input.
    await expect(page.getByText(/How the agent read your goal/i)).toBeVisible();
    await expect(page.getByText(/Symbol pool/i)).toBeVisible();
    await expect(page.getByText(/Interpreted scope/i)).toBeVisible();

    // Launch → navigate to the live run console.
    await page.getByRole("button", { name: /^Start run$/i }).click();
    await expect(page).toHaveURL(/\/dashboard\/research\/runs\/[^/]+$/);
  });
});
