// ATSX-17 (C-3): Candidate Dossier — trust-first (gates/critique/OOS lead; Sharpe demoted).
"use client";

import Link from "next/link";
import { use } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, YAxis } from "recharts";
import { useCandidateDossier } from "@/lib/research/hooks";
import { GateResult } from "@/lib/research/types";

const OOS_STYLE: Record<string, string> = {
  PASS: "bg-green-900 text-green-300 border-green-700",
  FAIL: "bg-red-900 text-red-300 border-red-700",
  PENDING: "bg-gray-800 text-gray-400 border-gray-700",
};

const fmtPct = (x: number | undefined | null) =>
  x == null ? "—" : `${(x * 100).toFixed(1)}%`;

const gnum = (d: Record<string, unknown>, k: string): number | null => {
  const v = d[k];
  return typeof v === "number" ? v : null;
};

const REGIME_COLOR: Record<string, string> = {
  bull: "text-green-400",
  bear: "text-red-400",
  sideways: "text-gray-400",
};

function GateRow({ g }: { g: GateResult }) {
  const passed = g.status.toUpperCase().includes("PASS");
  return (
    <div className="flex items-center justify-between border-b border-gray-800/60 py-2">
      <div className="flex items-center gap-2">
        <span className={`font-mono ${passed ? "text-green-400" : "text-red-400"}`}>
          {passed ? "✓" : "✗"}
        </span>
        <span className="text-sm text-gray-200 font-mono">{g.gate_id}</span>
      </div>
      <div className="font-mono text-[11px] text-gray-400">
        {g.value != null ? `value ${g.value}` : "—"}
        {g.threshold != null ? ` · thr ${g.threshold}` : ""}
      </div>
    </div>
  );
}

