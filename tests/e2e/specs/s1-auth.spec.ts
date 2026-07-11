import { expect, test } from "@playwright/test";
import { TEST_PASSWORD, apiRegisterVerify, uiLogin, uniqueEmail } from "../helpers/auth";

// S1 — auth: a verified user logs in through the real form and lands on the authenticated dashboard, and a
// protected API call (proxied through the frontend) succeeds. Covers the login UI + JWT-on-requests seam.
test.describe("S1 — authentication", () => {
  test("verified user logs in and reaches the dashboard", async ({ page, request }) => {
    const email = uniqueEmail();
    await apiRegisterVerify(request, email); // fresh verified account (no real email needed)

    await uiLogin(page, email, TEST_PASSWORD); // drives the real login form

    // On the authenticated app the research home renders (AuthGuard would bounce an unauthed user to "/").
    await page.goto("/dashboard/research");
    await expect(page).toHaveURL(/\/dashboard\/research$/);
    await expect(page.getByRole("heading", { name: "Research" })).toBeVisible();
    await expect(page.getByRole("link", { name: /New Run/i })).toBeVisible();
  });

  test("wrong password does not log in", async ({ page, request }) => {
    const email = uniqueEmail();
    await apiRegisterVerify(request, email);
    await page.goto("/");
    await page.locator('input[type="email"]').first().fill(email);
    await page.locator('input[type="password"]').first().fill("WrongPassword!1");
    await page.locator('button[type="submit"]').first().click();
    // stays on the login form (email field still present) and shows the error message.
    await expect(page.locator('input[type="email"]').first()).toBeVisible();
    await expect(page.locator(".text-red-400").first()).toBeVisible();
  });
});
