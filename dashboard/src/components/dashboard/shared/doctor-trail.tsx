"use client";

import type { DoctorStepView } from "@/lib/doctor-trail";
import { CheckStatus, CheckSummary } from "./check-summary";
import { CsvEntry } from "./csv-entry";

const KIND_LABEL: Record<string, string> = {
  coverage: "Coverage Doctor 🩺",
  rules: "Rules Doctor 🩹",
};

function GapChips({ label, items }: { label: string; items: string[] | undefined }) {
  if (!items || items.length === 0) return null;
  return (
    <div>
      <div className="mb-1 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">{label}</div>
      <div className="flex flex-wrap gap-1">
        {items.map((it, i) => (
          <span key={`${it}-${i}`} className="rounded bg-secondary px-1.5 py-0.5 text-[10px]">{it}</span>
        ))}
      </div>
    </div>
  );
}

function DoctorStep({ step }: { step: DoctorStepView }) {
  const { gaps } = step;
  const hasGaps =
    (gaps.missing_concepts?.length ?? 0) +
      (gaps.missing_skills?.length ?? 0) +
      (gaps.extra_concepts?.length ?? 0) +
      (gaps.extra_skills?.length ?? 0) +
      (gaps.violations?.length ?? 0) >
    0;

  return (
    <div className="rounded border border-[var(--qm-green)]/30 bg-card/60 p-3 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-bold text-foreground/80">{KIND_LABEL[step.kind] ?? step.kind}</span>
        {step.chainedFrom && (
          <span className="rounded bg-secondary px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-muted-foreground">
            chained from {step.chainedFrom}
          </span>
        )}
        <CheckStatus passed={step.error ? false : step.passed} />
        {step.regressed && (
          <span className="rounded bg-[var(--qm-red)]/15 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-[var(--qm-red)]">
            ⚠ regressed coverage
          </span>
        )}
      </div>

      {step.error && <div className="text-[11px] text-[var(--qm-red)]">{step.error}</div>}

      {hasGaps && (
        <div className="space-y-2">
          <GapChips label="Add missing concepts" items={gaps.missing_concepts} />
          <GapChips label="Add missing skills" items={gaps.missing_skills} />
          <GapChips label="Weigh extra concepts" items={gaps.extra_concepts} />
          <GapChips label="Weigh extra skills" items={gaps.extra_skills} />
          <GapChips label="Rule violations to fix" items={gaps.violations} />
        </div>
      )}

      {step.regressed && (step.regressedConcepts.length > 0 || step.regressedSkills.length > 0) && (
        <div className="space-y-2">
          <GapChips label="Regressed concepts" items={step.regressedConcepts} />
          <GapChips label="Regressed skills" items={step.regressedSkills} />
        </div>
      )}

      {step.csv && <CsvEntry source={step.csv} />}

      {(step.check1 || step.check2) && (
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
          <CheckSummary title="Check 1 — Universal Rules (re-eval)" check={step.check1} />
          <CheckSummary title="Check 2 — CSM Coverage (re-eval)" check={step.check2} />
        </div>
      )}
    </div>
  );
}

// Renders a doctor trail — one block per coverage / rules doctor pass — with the gaps
// it addressed, its patched CSV, and its re-eval status. Renders nothing when empty.
export function DoctorTrail({ steps }: { steps: DoctorStepView[] }) {
  if (!steps || steps.length === 0) return null;
  return (
    <div className="space-y-2">
      <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
        Doctor Trail
      </div>
      {steps.map((step, i) => (
        <DoctorStep key={i} step={step} />
      ))}
    </div>
  );
}