export default function CandidateDossierPage({
  params,
}: {
  params: Promise<{ goalId: string; hash: string }>;
}) {
  const { goalId, hash } = use(params);
  const { gates, critique, oos, artifacts, error, loading } = useCandidateDossier(goalId, hash);

  const oosOutcome = oos?.outcome || "PENDING";

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6">
      <div className="flex items-center gap-3">
        <Link
          href={`/dashboard/research/runs/${goalId}`}
          className="text-sm text-gray-400 hover:text-gray-200"
        >
          ← Console
        </Link>
        <span className="font-mono text-xs text-gray-500">{hash.slice(0, 16)}</span>
      </div>

      {error && (
        <div className="rounded border border-red-900 bg-red-950/40 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}
      {loading ? (
        <div className="text-gray-600 py-12 text-center">Loading dossier…</div>
      ) : (
        <>
          {/* TRUST FIRST: OOS verdict is the headline */}
          <div className={`rounded border px-4 py-4 ${OOS_STYLE[oosOutcome]}`}>
            <div className="text-[10px] uppercase font-semibold opacity-70">Out-of-sample verdict</div>
            <div className="text-2xl font-bold mt-1">OOS {oosOutcome}</div>
            {oos?.evaluated_at && (
              <div className="text-[11px] opacity-70 mt-1 font-mono">
                evaluated {new Date(oos.evaluated_at).toLocaleString()} · lineage{" "}
                {oos.lineage_id?.slice(0, 8)}
              </div>
            )}
            {/* D2: the buy-and-hold reality check — the comparison bar */}
            {oos?.excess_sharpe != null && (
              <div className="text-[11px] mt-2 flex gap-4">
                <span>
                  vs buy &amp; hold (risk-adjusted):{" "}
                  <span className={`font-mono font-semibold ${oos.excess_sharpe >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {oos.excess_sharpe >= 0 ? "+" : ""}{oos.excess_sharpe.toFixed(2)} Sharpe
                  </span>
                </span>
                {oos.excess_total_return_net != null && (
                  <span>
                    total return vs fee-paying hold:{" "}
                    <span className={`font-mono font-semibold ${oos.excess_total_return_net >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                      {oos.excess_total_return_net >= 0 ? "+" : ""}{(oos.excess_total_return_net * 100).toFixed(1)}%
                    </span>
                  </span>
                )}
              </div>
            )}
            {oosOutcome === "PENDING" && (
              <div className="text-[11px] opacity-70 mt-1">Not yet promoted to the OOS lockbox.</div>
            )}
          </div>

          {/* STATISTICAL QUALITY (F-8) — the "why" behind the confidence, from the gate report */}
          {gates.length > 0 && (() => {
            const gd = (id: string) => gates.find((x) => x.gate_id === id)?.details ?? {};
            const act = gd("minimum_activity");
            const bench = gd("benchmark_relative");
            const dsr = gd("deflated_sharpe");
            const t = gnum(act, "t_stat");
            const tier = (act["tier"] as string) || "—";
            const excess = gnum(bench, "excess_return");
            const dsrVal = gnum(dsr, "dsr");
            const trials = gnum(dsr, "n_trials");
            const provisional = dsr["provisional"] === true || (trials != null && trials < 20);
            const Cell = ({ label, value }: { label: string; value: string }) => (
              <div className="flex justify-between">
                <span className="text-gray-500">{label}</span>
                <span className="font-mono text-gray-300">{value}</span>
              </div>
            );
            return (
              <div className="rounded border border-gray-800 bg-gray-900 p-4">
                <div className="text-xs uppercase font-semibold text-gray-500 mb-2">Statistical quality</div>
                <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-[12px]">
                  <Cell label="Per-trade edge" value={t != null ? `t=${t.toFixed(2)} (${tier})` : `— (${tier})`} />
                  <Cell label="Benchmark margin" value={excess != null ? fmtPct(excess) : "—"} />
                  <Cell label="Out-of-sample" value={oosOutcome} />
                  <Cell
                    label="Multiple-testing (DSR)"
                    value={
                      dsrVal == null
                        ? "—"
                        : provisional
                          ? `provisional (${trials ?? "?"} trials)`
                          : `${dsrVal.toFixed(2)} (${trials} trials)`
                    }
                  />
                </div>
                <div className="text-[10px] text-gray-600 mt-2">
                  Confidence is headlined on the reliable per-run signals (per-trade edge, benchmark, OOS);
                  the DSR is a multiple-testing overlay, provisional on small runs.
                </div>
              </div>
            );
          })()}

          {/* GATES */}
          <div className="rounded border border-gray-800 bg-gray-900 p-4">
            <div className="text-xs uppercase font-semibold text-gray-500 mb-2">
              Quality gates ({gates.length})
            </div>
            {gates.length === 0 ? (
              <div className="text-sm text-gray-600 py-2">No gate report stored.</div>
            ) : (
              gates.map((g) => <GateRow key={g.gate_id} g={g} />)
            )}
          </div>

          {/* CRITIQUE */}
          <div className="rounded border border-gray-800 bg-gray-900 p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs uppercase font-semibold text-gray-500">Adversarial critique</span>
              {critique && (
                <span className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-amber-900/40 text-amber-300">
                  {critique.recommendation || "—"} · conf {critique.confidence}
                </span>
              )}
            </div>
            {critique?.prose && <div className="text-sm text-gray-300">{critique.prose}</div>}
            {critique && critique.weaknesses.length > 0 ? (
              <ul className="space-y-1">
                {critique.weaknesses.map((w, i) => (
                  <li key={i} className="text-[13px] text-gray-400 flex gap-2">
                    <span className="text-red-500">▪</span>
                    {w}
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-[13px] text-gray-600">No specific weaknesses recorded.</div>
            )}
          </div>

          {/* Evidence drill-downs (ATSX-27): equity / benchmark / regime */}
          {artifacts &&
          (artifacts.equity_curve.length > 1 ||
            Object.keys(artifacts.regime_analysis).length > 0 ||
            artifacts.benchmark.buy_hold_return != null) ? (
            <div className="rounded border border-gray-800 bg-gray-900 p-4 space-y-4">
              <div className="text-xs uppercase font-semibold text-gray-500">Evidence</div>

              {artifacts.equity_curve.length > 1 && (
                <div>
                  <div className="text-[11px] text-gray-500 mb-1">Equity curve</div>
                  <ResponsiveContainer width="100%" height={120}>
                    <LineChart data={artifacts.equity_curve.map((v, i) => ({ i, v }))}>
                      <YAxis hide domain={["dataMin", "dataMax"]} />
                      <Tooltip
                        contentStyle={{ background: "#111827", border: "1px solid #374151", fontSize: 11 }}
                        labelFormatter={() => ""}
                        formatter={(value) => [Number(value).toFixed(2), "equity"]}
                      />
                      <Line type="monotone" dataKey="v" stroke="#3b82f6" dot={false} strokeWidth={1.5} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}

              {artifacts.benchmark.buy_hold_return != null && (
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px]">
                  <span className="text-gray-500 uppercase text-[10px] font-semibold w-full">
                    Benchmark — Buy &amp; Hold
                  </span>
                  <span className="font-mono text-gray-300">return {fmtPct(artifacts.benchmark.buy_hold_return)}</span>
                  <span className="font-mono text-gray-300">
                    sharpe {artifacts.benchmark.buy_hold_sharpe?.toFixed(2) ?? "—"}
                  </span>
                </div>
              )}

              {Object.keys(artifacts.regime_analysis).length > 0 && (
                <div>
                  <div className="text-[11px] text-gray-500 mb-1">Regime breakdown</div>
                  <div className="space-y-1">
                    {Object.entries(artifacts.regime_analysis).map(([window, r]) => (
                      <div key={window} className="flex items-center justify-between text-[12px]">
                        <span className="text-gray-400 capitalize w-14">{window}</span>
                        <span className={`uppercase font-semibold ${REGIME_COLOR[r.type] || "text-gray-400"}`}>
                          {r.type}
                        </span>
                        <span className="font-mono text-gray-400">ret {fmtPct(r.return)}</span>
                        <span className="font-mono text-gray-400">sharpe {r.sharpe?.toFixed(2)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="text-[11px] text-gray-600">
              No serialized evidence for this candidate yet — regime/benchmark/equity attach when a
              strategy survives gates + critic.
            </div>
          )}
        </>
      )}
    </div>
  );
}
