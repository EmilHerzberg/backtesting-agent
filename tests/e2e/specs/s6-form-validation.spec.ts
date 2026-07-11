import { expect, test } from "@playwright/test";
import { bootstrapLoggedIn } from "../helpers/auth";

// S6 — form validation: in regime-fit mode an invalid window (start ≥ end) must block launch and show a
// message; a valid window re-enables it. Covers the client-side guard before a bad config can reach the API.
test.describe("S6 — start-run form validation", () => {
  test("regime window start ≥ end blocks Preview; a valid window re-enables it", async ({
    page,
    context,
    request,
  }) => {
    await bootstrapLoggedIn(context, request);
    await page.goto("/dashboard/research/new");
    await page.getByPlaceholder(/robust mean-reversion/i).fill("regime validation test");

    // switch to regime-fit mode → the window pickers appear
    await page.getByRole("button", { name: /Regime-fit/i }).click();
    const dates = page.locator('input[type="date"]');
    await expect(dates).toHaveCount(2);

    // invalid: start AFTER end → Preview disabled
    await dates.nth(0).fill("2022-01-01");
    await dates.nth(1).fill("2020-01-01");
    const preview = page.getByRole("button", { name: /Preview scope/i });
    await expect(preview).toBeDisabled();

    // fix the window → Preview enabled
    await dates.nth(1).fill("2023-01-01");
    await expect(preview).toBeEnabled();
  });
});
