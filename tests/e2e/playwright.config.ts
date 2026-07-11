import path from "path";
import { defineConfig, devices } from "@playwright/test";

// Local-stack E2E: Playwright launches the backend (uvicorn) + the built frontend (next start) and drives the
// real app. Rule-based scenarios are €0 and deterministic. The paid multi-model scenario (s9) is gated on E2E_LLM.
const REPO_ROOT = path.resolve(__dirname, "..", "..");
const FRONTEND = path.join(REPO_ROOT, "frontend");
const PY = path.join(REPO_ROOT, ".venv", "Scripts", "python.exe"); // Windows venv layout

export default defineConfig({
  testDir: "./specs",
  // The scenarios share one backend + drive real research runs; keep them serial for determinism.
  fullyParallel: false,
  workers: 1,
  timeout: 260_000, // a full rule_based run (to the first candidate) can take ~1–3 min on this data
  expect: { timeout: 20_000 },
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    actionTimeout: 20_000,
    navigationTimeout: 30_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // Reuse already-running dev servers; in CI, launch a fresh stack.
  webServer: [
    {
      command: `"${PY}" -m uvicorn src.backend.api.main:app --port 8000 --log-level warning`,
      cwd: REPO_ROOT,
      url: "http://localhost:8000/openapi.json",
      reuseExistingServer: !process.env.CI,
      timeout: 90_000,
      env: {
        DATABASE_URL: "sqlite+aiosqlite:///./data/e2e.db",
        SECRET_KEY: "e2e-test-secret-not-for-production",
        BROKER_MODE: "mock",
      },
    },
    {
      command: "npx next start -p 3000",
      cwd: FRONTEND,
      url: "http://localhost:3000",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
