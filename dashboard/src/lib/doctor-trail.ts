// Adapters that normalise the two very different sources of doctor-trail data —
// a live SSE run's in-memory agent list, and a persisted run.json trail — into one
// view model (DoctorStepView) so a single <DoctorTrail> component renders both.

import type { AgentRecord, CheckResult, DoctorGaps, DoctorKind, DoctorTrailEntry, Usage } from "./types";
import type { CsvSourceInput } from "@/components/dashboard/shared/csv-entry";

export interface DoctorStepView {
  kind: DoctorKind;
  chainedFrom: DoctorKind | null;
  gaps: DoctorGaps;
  csv: CsvSourceInput | null; // null when the doctor produced no CSV (errored)
  error: string | null;
  check1: CheckResult | null;
  check2: CheckResult | null;
  passed: boolean;
  regressed: boolean;
  regressedConcepts: string[];
  regressedSkills: string[];
  usage?: Usage;
  costUsd?: number;
  model?: string | null;
}

// Historical (analytics) adapter: map each persisted trail entry, wiring its CSV as a
// lazily-fetched ref.
export function doctorStepsFromRecord(
  trail: DoctorTrailEntry[],
  loadCsv: (file: string) => Promise<string>
): DoctorStepView[] {
  return (trail ?? []).map((d) => ({
    kind: d.kind,
    chainedFrom: d.chained_from,
    gaps: d.gaps_addressed ?? {},
    csv: d.csv_file ? { kind: "ref", file: d.csv_file, load: loadCsv } : null,
    error: d.error,
    check1: d.reeval?.check1 ?? null,
    check2: d.reeval?.check2 ?? null,
    passed: d.passed,
    regressed: d.regressed,
    regressedConcepts: d.regressed_concepts ?? [],
    regressedSkills: d.regressed_skills ?? [],
    usage: d.usage,
    costUsd: d.cost_usd,
    model: d.model,
  }));
}

// Live adapter: walk an attempt's agents in order. Each "Doctor" / "Doctor (rules)"
// agent opens a step; the next "Eval (doctored)" agent supplies its re-eval checks.
export function doctorStepsFromAgents(agents: AgentRecord[]): DoctorStepView[] {
  const steps: DoctorStepView[] = [];

  for (const ag of agents ?? []) {
    if (ag.name === "Doctor" || ag.name === "Doctor (rules)") {
      const isRules = ag.name === "Doctor (rules)";
      const input = ag.input ?? {};
      const output = ag.output ?? {};
      const csvText = output.csv_preview as string | undefined;
      // A rules doctor that follows a coverage doctor within the same attempt is the
      // orchestrator's chain (coverage fixed Check 2 but broke Check 1).
      const chainedFrom: DoctorKind | null =
        isRules && steps.some((s) => s.kind === "coverage") ? "coverage" : null;

      steps.push({
        kind: isRules ? "rules" : "coverage",
        chainedFrom,
        gaps: {
          missing_concepts: (input.missing_concepts as string[]) ?? [],
          missing_skills: (input.missing_skills as string[]) ?? [],
          extra_concepts: (input.extra_concepts as string[]) ?? [],
          extra_skills: (input.extra_skills as string[]) ?? [],
          violations: (input.violations as string[]) ?? [],
        },
        csv: csvText ? { kind: "text", text: csvText, filename: "doctored.csv" } : null,
        error: (output.error as string) ?? null,
        usage: output.usage as Usage | undefined,
        costUsd: output.cost_usd as number | undefined,
        model: output.model as string | null | undefined,
        check1: null,
        check2: null,
        passed: false,
        regressed: false,
        regressedConcepts: [],
        regressedSkills: [],
      });
    } else if (ag.name === "Eval (doctored)" && ag.output) {
      // Attach re-eval to the most recent doctor step still lacking it.
      const step = [...steps].reverse().find((s) => s.check1 === null && s.check2 === null);
      if (step) {
        const c1 = (ag.output.check1 as CheckResult) ?? null;
        const c2 = (ag.output.check2 as CheckResult & {
          regressed?: boolean;
          regressed_concepts?: string[];
          regressed_skills?: string[];
        }) ?? null;
        step.check1 = c1;
        step.check2 = c2;
        step.passed = Boolean(c1?.passed && c2?.passed);
        step.regressed = Boolean(c2?.regressed);
        step.regressedConcepts = c2?.regressed_concepts ?? [];
        step.regressedSkills = c2?.regressed_skills ?? [];
      }
    }
  }

  return steps;
}
