import { APIRequestContext, BrowserContext, Page, expect } from "@playwright/test";

// The backend is reached directly for API-level setup (register/verify/login); the browser drives the
// frontend, which proxies /api → backend. Register returns the verify token inline (no real email in test).
export const BACKEND = process.env.E2E_BACKEND_URL || "http://localhost:8000";
export const TEST_PASSWORD = "E2eTest123!";

export function uniqueEmail(prefix = "e2e"): string {
  return `${prefix}_${Date.now()}_${Math.floor(Math.random() * 1e6)}@test.local`;
}

/** Register a fresh user and verify it via the token returned inline in the register response. */
export async function apiRegisterVerify(
  request: APIRequestContext,
  email: string,
  password = TEST_PASSWORD,
): Promise<void> {
  const reg = await request.post(`${BACKEND}/api/auth/register`, { data: { email, password } });
  expect(reg.ok(), `register ${email} -> ${reg.status()}`).toBeTruthy();
  const body = await reg.json();
  const token = String(body.verify_url || "").split("/").pop();
  expect(token, "verify token present in register response").toBeTruthy();
  const ver = await request.get(`${BACKEND}/api/auth/verify/${token}`);
  expect(ver.ok(), `verify -> ${ver.status()}`).toBeTruthy();
}

/** Log in via the API; returns the JWT. */
export async function apiLogin(
  request: APIRequestContext,
  email: string,
  password = TEST_PASSWORD,
): Promise<string> {
  const res = await request.post(`${BACKEND}/api/auth/login`, { data: { email, password } });
  expect(res.ok(), `login -> ${res.status()}`).toBeTruthy();
  const token = String((await res.json()).access_token || "");
  expect(token, "jwt present").toBeTruthy();
  return token;
}

/** Fast path for tests that just need to BE logged in: register+verify+login via API, then inject the JWT
 *  into localStorage so the SPA treats the browser as authenticated on first navigation. */
export async function bootstrapLoggedIn(
  context: BrowserContext,
  request: APIRequestContext,
): Promise<{ email: string; token: string }> {
  const email = uniqueEmail();
  await apiRegisterVerify(request, email);
  const token = await apiLogin(request, email);
  await context.addInitScript((t) => {
    try {
      window.localStorage.setItem("token", t as string);
    } catch {
      /* ignore */
    }
  }, token);
  return { email, token };
}

/** Drive the real login FORM (for the auth scenario). Ends on the authenticated dashboard. */
export async function uiLogin(page: Page, email: string, password = TEST_PASSWORD): Promise<void> {
  await page.goto("/");
  const emailInput = page.locator('input[type="email"]').first();
  await emailInput.waitFor({ state: "visible" });
  await emailInput.fill(email);
  await page.locator('input[type="password"]').first().fill(password);
  await page.locator('button[type="submit"]').first().click();
  // login swaps the form for the dashboard (the email field disappears).
  await expect(page.locator('input[type="email"]')).toHaveCount(0, { timeout: 20_000 });
}
