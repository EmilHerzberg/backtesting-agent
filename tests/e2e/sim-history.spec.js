// E2E test for SIM-S7 (ATS-1582..1585) against the live Contabo deploy.
//
// Verifies:
//   1. /dashboard/simulation loads after login
//   2. Running a simulation persists it (URL gets ?trial=<id>)
//   3. "Letzte Simulationen" panel shows the new run
//   4. Clicking a row reloads the page with ?trial=<id> and prefills the form
//   5. /dashboard/simulation/history shows the saved run with filters working
//
// Run: node tests/e2e/sim-history.spec.js
// Env: E2E_BASE_URL  (default http://109.199.123.190)
//      E2E_EMAIL     (default qa-test@v3.test)
//      E2E_PASSWORD  (default QaTest123!)

const { chromium } = require("playwright");

const BASE_URL = process.env.E2E_BASE_URL || "http://109.199.123.190";
const EMAIL = process.env.E2E_EMAIL || "qa-test@v3.test";
const PASSWORD = process.env.E2E_PASSWORD || "QaTest123!";

function log(step, msg) {
  console.log(`[${step}] ${msg}`);
}

function fail(msg) {
  throw new Error(`ASSERT FAILED: ${msg}`);
}

async function login(page) {
  log("LOGIN", `Navigating to ${BASE_URL}/`);
  await page.goto(BASE_URL + "/", { waitUntil: "domcontentloaded" });
  // The login form uses native <input type=email/password>; wait for them.
  await page.waitForSelector('input[type="email"]', { timeout: 15000 });
  await page.fill('input[type="email"]', EMAIL);
  await page.fill('input[type="password"]', PASSWORD);
  // Click the visible submit button on the login form.
  await Promise.all([
    page.waitForLoadState("networkidle"),
    page.click('button[type="submit"]'),
  ]);
  // Login replaces the form with the dashboard. Wait until either:
  //  - the email input disappears (logged in), or
  //  - an error shows up.
  await page
    .waitForFunction(() => !document.querySelector('input[type="email"]'), null, {
      timeout: 15000,
    })
    .catch(async () => {
      const err = await page.locator(".text-red-400").first().textContent().catch(() => null);
      fail(`login did not complete (error on page: ${err})`);
    });
  log("LOGIN", "OK — logged in");
}

async function step1_openSimulationPage(page) {
  log("STEP1", "Navigating to /dashboard/simulation");
  await page.goto(BASE_URL + "/dashboard/simulation", {
    waitUntil: "domcontentloaded",
  });
  // The page H1 should read "Simulation".
  const h1 = await page.locator("h1").first().textContent();
  if (!h1 || !h1.toLowerCase().includes("simulation")) {
    fail(`H1 not 'Simulation' — got '${h1}'`);
  }
  log("STEP1", "OK — H1 contains 'Simulation'");
  // Recent panel header should be present (regardless of whether it has rows).
  const panelOk = await page
    .locator('text=Letzte Simulationen')
    .first()
    .isVisible({ timeout: 8000 })
    .catch(() => false);
  if (!panelOk) fail("'Letzte Simulationen' panel not visible");
  log("STEP1", "OK — 'Letzte Simulationen' panel visible");
}

async function step2_runSimulation(page) {
  log("STEP2", "Setting form fields and submitting Run");
  // Symbol: clear + type to avoid relying on default
  await page.fill('input[placeholder*="AAPL"]', "AAPL");
  // Strategy: use default (SMACrossover).
  // Submit:
  await page.click('button:has-text("Simulation starten")');
  // Wait for the URL to gain ?trial=<id> — that's the success signal.
  log("STEP2", "Waiting for ?trial=<id> in URL …");
  await page.waitForURL(/[?&]trial=\d+/, { timeout: 60000 });
  const url = new URL(page.url());
  const trialId = url.searchParams.get("trial");
  if (!trialId || !/^\d+$/.test(trialId)) fail(`trial query param missing/invalid: ${trialId}`);
  log("STEP2", `OK — URL now has trial=${trialId}`);
  // Result chart should render — recharts injects an <svg class="recharts-surface">
  await page.waitForSelector("svg.recharts-surface", { timeout: 15000 });
  log("STEP2", "OK — result chart rendered");
  return Number(trialId);
}

