// ATSX-15 (C-0): polling data hooks for the Research screens.
// Hand-rolled useEffect + setInterval (repo convention; no SWR/react-query).
// Cadence per D4: 2s while running, stop on terminal status.

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { request } from "@/lib/api";
import {
  Candidate,
  CandidateArtifacts,
  Critique,
  DirectorStats,
  GateResult,
  Graveyard,
  Hypothesis,
  isTerminalStatus,
  LineageNode,
  OOSVerdict,
  Report,
  ResearchEvent,
  ResearchState,
  RunListItem,
} from "./types";

const POLL_MS = 2000;

interface RunStateHook {
  state: ResearchState | null;
  error: string;
  notLive: boolean; // /state 404'd — run no longer in memory and not in DB
  loading: boolean;
}

/** Poll a run's state; stops once terminal. 404 → notLive (honest empty state). */
export function useRunState(goalId: string): RunStateHook {
  const [state, setState] = useState<ResearchState | null>(null);
  const [error, setError] = useState("");
  const [notLive, setNotLive] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const s = await request<ResearchState>(`/research/runs/${goalId}/state`);
      setState(s);
      setNotLive(false);
      setError("");
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Fehler";
      // 404 surfaces as "No research run" — treat as no-longer-live.
      if (msg.toLowerCase().includes("no research run") || msg.includes("404")) {
        setNotLive(true);
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  }, [goalId]);

  useEffect(() => {
    let active = true;
    void refresh();
    const t = setInterval(() => {
      // Stop polling once terminal (re-checked each tick via the latest state).
      setState((cur) => {
        if (active && !isTerminalStatus(cur?.status)) void refresh();
        return cur;
      });
    }, POLL_MS);
    return () => {
      active = false;
      clearInterval(t);
    };
  }, [refresh]);

  return { state, error, notLive, loading };
}

/** Activity stream: SSE (ATSX-26) with automatic polling fallback. Same shape —
 * if streaming is unavailable or drops, it degrades to the prior 2s polling. */
export function useRunEvents(goalId: string, stopWhenTerminalStatus?: string) {
  const [events, setEvents] = useState<ResearchEvent[]>([]);
  const sinceRef = useRef(0);

  const append = useCallback((batch: ResearchEvent[]) => {
    if (batch.length > 0) {
      sinceRef.current = batch[batch.length - 1].id;
      setEvents((prev) => [...prev, ...batch]);
    }
  }, []);

  useEffect(() => {
    let active = true;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    const controller = new AbortController();

    const poll = async () => {
      try {
        append(
          await request<ResearchEvent[]>(`/research/runs/${goalId}/events?since=${sinceRef.current}`),
        );
      } catch {
        /* next tick retries */
      }
    };

    const startPolling = () => {
      if (pollTimer) return;
      void poll();
      pollTimer = setInterval(() => {
        if (!isTerminalStatus(stopWhenTerminalStatus)) void poll();
      }, POLL_MS);
    };

    const startSSE = async () => {
      try {
        const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
        const res = await fetch(
          `/api/research/runs/${goalId}/events/stream?since=${sinceRef.current}`,
          {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
            signal: controller.signal,
          },
        );
        if (!res.ok || !res.body) throw new Error("stream unavailable");
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        while (active) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const frames = buf.split("\n\n");
          buf = frames.pop() ?? "";
          for (const frame of frames) {
            const dataLine = frame.split("\n").find((l) => l.startsWith("data:"));
            if (!dataLine) continue;
            const payload = dataLine.slice(5).trim();
            if (!payload || payload === "{}") continue;
            try {
              const ev = JSON.parse(payload) as ResearchEvent;
              if (ev && ev.id != null) append([ev]);
            } catch {
              /* skip malformed frame */
            }
          }
        }
        // Stream closed — if the run is still live, degrade to polling.
        if (active && !isTerminalStatus(stopWhenTerminalStatus)) startPolling();
      } catch {
        if (active) startPolling();
      }
    };

    void startSSE();

    return () => {
      active = false;
      controller.abort();
      if (pollTimer) clearInterval(pollTimer);
    };
  }, [goalId, stopWhenTerminalStatus, append]);

  return events;
}

/** Poll a run's candidates (cheap, small list). */
export function useCandidates(goalId: string, stopWhenTerminalStatus?: string) {
  const [candidates, setCandidates] = useState<Candidate[]>([]);

  const refresh = useCallback(async () => {
    try {
      setCandidates(await request<Candidate[]>(`/research/runs/${goalId}/candidates`));
    } catch {
      /* keep last */
    }
  }, [goalId]);

  useEffect(() => {
    void refresh();
    const t = setInterval(() => {
      if (!isTerminalStatus(stopWhenTerminalStatus)) void refresh();
    }, POLL_MS);
    return () => clearInterval(t);
  }, [refresh, stopWhenTerminalStatus]);

  return candidates;
}

