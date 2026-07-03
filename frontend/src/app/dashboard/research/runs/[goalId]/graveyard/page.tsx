// ATSX-19 (C-4): Graveyard — what died and why. Filter by cause of death.
"use client";

import Link from "next/link";
import { use, useState } from "react";
import { useGraveyard } from "@/lib/research/hooks";

export default function GraveyardPage({
  params,
}: {
  params: Promise<{ goalId: string }>;
}) {
  const { goalId } = use(params);
  const { graveyard, error } = useGraveyard(goalId);
  const [filter, setFilter] = useState<string | null>(null);

  const failures = graveyard?.failures ?? [];
  const shown = filter
    ? failures.filter((f) => (f.failed_gate || f.failure_reason || "unknown") === filter)
    : failures;

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-5">
      <div className="flex items-center gap-3">
        <Link href={`/dashboard/research/runs/${goalId}`} className="text-sm text-gray-400 hover:text-gray-200">
          ← Console
        </Link>
        <h1 className="text-lg font-semibold text-gray-100">Graveyard</h1>
        {graveyard && <span className="font-mono text-sm text-gray-500">{graveyard.total} dead</span>}
      </div>

      {error && (
        <div className="rounded border border-red-900 bg-red-950/40 px-4 py-3 text-sm text-red-300">{error}</div>
      )}

      {graveyard && graveyard.total === 0 ? (
        <div className="text-sm text-gray-600 py-8 text-center">
          No failures recorded — nothing has died here yet.
        </div>
      ) : (
        <>
          {/* Aggregate cause-of-death sentence (sum reconciles with total) */}
          {graveyard && (
            <p className="text-sm text-gray-400">
              <span className="font-mono text-gray-200">{graveyard.total}</span> strategies died —{" "}
              {Object.entries(graveyard.by_cause)
                .sort((a, b) => b[1] - a[1])
                .map(([cause, count], i) => (
                  <span key={cause}>
                    {i > 0 ? " · " : ""}
                    <span className="font-mono text-red-300">{count}</span>{" "}
                    <span className="font-mono">{cause}</span>
                  </span>
                ))}
            </p>
          )}

          {/* Cause-of-death filter chips */}
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => setFilter(null)}
              className={`text-xs px-2 py-1 rounded ${
                filter === null ? "bg-blue-700 text-white" : "bg-gray-800 text-gray-400 hover:bg-gray-700"
              }`}
            >
              All ({graveyard?.total ?? 0})
            </button>
            {Object.entries(graveyard?.by_cause ?? {})
              .sort((a, b) => b[1] - a[1])
              .map(([cause, count]) => (
                <button
                  key={cause}
                  onClick={() => setFilter(cause)}
                  className={`text-xs px-2 py-1 rounded font-mono ${
                    filter === cause ? "bg-red-700 text-white" : "bg-gray-800 text-gray-400 hover:bg-gray-700"
                  }`}
                >
                  {cause} ({count})
                </button>
              ))}
          </div>

          {/* Failure list */}
          <div className="space-y-2">
            {shown.map((f, i) => (
              <Link
                key={`${f.strategy_hash}-${i}`}
                href={`/dashboard/research/runs/${goalId}/candidates/${f.strategy_hash}`}
                className="block rounded border border-gray-800 bg-gray-900 p-3 hover:border-gray-700"
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm text-gray-200">
                    {f.security_id} · <span className="font-mono">{f.template_id}</span>
                  </span>
                  <span className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-red-900/50 text-red-300 font-mono">
                    {f.failed_gate || f.failure_reason || "unknown"}
                  </span>
                </div>
                {f.critic_notes && (
                  <div className="text-[12px] text-gray-500 mt-1.5 italic">&ldquo;{f.critic_notes}&rdquo;</div>
                )}
                {f.failed_gate && f.gate_details && typeof f.gate_details.value !== "undefined" && (
                  <div className="text-[11px] text-gray-600 mt-1 font-mono">
                    value {String(f.gate_details.value)}
                    {typeof f.gate_details.threshold !== "undefined"
                      ? ` vs threshold ${String(f.gate_details.threshold)}`
                      : ""}
                  </div>
                )}
              </Link>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