async function step3_recentPanelShowsRun(page, trialId) {
  log("STEP3", `Checking that Recent panel contains trial=${trialId}`);
  // Use a contains-selector — Link may not render exact href= equal-string.
  const linkSel = `a[href*="trial=${trialId}"]`;
  const found = await page
    .locator(linkSel)
    .first()
    .waitFor({ state: "visible", timeout: 15000 })
    .then(() => true)
    .catch(() => false);
  if (!found) {
    // Dump panel HTML for debugging
    const panelHtml = await page
      .locator("text=Letzte Simulationen")
      .first()
      .locator("xpath=ancestor::section[1]")
      .innerHTML()
      .catch(() => "(panel not found)");
    console.error("[DEBUG] Panel HTML:\n" + panelHtml.slice(0, 2000));
    fail(`Recent panel does not contain link to trial=${trialId}`);
  }
  log("STEP3", "OK — Recent panel shows the new run");
}

async function step4_clickRowPrefillsForm(page, trialId) {
  log("STEP4", "Navigating away then clicking the recent row to verify prefill");
  // Navigate to a clean simulation page (no ?trial)
  await page.goto(BASE_URL + "/dashboard/simulation", { waitUntil: "domcontentloaded" });
  // Wait for the panel to load
  const linkSel = `a[href="/dashboard/simulation?trial=${trialId}"]`;
  await page.waitForSelector(linkSel, { timeout: 15000 });
  // Click the link
  await Promise.all([
    page.waitForURL(new RegExp(`[?&]trial=${trialId}`), { timeout: 15000 }),
    page.locator(linkSel).first().click(),
  ]);
  // Form must be prefilled; chart should render again from the saved data
  await page.waitForSelector("svg.recharts-surface", { timeout: 15000 });
  // Check symbol input still says AAPL
  const sym = await page.inputValue('input[placeholder*="AAPL"]');
  if (sym !== "AAPL") fail(`symbol input not prefilled — got '${sym}'`);
  log("STEP4", "OK — clicking row reloaded saved sim and form prefilled (symbol=AAPL)");
}

async function step5_historyPage(page, trialId) {
  log("STEP5", "Opening /dashboard/simulation/history");
  await page.goto(BASE_URL + "/dashboard/simulation/history", {
    waitUntil: "domcontentloaded",
  });
  // H1 should read "Simulation-Verlauf"
  const h1 = await page.locator("h1").first().textContent();
  if (!h1 || !h1.includes("Verlauf")) fail(`history H1 wrong: '${h1}'`);
  // Row to our trial should be present
  const linkSel = `a[href="/dashboard/simulation?trial=${trialId}"]`;
  await page.waitForSelector(linkSel, { timeout: 10000 });
  log("STEP5", "OK — history page shows the saved run");
  // Apply a filter that should EXCLUDE the AAPL run, table should empty out.
  log("STEP5", "Applying filter Symbol=ZZZNOTASYMBOL — table must empty");
  await page.fill('input[placeholder*="AAPL"]', "ZZZNOTASYMBOL");
  await page.click('button:has-text("Filter anwenden")');
  // Wait for empty state text
  await page.waitForSelector(
    'text=Keine Simulationen passen zu diesen Filtern',
    { timeout: 10000 },
  );
  log("STEP5", "OK — filter empty state shown");
  // Reset filter — table should re-populate
  await page.click('button:has-text("Zurücksetzen")');
  await page.waitForSelector(linkSel, { timeout: 10000 });
  log("STEP5", "OK — filter reset, row reappears");
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1366, height: 800 },
  });
  const page = await ctx.newPage();
  page.on("pageerror", (err) => console.error("[pageerror]", err.message));
  page.on("console", (m) => {
    if (m.type() === "error") console.error("[console.error]", m.text());
  });

  const t0 = Date.now();
  try {
    await login(page);
    await step1_openSimulationPage(page);
    const trialId = await step2_runSimulation(page);
    await step3_recentPanelShowsRun(page, trialId);
    await step4_clickRowPrefillsForm(page, trialId);
    await step5_historyPage(page, trialId);
    const ms = Date.now() - t0;
    console.log(`\n=== ALL STEPS PASSED in ${(ms / 1000).toFixed(1)}s ===`);
  } catch (e) {
    console.error("\n=== TEST FAILED ===");
    console.error(e.message);
    // Take a screenshot for debugging — alongside the spec file
    try {
      const path = require("path");
      const out = path.join(__dirname, "failure.png");
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
