// ATSX-26 (P4): Lineage graph — the hypothesis family tree (roots → mutations).
"use client";

import Link from "next/link";
import { use } from "react";
import { useLineage } from "@/lib/research/hooks";
import { LineageNode } from "@/lib/research/types";

function Node({ node, all, depth }: { node: LineageNode; all: LineageNode[]; depth: number }) {
  const children = all.filter((n) => n.parent_lineage_id === node.lineage_id);
  return (
    <div>
      <div className="flex items-center gap-2 py-1 text-sm" style={{ paddingLeft: depth * 18 }}>
        <span className="font-mono text-gray-300">
          {depth > 0 ? "└ " : ""}
          {node.lineage_id.slice(0, 14)}
        </span>
        <span className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-gray-800 text-gray-500">
          {node.declared_by}
        </span>
        {node.root_strategy_hash && (
          <span className="font-mono text-[11px] text-gray-600">{node.root_strategy_hash.slice(0, 8)}</span>
        )}
      </div>
      {children.map((c) => (
        <Node key={c.lineage_id} node={c} all={all} depth={depth + 1} />
      ))}
    </div>
  );
}

export default function LineagePage({ params }: { params: Promise<{ goalId: string }> }) {
  const { goalId } = use(params);
  const nodes = useLineage(goalId);
  const roots = nodes.filter((n) => !n.parent_lineage_id);

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-4">
      <div className="flex items-center gap-3">
        <Link href={`/dashboard/research/runs/${goalId}`} className="text-sm text-gray-400 hover:text-gray-200">
          ← Console
        </Link>
        <h1 className="text-lg font-semibold text-gray-100">Lineage</h1>
        <span className="font-mono text-sm text-gray-500">{nodes.length} nodes</span>
      </div>

      <p className="text-[12px] text-gray-600">
        Each hypothesis starts a <span className="text-gray-400">root</span> lineage; parameter
        mutations branch as <span className="text-gray-400">children</span> (sharing OOS budget).
        Live view — available while the run is in memory.
      </p>

      {nodes.length === 0 ? (
        <div className="text-sm text-gray-600 py-10 text-center">
          No lineage yet — or this run is no longer live.
        </div>
      ) : (
        <div className="rounded border border-gray-800 bg-gray-900 p-3">
          {roots.map((r) => (
            <Node key={r.lineage_id} node={r} all={nodes} depth={0} />
          ))}
        </div>
      )}
    </div>
  );
}
