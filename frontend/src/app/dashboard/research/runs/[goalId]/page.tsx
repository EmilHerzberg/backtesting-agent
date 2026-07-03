// ATSX-16 (C-2): Agent Console — live single-run view per AGENT-CONSOLE-WIREFRAME.md.
"use client";

import { use } from "react";
import {
  ActivityStream,
  BudgetHUD,
  EvidencePanel,
  NotLivePanel,
  PipelineRail,
  RunStatusBanner,
  TopBar,
} from "@/components/research/console";
import {
  useCandidates,
  useHypothesis,
  useRunControls,
  useRunEvents,
  useRunState,
} from "@/lib/research/hooks";

export default function AgentConsolePage({
  params,
}: {
  params: Promise<{ goalId: string }>;
}) {
  const { goalId } = use(params);
  const { state, error, notLive, loading } = useRunState(goalId);
  const status = state?.status;
  const events = useRunEvents(goalId, status);
  const candidates = useCandidates(goalId, status);
  const hypothesis = useHypothesis(goalId, status);

  const running = state?.status === "running";
  const controls = useRunControls(goalId);

  return (
    <div className="flex flex-col h-[calc(100vh-3.5rem)]">
      <TopBar state={state} goalId={goalId} controls={controls} />

      {error && (
        <div className="bg-red-950/40 border-b border-red-900 px-4 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      {notLive ? (
        <NotLivePanel goalId={goalId} />
      ) : loading && !state ? (
        <div className="flex-1 flex items-center justify-center text-gray-600">Connecting…</div>
      ) : (
        <>
          <BudgetHUD state={state} />
          {state && <RunStatusBanner state={state} />}
          <div className="grid grid-cols-[280px_1fr_300px] flex-1 min-h-0">
            <PipelineRail state={state} hypothesis={hypothesis} />
            <ActivityStream events={events} goalId={goalId} />
            <EvidencePanel
              candidates={candidates}
              failureCount={state?.failure_count ?? 0}
              hypothesis={hypothesis}
              goalId={goalId}
              running={!!running}
            />
          </div>
        </>
      )}
    </div>
  );
}
