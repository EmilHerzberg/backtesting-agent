// ATSX-21 (C-5): Report — the Reporter's honest FinalReport (numbers from the store).
"use client";

import Link from "next/link";
import { use } from "react";
import { useReport } from "@/lib/research/hooks";
import { ReportSection } from "@/lib/research/types";

function NumericFields({ fields }: { fields: Record<string, unknown> }) {
  const entries = Object.entries(fields);
  if (entries.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-2 mb-2">
      {entries.map(([k, v]) => (
        <span
          key={k}
          className="text-[11px] font-mono px-2 py-1 rounded bg-gray-950 border border-gray-800 text-gray-300"
        >
          <span className="text-gray-500">{k}</span>{" "}
          {typeof v === "object" ? JSON.stringify(v) : String(v)}
        </span>
      ))}
    </div>
  );
}

function Section({ s }: { s: ReportSection }) {
  return (
    <div className="rounded border border-gray-800 bg-gray-900 p-4 space-y-1">
      <div className="text-xs uppercase font-semibold text-gray-500">{s.title}</div>
      <NumericFields fields={s.numeric_fields} />
      {s.narrative && <p className="text-sm text-gray-300 leading-relaxed">{s.narrative}</p>}
    </div>
  );
}

export default function ReportPage({
  params,
}: {
  params: Promise<{ goalId: string }>;
}) {
  const { goalId } = use(params);
  const { report, error, loading } = useReport(goalId);

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-5">
      <div className="flex items-center gap-3">
        <Link href={`/dashboard/research/runs/${goalId}`} className="text-sm text-gray-400 hover:text-gray-200">
          ← Console
        </Link>
        <h1 className="text-lg font-semibold text-gray-100">Research Report</h1>
        {report && (
          <span className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">
            {report.status}
          </span>
        )}
      </div>

      {report?.goal_text && <div className="text-sm text-gray-400">{report.goal_text}</div>}

      {error && (
        <div className="rounded border border-red-900 bg-red-950/40 px-4 py-3 text-sm text-red-300">{error}</div>
      )}

      {loading ? (
        <div className="text-gray-600 py-12 text-center">Loading report…</div>
      ) : !report?.available ? (
        <div className="rounded border border-gray-800 bg-gray-900 p-6 text-center text-gray-500">
          No report yet — it is generated when the run finishes. This page will update automatically.
        </div>
      ) : (
        <>
          {/* Honest-framing banner — never claims proof */}
          <div className="rounded border border-amber-900/40 bg-amber-950/10 px-4 py-3 text-[13px] text-amber-200/80">
            This is a falsification report. Surviving strategies are <strong>not yet falsified</strong> —
            not proven profitable. Read the Limitations section.
          </div>
          <div className="space-y-3">
            {report.sections.map((s) => (
              <Section key={s.key} s={s} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
