"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { CheckResult } from "@/lib/types";

// A tri-state PASS / FAIL / — glyph shared by every check surface (live escalation
// window, analytics run insights, doctor re-eval).
export function CheckStatus({ passed }: { passed: boolean | null | undefined }) {
  if (passed === true) return <span className="text-[10px] font-bold text-[var(--qm-green)]">✓ PASSED</span>;
  if (passed === false) return <span className="text-[10px] font-bold text-[var(--qm-red)]">✕ FAILED</span>;
  return <span className="text-[10px] font-bold text-muted-foreground">—</span>;
}

// A single check block: title + status, markdown feedback, and missing-concept /
// missing-skill chips. Used for generator checks and for doctor re-eval checks.
export function CheckSummary({ title, check }: { title: string; check: CheckResult | null | undefined }) {
  const passed = check?.passed;
  const feedback = check?.feedback ?? [];
  const missingConcepts = check?.missing_concepts ?? [];
  const missingSkills = check?.missing_skills ?? [];

  return (
    <div className="rounded border border-border bg-card/60 p-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-bold text-foreground/80">{title}</span>
        <CheckStatus passed={passed} />
      </div>

      {feedback.length > 0 && (
        <div className="md-feedback text-[11px] text-foreground/70">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{feedback.join("\n\n")}</ReactMarkdown>
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
