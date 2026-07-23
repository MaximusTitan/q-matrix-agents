import { useState } from "react";
import { AgentTimeline } from "@/components/dashboard/agent-timeline";
import { CsvPreview } from "@/components/dashboard/csv-preview";
import { ComparePanel, collectCsvSources } from "@/components/dashboard/compare-panel";
import { EscalationPanel } from "@/components/dashboard/escalation-panel";
import { PrerequisiteMappingSummary } from "@/components/dashboard/prerequisite-mapping-summary";
import { cn } from "@/lib/utils";
import type { PipelineState, RunFormValues, StartRunOptions } from "@/lib/types";

interface MainPanelProps {
  state: PipelineState;
  form: RunFormValues;
  onStart: (options: StartRunOptions) => void;
  onTabChange: (tab: number) => void;
}

export function MainPanel({ state, form, onStart }: MainPanelProps) {
  // Local view tab (Pipeline vs Compare). NOT state.activeTab — the reducer
  // repurposes that to track the active attempt.
  const [view, setView] = useState<"pipeline" | "compare">("pipeline");
  const compareReady = collectCsvSources(state).length >= 2;

  if (state.status === "idle") {
    return (
      <main className="flex flex-1 flex-col overflow-y-auto p-6">
        <div className="flex h-[340px] flex-col items-center justify-center gap-4">
          <div className="flex h-16 w-16 items-center justify-center rounded-full border border-border bg-secondary text-3xl text-muted-foreground/40">
            ⟳
          </div>
          <div className="text-center">
            <div className="text-sm font-bold text-foreground/70">No run in progress</div>
            <div className="mt-2 max-w-xs text-[11px] text-muted-foreground leading-relaxed">
              ① Fill in Board / Subject / Grade / Chapter
              <span className="mx-1 text-border">→</span>
              ② Click ▶ Run Pipeline
              <span className="mx-1 text-border">→</span>
              ③ Watch agents stream results live
            </div>
          </div>
        </div>
      </main>
    );
  }

  const activeView = view === "compare" && compareReady ? "compare" : "pipeline";

  return (
    <main className="flex flex-1 flex-col overflow-y-auto p-6">
      {/* View tabs */}
      <div className="mb-4 flex gap-1 border-b border-border">
        {([
          ["pipeline", "Pipeline", true],
          ["compare", "Compare", compareReady],
        ] as const).map(([value, label, enabled]) => (
          <button
            key={value}
            onClick={() => enabled && setView(value)}
            disabled={!enabled}
            title={!enabled ? "Run the pipeline to produce CSVs to compare" : undefined}
            className={cn(
              "-mb-px border-b-2 px-3 py-1.5 text-xs font-bold transition-colors",
              activeView === value
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
              !enabled && "cursor-not-allowed opacity-40 hover:text-muted-foreground"
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {activeView === "compare" ? (
        <ComparePanel state={state} />
      ) : (
        <>
          <AgentTimeline agents={state.agents} currentAttempt={state.currentAttempt} />
          <PrerequisiteMappingSummary
            agent={[...state.agents]
              .reverse()
              .find((a) =>
                a.name === "Prerequisites" || a.name === "PrerequisitesL2" || a.name === "PrerequisitesL3"
              )}
          />
          {state.csv && (
            <CsvPreview
              csv={state.csv}
              chapter={form.chapter}
              selectedBy={state.selectedBy}
              source={state.source}
              candidateCount={state.candidateCount}
            />
          )}
          {state.escalation && (
            <EscalationPanel
              form={form}
              escalation={state.escalation}
              attempts={state.attempts}
              onStart={onStart}
            />
          )}
        </>
      )}
    </main>
  );
}
