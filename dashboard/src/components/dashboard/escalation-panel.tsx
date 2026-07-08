"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { AttemptRecord, CheckResult, EscalationData, RunFormValues, StartRunOptions } from "@/lib/types";
import { cn } from "@/lib/utils";
import { DoctorTrail } from "./shared/doctor-trail";
import { doctorStepsFromAgents } from "@/lib/doctor-trail";

interface EscalationPanelProps {
  form: RunFormValues;
  escalation: EscalationData;
  attempts: AttemptRecord[];
  onStart: (options: StartRunOptions) => void;
}

// ── Per-check block ────────────────────────────────────────────────────────────

function CheckBlock({ title, check }: { title: string; check: CheckResult | undefined }) {
  const passed = check?.passed;
  const feedback = check?.feedback ?? [];
  const missingConcepts = check?.missing_concepts ?? [];
  const missingSkills = check?.missing_skills ?? [];

  return (
    <div className="rounded border border-border bg-card/60 p-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-bold text-foreground/80">{title}</span>
        {passed !== undefined && (
          <span className={cn(
            "text-[10px] font-bold",
            passed ? "text-[var(--qm-green)]" : "text-[var(--qm-red)]"
          )}>
            {passed ? "✓ PASSED" : "✗ FAILED"}
          </span>
        )}
      </div>

      {feedback.length > 0 && (
        <div className="md-feedback text-[11px] text-foreground/70">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {feedback.join("\n\n")}
          </ReactMarkdown>
        </div>
      )}

      {missingConcepts.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
            Missing Concepts
          </div>
          <div className="flex flex-wrap gap-1">
            {missingConcepts.map((c) => (
              <span key={c} className="rounded bg-secondary px-1.5 py-0.5 text-[10px]">{c}</span>
            ))}
          </div>
        </div>
      )}

      {missingSkills.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
            Missing Skills
          </div>
          <div className="flex flex-wrap gap-1">
            {missingSkills.map((s) => (
              <span key={s} className="rounded bg-secondary px-1.5 py-0.5 text-[10px]">{s}</span>
            ))}
          </div>
        </div>
      )}

      {passed && !feedback.length && !missingConcepts.length && !missingSkills.length && (
        <div className="text-[11px] text-[var(--qm-green)]">All checks passed</div>
      )}
    </div>
  );
}

// ── Failure details (full report across all attempts) ─────────────────────────

