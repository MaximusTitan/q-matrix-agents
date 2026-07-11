"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Header } from "@/components/dashboard/header";
import { MainPanel } from "@/components/dashboard/main-panel";
import { QueuePanel } from "@/components/dashboard/queue-panel";
import { RunForm } from "@/components/dashboard/run-form";
import { RunHistory } from "@/components/dashboard/run-history";
import { usePipeline } from "@/hooks/use-pipeline";
import { useChapterQueue } from "@/hooks/use-chapter-queue";
import { useRuns } from "@/hooks/use-runs";
import type { RunFormValues, RunOutcome } from "@/lib/types";

const DEFAULT_FORM: RunFormValues = {
  board: "",
  subject: "",
  grade: "",
  chapter: "",
};

export default function DashboardPage() {
  const [form, setForm] = useState<RunFormValues>(DEFAULT_FORM);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const { runs, refresh } = useRuns();

  // Bridge the run→queue completion cycle: usePipeline needs a completion callback,
  // but the queue (which owns that callback) needs startRun/isRunning from usePipeline.
  const queueCompleteRef = useRef<(outcome: RunOutcome) => void>(() => {});

  const handleRunComplete = useCallback(
    (outcome: RunOutcome) => {
      refresh();
      queueCompleteRef.current(outcome);
    },
    [refresh]
  );

  const { state, isRunning, startRun, setActiveTab } = usePipeline({
    onRunComplete: handleRunComplete,
  });

  const queue = useChapterQueue({ startRun, isRunning });
  useEffect(() => {
    queueCompleteRef.current = queue.handleRunComplete;
  }, [queue.handleRunComplete]);

  const displayStatus =
    state.status === "idle" && isRunning ? "running" : state.status;

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background">
      <Header status={displayStatus} runCount={runs.length} />
      <div className="flex min-h-0 flex-1 overflow-hidden">
        {/* Sidebar */}
        <aside
          className="relative flex shrink-0 flex-col border-r border-border bg-card transition-all duration-200"
          style={{ width: sidebarOpen ? 280 : 40 }}
        >
          {/* Collapse toggle */}
          <button
            onClick={() => setSidebarOpen((p) => !p)}
            className="absolute -right-3 top-4 z-20 flex h-6 w-6 items-center justify-center rounded-full border border-border bg-card text-muted-foreground shadow-sm hover:text-foreground transition-colors"
            title={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
          >
            {sidebarOpen ? (
              <ChevronLeft className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
          </button>

          {sidebarOpen && (
            <div className="thin-scroll flex min-h-0 flex-1 flex-col overflow-y-auto">
              <RunForm
                form={form}
                onFormChange={setForm}
                isRunning={isRunning}
                onStart={startRun}
                onEnqueue={queue.enqueue}
              />
              <QueuePanel
                queue={queue.queue}
                processing={queue.processing}
                isRunning={isRunning}
                onRun={queue.start}
                onClear={queue.clear}
                onRemove={queue.remove}
              />
              <RunHistory runs={runs} />
            </div>
          )}
        </aside>

        {/* Main content — scrolls independently */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          <MainPanel
            state={state.status === "idle" && isRunning ? { ...state, status: "running" } : state}
            form={form}
            onStart={startRun}
            onTabChange={setActiveTab}
          />
        </div>
      </div>
    </div>
  );
}
