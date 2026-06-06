import { AgentTimeline } from "@/components/dashboard/agent-timeline";
import { CsvPreview } from "@/components/dashboard/csv-preview";
import { EscalationPanel } from "@/components/dashboard/escalation-panel";
import type { PipelineState, RunFormValues, StartRunOptions } from "@/lib/types";

interface MainPanelProps {
  state: PipelineState;
  form: RunFormValues;
  onStart: (options: StartRunOptions) => void;
  onTabChange: (tab: number) => void;
}

export function MainPanel({ state, form, onStart, onTabChange }: MainPanelProps) {
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

  return (
    <main className="flex flex-1 flex-col overflow-y-auto p-6">
      <AgentTimeline agents={state.agents} currentAttempt={state.currentAttempt} />
      {state.csv && <CsvPreview csv={state.csv} chapter={form.chapter} />}
      {state.escalation && (
        <EscalationPanel
          form={form}
          escalation={state.escalation}
          attempts={state.attempts}
          onStart={onStart}
        />
      )}
    </main>
  );
}
