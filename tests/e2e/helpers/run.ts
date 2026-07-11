import { APIRequestContext, expect } from "@playwright/test";
import { BACKEND } from "./auth";

// A €0 rule_based run that DETERMINISTICALLY surfaces one candidate (calibrated: mean-reversion on stable/
// mean-reverting staples clears the honest gates that trend-on-trending-stocks does not). Stops early at the
// first candidate (target_candidates=1). Seeded → reproducible.
export const DEFAULT_RUN = {
  goal_text: "robust mean-reversion on consumer staples",
  asset_pool: ["KO", "PG", "JNJ", "XOM"],
  strategy_families: ["mean_reversion"],
  rigor: "exploratory",
  enable_oos: false,
  seed: 3,
  max_runs: 40,
  max_seconds: 240,
  target_candidates: 1,
  agent_mode: "rule_based",
  provider: null as string | null,
  model: null as string | null,
  mode: "robustness",
  window_start: null as string | null,
  window_end: null as string | null,
};

const auth = (token: string) => ({ Authorization: `Bearer ${token}` });
const TERMINAL = new Set(["completed", "stopped", "failed", "interrupted"]);

export async function startRunApi(
  request: APIRequestContext,
  token: string,
  overrides: Record<string, unknown> = {},
): Promise<string> {
  const res = await request.post(`${BACKEND}/api/research/runs`, {
    headers: auth(token),
    data: { ...DEFAULT_RUN, ...overrides },
  });
  expect(res.ok(), `start run -> ${res.status()}: ${await res.text().catch(() => "")}`).toBeTruthy();
  const goalId = String((await res.json()).goal_id || "");
  expect(goalId, "goal_id present").toBeTruthy();
  return goalId;
}

// NOTE: a synchronous backtest briefly blocks the async event loop, so a poll that lands mid-backtest can
// see a reset connection. These getters swallow transient errors (return null/[]) and the pollers retry —
// mirroring the frontend, whose request() also retries. This keeps the E2E robust without masking real failures.
export async function getState(
  request: APIRequestContext,
  token: string,
  goalId: string,
): Promise<Record<string, any> | null> {
  try {
    const res = await request.get(`${BACKEND}/api/research/runs/${goalId}/state`, { headers: auth(token) });
    return res.ok() ? res.json() : null;
  } catch {
    return null;
  }
}

export async function getCandidates(
  request: APIRequestContext,
  token: string,
  goalId: string,
): Promise<any[]> {
  try {
    const res = await request.get(`${BACKEND}/api/research/runs/${goalId}/candidates`, { headers: auth(token) });
    return res.ok() ? res.json() : [];
  } catch {
    return [];
  }
}

export async function getReport(
  request: APIRequestContext,
  token: string,
  goalId: string,
): Promise<Record<string, any> | null> {
  try {
    const res = await request.get(`${BACKEND}/api/research/runs/${goalId}/report`, { headers: auth(token) });
    return res.ok() ? res.json() : null;
  } catch {
    return null;
  }
}

/** Poll the run state until it reaches a terminal status (or COMPLETED phase), else throw with the last state. */
export async function pollUntilTerminal(
  request: APIRequestContext,
  token: string,
  goalId: string,
  timeoutMs = 220_000,
): Promise<Record<string, any>> {
  const start = Date.now();
  let last: Record<string, any> | null = null;
  while (Date.now() - start < timeoutMs) {
    last = await getState(request, token, goalId);
    if (last && (TERMINAL.has(String(last.status)) || String(last.phase).toUpperCase() === "COMPLETED")) {
      return last;
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
  throw new Error(`run ${goalId} did not terminate in ${timeoutMs}ms (last: status=${last?.status} phase=${last?.phase})`);
}
