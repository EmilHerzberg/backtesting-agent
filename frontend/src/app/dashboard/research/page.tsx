// ATSX-23 (C-6): Research home — runs history + Director dashboard (aggregate stats).
"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { providerApi } from "@/lib/api";
import { useDirectorStats, useRunsList } from "@/lib/research/hooks";
import { phaseToPill, RunListItem } from "@/lib/research/types";
import { OnboardingModal } from "@/components/onboarding-modal";

const PILL: Record<string, string> = {
  running: "bg-blue-900 text-blue-300",
  completed: "bg-green-900 text-green-300",
  stopped: "bg-red-900 text-red-300",
  failed: "bg-red-900 text-red-300",
  paused: "bg-orange-900 text-orange-300",
  connecting: "bg-gray-800 text-gray-400",
};

function Stat({ label, value, accent }: { label: string; value: number | string; accent?: string }) {
  return (
    <div className="rounded border border-gray-800 bg-gray-900 p-3">
      <div className="text-[10px] uppercase font-semibold text-gray-500">{label}</div>
      <div className={`text-2xl font-bold font-mono mt-1 ${accent || "text-gray-100"}`}>{value}</div>
    </div>
  );
}

function RunRow({ r }: { r: RunListItem }) {
  const pill = phaseToPill(r.status, r.phase);
  return (
    <Link
      href={`/dashboard/research/runs/${r.goal_id}`}
      className="flex items-center justify-between rounded border border-gray-800 bg-gray-900 p-3 hover:border-gray-700"
    >
      <div className="min-w-0">
        <div className="text-sm text-gray-200 truncate">{r.goal_text || r.goal_id}</div>
        <div className="text-[11px] text-gray-600 font-mono mt-0.5">
          {r.candidates_count} survivors · {r.failure_count} dead · {r.used_runs}/{r.max_runs} runs
        </div>
      </div>
      <span className={`text-[10px] uppercase font-semibold px-2 py-1 rounded shrink-0 ${PILL[pill]}`}>
        {pill}
      </span>
    </Link>
  );
}

export default function ResearchHomePage() {
  const { runs, error, loading } = useRunsList();
  const stats = useDirectorStats();

  // F-1: onboard a keyless new user (unless already skipped). Rule-based never blocked.
  const [onboard, setOnboard] = useState(false);
  const [types, setTypes] = useState<string[]>([]);
  useEffect(() => {
    if (typeof window === "undefined" || localStorage.getItem("bt_onboarding_skipped")) return;
    providerApi.list().then((ps) => {
      if (ps.length === 0) {
        providerApi.types().then((r) => setTypes(r.types)).catch(() => {});
        setOnboard(true);
      }
    }).catch(() => {});
  }, []);

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6">
      {onboard && (
        <OnboardingModal
          types={types}
          onDone={() => setOnboard(false)}
          onSkip={() => {
            localStorage.setItem("bt_onboarding_skipped", "1");
            setOnboard(false);
          }}
        />
      )}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-100">Research</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            The autonomous falsification institute — runs, survivors, and the graveyard.
          </p>
        </div>
        <Link
          href="/dashboard/research/new"
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-white text-sm font-semibold"
        >
          + New Run
        </Link>
      </div>

      {/* Director dashboard */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Stat label="Runs" value={stats.total_runs} />
          <Stat label="Trials (audit)" value={stats.audit_trial_count} />
          <Stat label="Survivors" value={stats.candidates_found} accent="text-green-300" />
          <Stat label="Died (graveyard)" value={stats.failures_recorded} accent="text-red-300" />
          <Stat label="Valid trials" value={stats.valid_research_trial_count} />
          <Stat label="OOS passed" value={stats.oos_passed} accent="text-green-300" />
          <Stat label="OOS failed" value={stats.oos_failed} accent="text-red-300" />
          <Stat
            label="Survival rate"
            value={
              stats.valid_research_trial_count > 0
                ? `${Math.round((stats.candidates_found / stats.valid_research_trial_count) * 100)}%`
                : "—"
            }
          />
        </div>
      )}

      {/* Coverage map (ATSX-26): asset × strategy explored + outcomes */}
      {stats && stats.coverage.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs uppercase font-semibold text-gray-500">Coverage — asset × strategy</div>
          <div className="rounded border border-gray-800 bg-gray-900 divide-y divide-gray-800/60">
            {stats.coverage.map((c) => (
              <div
                key={`${c.security_id}-${c.template_id}`}
                className="flex items-center justify-between px-3 py-2 text-sm"
              >
                <span className="text-gray-200">
                  <span className="font-mono">{c.security_id}</span>
                  <span className="text-gray-600"> · </span>
                  <span className="font-mono text-gray-400">{c.template_id}</span>
                </span>
                <span className="font-mono text-[11px]">
                  <span className="text-green-400">{c.survived} survived</span>
                  <span className="text-gray-600"> · </span>
                  <span className="text-red-400">{c.died} died</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Runs history */}
      <div className="space-y-2">
        <div className="text-xs uppercase font-semibold text-gray-500">Runs</div>
        {error && (
          <div className="rounded border border-red-900 bg-red-950/40 px-3 py-2 text-sm text-red-300">{error}</div>
        )}
        {loading ? (
          <div className="text-gray-600 py-6 text-center text-sm">Loading…</div>
        ) : runs.length === 0 ? (
          <div className="rounded border border-gray-800 bg-gray-900 p-6 text-center text-gray-500 text-sm">
            No runs yet. <Link href="/dashboard/research/new" className="text-blue-400 hover:underline">Start one →</Link>
          </div>
        ) : (
          runs.map((r) => <RunRow key={r.goal_id} r={r} />)
        )}
      </div>
    </div>
  );
}
