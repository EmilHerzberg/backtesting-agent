// E2E test for DATA-PROV-S1 (ATS-1586..1591) against the live Contabo deploy.
//
// Verifies the full Setup-Page flow:
//   1. Login
//   2. "Datenquellen API-Keys" section is visible
//   3. Open the add form, pick alpha_vantage, enter a key, save
//   4. The new key appears in the list with a masked value
//   5. Test button calls the backend (we stub the AV call via env-bypass)
//   6. "Datenquellen für Backtesting" overview shows Alpha Vantage with
//      the "via Frontend" badge
//   7. Delete removes the row
//
// To exercise the REAL Alpha Vantage call, pass E2E_AV_KEY=<real-key> in
// the env. Without it, the test enters a fake key and just verifies the
// UI plumbing — which is what we want for routine CI runs.
//
// Run: cd tests/e2e && node data-provider-keys.spec.js
// Override target: E2E_BASE_URL=https://my-host node data-provider-keys.spec.js

const { chromium } = require("playwright");

const BASE_URL = process.env.E2E_BASE_URL || "http://109.199.123.190";
const EMAIL = process.env.E2E_EMAIL || "qa-test@v3.test";
const PASSWORD = process.env.E2E_PASSWORD || "QaTest123!";
const AV_KEY = process.env.E2E_AV_KEY || "DEMO-FAKE-KEY-FOR-E2E-PLUMBING-1234";
const HAS_REAL_KEY = !!process.env.E2E_AV_KEY;

function log(step, msg) {
  console.log(`[${step}] ${msg}`);
}
function fail(msg) {
  throw new Error(`ASSERT FAILED: ${msg}`);
}

async function login(page) {
  log("LOGIN", `Navigating to ${BASE_URL}/`);
  await page.goto(BASE_URL + "/", { waitUntil: "domcontentloaded" });
  await page.waitForSelector('input[type="email"]', { timeout: 15000 });
  await page.fill('input[type="email"]', EMAIL);
  await page.fill('input[type="password"]', PASSWORD);
  await Promise.all([
    page.waitForLoadState("networkidle"),
    page.click('button[type="submit"]'),
  ]);
  await page
    .waitForFunction(() => !document.querySelector('input[type="email"]'), null, {
      timeout: 15000,
    })
    .catch(() => fail("login did not complete"));
  log("LOGIN", "OK");
}

