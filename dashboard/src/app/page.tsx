"use client";

import { useState } from "react";
import { Header } from "@/components/dashboard/header";
import { MainPanel } from "@/components/dashboard/main-panel";
import { RunForm } from "@/components/dashboard/run-form";
import { RunHistory } from "@/components/dashboard/run-history";
import { usePipeline } from "@/hooks/use-pipeline";
import { useRuns } from "@/hooks/use-runs";
import type { RunFormValues } from "@/lib/types";

const DEFAULT_FORM: RunFormValues = {
  board: "CBSE",
  subject: "",
  grade: "Grade 8",
  chapter: "",
};

export default function DashboardPage() {
  const [form, setForm] = useState<RunFormValues>(DEFAULT_FORM);
  const { runs, refresh } = useRuns();
  const { state, isRunning, startRun, setActiveTab } = usePipeline({
    onRunComplete: refresh,
  });

  const displayStatus =
    state.status === "idle" && isRunning ? "running" : state.status;

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <Header status={displayStatus} runCount={runs.length} />
      <div className="flex min-h-0 flex-1">
        <aside className="flex w-[280px] shrink-0 flex-col border-r border-border bg-card">
          <RunForm
            form={form}
            onFormChange={setForm}
            isRunning={isRunning}
            onStart={startRun}
          />
          <RunHistory runs={runs} />
        </aside>
        <MainPanel
          state={state.status === "idle" && isRunning ? { ...state, status: "running" } : state}
          form={form}
          onStart={startRun}
          onTabChange={setActiveTab}
        />
      </div>
    </div>
  );
}