function FailureDetails({
  escalation,
  attempts,
}: {
  escalation: EscalationData;
  attempts: AttemptRecord[];
}) {
  const [open, setOpen] = useState(true); // open by default — user needs this context

  // Pull eval results + the doctor trail from each attempt's agent list.
  const attemptReports = attempts
    .filter((a) => a && a.agents)
    .map((a) => {
      const evalAgent = a.agents.find((ag) => ag.name === "Eval" && ag.output);
      const c1 = evalAgent?.output?.check1 as CheckResult | undefined;
      const c2 = evalAgent?.output?.check2 as CheckResult | undefined;
      return { attempt: a.attempt, c1, c2, doctorSteps: doctorStepsFromAgents(a.agents) };
    })
    .filter(({ c1, c2, doctorSteps }) => c1 !== undefined || c2 !== undefined || doctorSteps.length > 0);

  const hasContent = escalation.error || attemptReports.length > 0;
  if (!hasContent) return null;

  return (
    <div className="mb-3 rounded border border-[var(--qm-red)]/30 bg-card overflow-hidden">
      <button
        onClick={() => setOpen((p) => !p)}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-muted-foreground hover:text-foreground transition-colors"
      >
        {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        Why it escalated
        {escalation.failed_check && (
          <span className="ml-1 font-normal normal-case text-[var(--qm-red)]">
            — {escalation.failed_check} failed after {escalation.attempt} attempt{escalation.attempt !== 1 ? "s" : ""}
          </span>
        )}
      </button>

      {open && (
        <div className="thin-scroll max-h-[480px] overflow-y-auto border-t border-[var(--qm-red)]/20 px-3 py-3 space-y-4">
          {escalation.error && (
            <p className="text-[11px] text-[var(--qm-red)]">{escalation.error}</p>
          )}

          {attemptReports.map(({ attempt, c1, c2, doctorSteps }) => (
            <div key={attempt} className="space-y-3">
              <div className="mb-2 flex items-center gap-2">
                <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                  Cycle {attempt}
                </span>
                <span className={cn(
                  "text-[10px] font-bold",
                  c1?.passed && c2?.passed ? "text-[var(--qm-green)]" : "text-[var(--qm-red)]"
                )}>
                  {c1?.passed && c2?.passed ? "✓ Passed" : "✗ Failed"}
                </span>
              </div>
              <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                <CheckBlock title="Check 1 — Universal Rules" check={c1} />
                <CheckBlock title="Check 2 — CSM Coverage" check={c2} />
              </div>
              <DoctorTrail steps={doctorSteps} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export function EscalationPanel({ form, escalation, attempts, onStart }: EscalationPanelProps) {
  const [feedback, setFeedback] = useState("");
  const [mapGuidance, setMapGuidance] = useState("");
  const [rejectReason, setRejectReason] = useState("");

  const resumeWithFeedback = () => {
    if (!feedback.trim()) { alert("Please enter feedback."); return; }
    onStart({ ...form, humanFeedback: feedback.trim() });
  };

  const reExtract = () => {
    if (!mapGuidance.trim()) { alert("Please enter map guidance."); return; }
    onStart({ ...form, mapGuidance: mapGuidance.trim() });
  };

  const rejectRun = () => {
    if (!rejectReason.trim()) { alert("Please enter a rejection reason."); return; }
    onStart({ ...form, rejectReason: rejectReason.trim() });
  };

  return (
    <Alert className="border-[var(--qm-red)] bg-[var(--qm-red)]/10">
      <AlertTitle className="text-sm font-bold text-[var(--qm-red)]">
        ⚠ Escalation Required
      </AlertTitle>
      <AlertDescription>
        <div className="mt-3 space-y-3">
          <FailureDetails escalation={escalation} attempts={attempts} />

          <div className="rounded border border-border bg-card p-3">
            <div className="mb-2 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
              Option A — Human Feedback
            </div>
            <Textarea
              placeholder="e.g. Focus on covering all concepts including amplitude, frequency, and time period."
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              className="mb-2 min-h-[60px] bg-secondary text-xs"
            />
            <Button size="sm" className="text-xs" onClick={resumeWithFeedback}>
              ▶ Resume with Feedback
            </Button>
          </div>

          <div className="rounded border border-border bg-card p-3">
            <div className="mb-2 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
              Option B — Re-Extract Concept Map
            </div>
            <Textarea
              placeholder="e.g. Extract only concepts explicitly listed as NCERT learning objectives."
              value={mapGuidance}
              onChange={(e) => setMapGuidance(e.target.value)}
              className="mb-2 min-h-[60px] bg-secondary text-xs"
            />
            <Button
              size="sm"
              variant="secondary"
              className="text-xs text-[var(--qm-purple)]"
              onClick={reExtract}
            >
              ↺ Re-Extract + Re-Run
            </Button>
          </div>

          <div className="rounded border border-border bg-card p-3">
            <div className="mb-2 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
              Option C — Reject + Encode Grade Rule
            </div>
            <Textarea
              placeholder="e.g. Maximum 3 skills per concept"
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              className="mb-2 min-h-[60px] bg-secondary text-xs"
            />
            <Button size="sm" variant="destructive" className="text-xs" onClick={rejectRun}>
              ✗ Reject + Re-Run
            </Button>
          </div>
        </div>
      </AlertDescription>
    </Alert>
  );
}