async function step1_openSetupPage(page) {
  log("STEP1", "Navigating to /setup");
  await page.goto(BASE_URL + "/setup", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("text=Datenquellen API-Keys", { timeout: 15000 });
  log("STEP1", "OK — Datenquellen API-Keys section visible");
}

async function step2_cleanupExistingAvKey(page) {
  // If qa-test already has an alpha_vantage key from a prior test, remove it.
  log("STEP2", "Cleaning up any prior alpha_vantage key");
  // Listen for the confirm dialog and accept it
  page.once("dialog", (d) => d.accept().catch(() => {}));
  // The list rows show "Alpha Vantage"; locate any with an Entfernen button
  const rows = await page
    .locator("text=Alpha Vantage")
    .locator("xpath=ancestor::div[contains(@class, 'rounded-lg')][1]")
    .all();
  for (const row of rows) {
    const del = row.locator('button:has-text("Entfernen")');
    if (await del.count() > 0) {
      page.once("dialog", (d) => d.accept().catch(() => {}));
      await del.first().click().catch(() => {});
      // small wait for the list refresh
      await page.waitForTimeout(800);
    }
  }
  log("STEP2", "OK");
}

async function step3_addAlphaVantageKey(page) {
  log("STEP3", "Adding alpha_vantage key via the form");
  await page.click('button:has-text("+ API-Key")');
  // Wait for the password input to appear
  await page.waitForSelector('input[type="password"][placeholder="API Key"]', {
    timeout: 5000,
  });
  // Provider dropdown should default to alpha_vantage already; set explicitly
  // by value to avoid label/regex flakiness across Playwright versions.
  await page.selectOption("select", "alpha_vantage");
  await page.fill('input[type="password"][placeholder="API Key"]', AV_KEY);
  await Promise.all([
    page.waitForResponse(
      (r) =>
        r.url().includes("/api/data/providers") && r.request().method() === "POST",
      { timeout: 15000 },
    ),
    page.click('button:has-text("Speichern")'),
  ]);
  log("STEP3", "OK — POST request fired");
}

async function step4_verifyListEntry(page) {
  log("STEP4", "Verifying Alpha Vantage entry appears in the keys list");
  // The entry row has a "Testen" button next to the masked key.
  const row = page
    .locator("text=Alpha Vantage")
    .locator("xpath=ancestor::div[contains(@class, 'bg-gray-800')][1]");
  await row.waitFor({ state: "visible", timeout: 10000 });
  const masked = await row.locator(".font-mono").first().textContent();
  if (!masked || masked.includes(AV_KEY)) {
    fail(`Key not masked or missing — got '${masked}'`);
  }
  log("STEP4", `OK — masked key shown as '${masked.trim()}'`);
}

async function step5_clickTestButton(page) {
  log("STEP5", "Clicking Test button");
  const row = page
    .locator("text=Alpha Vantage")
    .locator("xpath=ancestor::div[contains(@class, 'bg-gray-800')][1]");
  // Wait for POST /test response and capture the body
  const respPromise = page.waitForResponse(
    (r) => r.url().includes("/test") && r.request().method() === "POST",
    { timeout: 30000 },
  );
  await row.locator('button:has-text("Testen")').click();
  const resp = await respPromise;
  const body = await resp.json();
  if (HAS_REAL_KEY) {
    if (!body.success) fail(`Real-key test failed: ${body.message}`);
    log("STEP5", `OK — REAL Alpha Vantage call succeeded: ${body.message}`);
  } else {
    // Fake key — backend should report an error from Alpha Vantage about the
    // invalid key. We accept either success=false (most likely) or
    // success=true if AV happens to soft-pass demo keys.
    log(
      "STEP5",
      `OK — POST /test returned success=${body.success}: ${body.message}`,
    );
  }
}

async function step6_verifyOverviewBadge(page) {
  log("STEP6", "Checking overview shows 'via Frontend' badge for Alpha Vantage");
  const overview = page
    .locator("text=Datenquellen fuer Backtesting")
    .locator("xpath=ancestor::section[1]");
  await overview.waitFor({ timeout: 10000 });
  const avRow = overview
    .locator("text=Alpha Vantage")
    .locator("xpath=ancestor::div[contains(@class, 'rounded-lg')][1]");
  await avRow.waitFor({ timeout: 10000 });
  const html = await avRow.innerHTML();
  if (!html.includes("via Frontend")) {
    fail(`Expected 'via Frontend' badge in overview row HTML — got: ${html.slice(0, 600)}`);
  }
  log("STEP6", "OK — 'via Frontend' badge present");
}

async function step7_deleteKey(page) {
  log("STEP7", "Deleting the Alpha Vantage key");
  page.once("dialog", (d) => d.accept().catch(() => {}));
  const row = page
    .locator("text=Alpha Vantage")
    .locator("xpath=ancestor::div[contains(@class, 'bg-gray-800')][1]")
    .first();
  await Promise.all([
    page.waitForResponse(
      (r) =>
        r.url().match(/\/api\/data\/providers\/\d+$/) && r.request().method() === "DELETE",
      { timeout: 15000 },
    ),
    row.locator('button:has-text("Entfernen")').click(),
  ]);
  // Reload to be sure
  await page.reload({ waitUntil: "domcontentloaded" });
  // After delete, the key list shows the empty-state text
  const empty = await page
    .locator("text=Noch keine API-Keys hinterlegt")
    .first()
    .isVisible({ timeout: 5000 })
    .catch(() => false);
  if (!empty) {
    // Allow for the case where the user has other (non-AV) keys
    const stillThere = await page
      .locator("section")
      .filter({ hasText: "Datenquellen API-Keys" })
      .locator("text=Alpha Vantage")
      .count();
    if (stillThere > 0) fail("Alpha Vantage entry still present after delete");
  }
  log("STEP7", "OK — Alpha Vantage entry removed");
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1366, height: 900 },
  });
  const page = await ctx.newPage();
  page.on("pageerror", (err) => console.error("[pageerror]", err.message));

  const t0 = Date.now();
  try {
    await login(page);
    await step1_openSetupPage(page);
    await step2_cleanupExistingAvKey(page);
    await step3_addAlphaVantageKey(page);
    await step4_verifyListEntry(page);
    await step5_clickTestButton(page);
    await step6_verifyOverviewBadge(page);
    await step7_deleteKey(page);
    const ms = Date.now() - t0;
    console.log(`\n=== ALL STEPS PASSED in ${(ms / 1000).toFixed(1)}s ===`);
    if (HAS_REAL_KEY) {
      console.log("(real Alpha Vantage call was used — 1 quota burned)");
    } else {
      console.log("(no E2E_AV_KEY — only verified UI plumbing, not real AV call)");
    }
  } catch (e) {
    console.error("\n=== TEST FAILED ===");
    console.error(e.message);
    try {
      const path = require("path");
      const out = path.join(__dirname, "data-provider-failure.png");
      await page.screenshot({ path: out, fullPage: true });
      console.error("screenshot:", out);
    } catch (_) {
      /* ignore */
    }
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