/** Poll the current hypothesis (404 → null while none yet). */
export function useHypothesis(goalId: string, stopWhenTerminalStatus?: string) {
  const [hypothesis, setHypothesis] = useState<Hypothesis | null>(null);

  const refresh = useCallback(async () => {
    try {
      setHypothesis(await request<Hypothesis>(`/research/runs/${goalId}/hypothesis`));
    } catch {
      setHypothesis(null);
    }
  }, [goalId]);

  useEffect(() => {
    void refresh();
    const t = setInterval(() => {
      if (!isTerminalStatus(stopWhenTerminalStatus)) void refresh();
    }, POLL_MS);
    return () => clearInterval(t);
  }, [refresh, stopWhenTerminalStatus]);

  return hypothesis;
}

/** Poll a run's lineage tree (ATSX-26). Live-only — 404 → keep last while none/evicted. */
export function useLineage(goalId: string, stopWhenTerminalStatus?: string) {
  const [nodes, setNodes] = useState<LineageNode[]>([]);

  const refresh = useCallback(async () => {
    try {
      setNodes(await request<LineageNode[]>(`/research/runs/${goalId}/lineage`));
    } catch {
      /* 404 while no lineage yet / run evicted — keep last */
    }
  }, [goalId]);

  useEffect(() => {
    void refresh();
    const t = setInterval(() => {
      if (!isTerminalStatus(stopWhenTerminalStatus)) void refresh();
    }, POLL_MS);
    return () => clearInterval(t);
  }, [refresh, stopWhenTerminalStatus]);

  return nodes;
}

/** Poll the caller's runs list (history) — light cadence. */
export function useRunsList() {
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setRuns(await request<RunListItem[]>("/research/runs"));
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Fehler");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [refresh]);

  return { runs, error, loading };
}

/** Poll the Director-dashboard aggregate stats. */
export function useDirectorStats() {
  const [stats, setStats] = useState<DirectorStats | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStats(await request<DirectorStats>("/research/stats"));
    } catch {
      /* keep last */
    }
  }, []);

  useEffect(() => {
    void refresh();
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [refresh]);

  return stats;
}

/** Poll a run's graveyard (failures + aggregate by cause). */
export function useGraveyard(goalId: string, stopWhenTerminalStatus?: string) {
  const [graveyard, setGraveyard] = useState<Graveyard | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setGraveyard(await request<Graveyard>(`/research/runs/${goalId}/graveyard`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Fehler");
    }
  }, [goalId]);

  useEffect(() => {
    void refresh();
    const t = setInterval(() => {
      if (!isTerminalStatus(stopWhenTerminalStatus)) void refresh();
    }, POLL_MS);
    return () => clearInterval(t);
  }, [refresh, stopWhenTerminalStatus]);

  return { graveyard, error };
}

/** Fetch a run's final report (one-shot + light poll until available). */
export function useReport(goalId: string) {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const r = await request<Report>(`/research/runs/${goalId}/report`);
      setReport(r);
      return r.available;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Fehler");
      return true; // stop polling on error
    } finally {
      setLoading(false);
    }
  }, [goalId]);

  useEffect(() => {
    let active = true;
    void refresh();
    // Poll until the report becomes available, then stop.
    const t = setInterval(async () => {
      const done = await refresh();
      if (done && active) clearInterval(t);
    }, POLL_MS);
    return () => {
      active = false;
      clearInterval(t);
    };
  }, [refresh]);

  return { report, error, loading };
}

interface DossierHook {
  gates: GateResult[];
  critique: Critique | null;
  oos: OOSVerdict | null;
  artifacts: CandidateArtifacts | null;
  error: string;
  loading: boolean;
}

/** One-shot fetch of a candidate's gates + critique + OOS + evidence for the dossier. */
export function useCandidateDossier(goalId: string, hash: string): DossierHook {
  const [gates, setGates] = useState<GateResult[]>([]);
  const [critique, setCritique] = useState<Critique | null>(null);
  const [oos, setOos] = useState<OOSVerdict | null>(null);
  const [artifacts, setArtifacts] = useState<CandidateArtifacts | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const base = `/research/runs/${goalId}/candidates/${hash}`;
        const [g, c, o, a] = await Promise.all([
          request<GateResult[]>(`${base}/gates`),
          request<Critique>(`${base}/critique`),
          request<OOSVerdict>(`${base}/oos`),
          request<CandidateArtifacts>(`${base}/artifacts`),
        ]);
        if (!active) return;
        setGates(g);
        setCritique(c);
        setOos(o);
        setArtifacts(a);
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : "Fehler");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [goalId, hash]);

  return { gates, critique, oos, artifacts, error, loading };
}

export interface RunControls {
  busy: boolean;
  pause: () => void;
  resume: () => void;
  stop: () => void;
}

/** A-9 run controls: pause / resume / stop. Status reconciles on the next state poll. */
export function useRunControls(goalId: string): RunControls {
  const [busy, setBusy] = useState(false);

  const act = useCallback(
    async (path: string) => {
      setBusy(true);
      try {
        await request(`/research/runs/${goalId}/${path}`, { method: "POST" });
      } catch {
        /* the next /state poll reconciles the real status */
      } finally {
        setBusy(false);
      }
    },
    [goalId],
  );

  return {
    busy,
    pause: () => act("pause"),
    resume: () => act("resume"),
    stop: () => act("stop"),
  };
}
