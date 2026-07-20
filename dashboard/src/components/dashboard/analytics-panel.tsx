"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Copy, Download, X } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { copyCsv, downloadCsv } from "@/lib/csv-actions";
import { fetchRunCsv, type AnalyticsFilters } from "@/lib/api";
import { doctorStepsFromRecord } from "@/lib/doctor-trail";
import { sumUsage } from "@/lib/usage";
import { cn } from "@/lib/utils";
import type {
  AnalyticsChapter,
  AnalyticsResponse,
  ChapterAnalytics,
  ChapterRunRecord,
  ChapterStatus,
  EscalationAttempt,
  EscalationReport,
  ModelPerformanceResponse,
  RunAttempt,
} from "@/lib/types";
import { CheckStatus, CheckSummary } from "./shared/check-summary";
import { CsvEntry } from "./shared/csv-entry";
import { DoctorTrail } from "./shared/doctor-trail";
import { ModelPerformancePanel } from "./model-performance-panel";
import { AnalyticsFilterBar, type AnalyticsFolderOptions } from "./analytics-filter-bar";
import { UsageBadge } from "./shared/usage-badge";

export interface SelectedChapter {
  board: string;
  subject: string;
  grade: string;
  chapter: string;
}

interface AnalyticsPanelProps {
  data: AnalyticsResponse | null;
  loading: boolean;
  error: string | null;
  modelPerformance: ModelPerformanceResponse | null;
  filters: AnalyticsFilters;
  onFiltersChange: (filters: AnalyticsFilters) => void;
  folderOptions: AnalyticsFolderOptions;
  allModelOptions: string[];
  selected: SelectedChapter | null;
  detail: ChapterAnalytics | null;
  detailLoading: boolean;
  detailError: string | null;
  onSelect: (chapter: SelectedChapter) => void;
  onClear: () => void;
}

// ─── Status presentation ───────────────────────────────────────────────────────

const STATUS_META: Record<
  ChapterStatus,
  { glyph: string; color: string; label: string }
> = {
  confirmed: { glyph: "✓", color: "var(--qm-green)", label: "Confirmed" },
  escalated: { glyph: "✕", color: "var(--qm-red)", label: "Escalated" },
  mapped: { glyph: "◔", color: "var(--qm-amber)", label: "Mapped only" },
};

function StatusGlyph({ status }: { status: ChapterStatus }) {
  const meta = STATUS_META[status];
  return (
    <span style={{ color: meta.color }} title={meta.label}>
      {meta.glyph}
    </span>
  );
}

function checkGlyph(passed: boolean | null) {
  if (passed === true)
    return <span className="text-[var(--qm-green)]">✓ PASSED</span>;
  if (passed === false)
    return <span className="text-[var(--qm-red)]">✕ FAILED</span>;
  return <span className="text-muted-foreground">—</span>;
}

// ─── Summary stat tiles ─────────────────────────────────────────────────────────

function StatTile({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color?: string;
}) {
  return (
    <div className="flex min-w-[110px] flex-1 flex-col gap-1 rounded-lg border border-border bg-card px-4 py-3">
      <span
        className="text-2xl font-bold tabular-nums"
        style={color ? { color } : undefined}
      >
        {value}
      </span>
      <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
        {label}
      </span>
    </div>
  );
}

function SummaryRow({ data }: { data: AnalyticsResponse }) {
  const s = data.summary;
  const attempted = s.total_chapters;
  const succeeded = s.confirmed + s.confirmed_no_prereqs;
  const rate = attempted ? Math.round((succeeded / attempted) * 100) : 0;
  return (
    <div className="flex flex-wrap gap-3">
      <StatTile label="Chapters attempted" value={s.total_chapters} />
      <StatTile label="Confirmed · L1 mapped" value={s.confirmed} color="var(--qm-green)" />
      {s.confirmed_no_prereqs > 0 && (
        <StatTile
          label="Confirmed · no prereqs"
          value={s.confirmed_no_prereqs}
          color="var(--qm-blue)"
        />
      )}
      <StatTile label="Escalated" value={s.escalated} color="var(--qm-red)" />
      <StatTile label="Mapped only" value={s.mapped_only} color="var(--qm-amber)" />
      <StatTile label="Success rate %" value={rate} color="var(--qm-purple)" />
    </div>
  );
}

// ─── Grouped tree ───────────────────────────────────────────────────────────────

function ChapterRow({
  chapter,
  active,
  onClick,
}: {
  chapter: AnalyticsChapter;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2 rounded border px-2 py-1.5 text-left transition-colors",
        active
          ? "border-primary bg-secondary/60"
          : "border-transparent hover:border-border hover:bg-secondary/40"
      )}
    >
      <span className="text-xs">
        <StatusGlyph status={chapter.status} />
      </span>
      <span className="min-w-0 flex-1 truncate text-xs font-medium">
        {chapter.chapter}
      </span>
      {chapter.status === "confirmed" && !chapter.has_prereqs && (
        <span className="shrink-0 text-[10px] text-[var(--qm-blue)]">no prereqs</span>
      )}
      {chapter.status === "escalated" && chapter.latest_failed_check && (
        <span className="shrink-0 text-[10px] text-muted-foreground">
          {chapter.latest_failed_check}
          {chapter.escalation_count > 1 ? ` ·${chapter.escalation_count}×` : ""}
        </span>
      )}
    </button>
  );
}

function countByStatus(chapters: AnalyticsChapter[]): Record<ChapterStatus, number> {
  return chapters.reduce(
    (acc, c) => {
      acc[c.status] += 1;
      return acc;
    },
    { confirmed: 0, escalated: 0, mapped: 0 } as Record<ChapterStatus, number>
  );
}

function StatusCounts({ counts }: { counts: Record<ChapterStatus, number> }) {
  return (
    <span className="ml-auto flex items-center gap-2 text-[10px] tabular-nums">
      {counts.confirmed > 0 && (
        <span className="text-[var(--qm-green)]">✓ {counts.confirmed}</span>
      )}
      {counts.escalated > 0 && (
        <span className="text-[var(--qm-red)]">✕ {counts.escalated}</span>
      )}
      {counts.mapped > 0 && (
        <span className="text-[var(--qm-amber)]">◔ {counts.mapped}</span>
      )}
    </span>
  );
}

// Board → Subject → Grade tree built from the flat (board, subject, grade)
// group list the API returns, so each level can be collapsed independently.
interface GradeNode {
  grade: string;
  chapters: AnalyticsChapter[];
}
interface SubjectNode {
  subject: string;
  grades: GradeNode[];
}
interface BoardNode {
  board: string;
  subjects: SubjectNode[];
}

function buildBoardTree(groups: AnalyticsResponse["groups"]): BoardNode[] {
  const boards = new Map<string, Map<string, Map<string, AnalyticsChapter[]>>>();
  for (const g of groups) {
    const subjects = boards.get(g.board) ?? new Map();
    boards.set(g.board, subjects);
    const grades = subjects.get(g.subject) ?? new Map();
    subjects.set(g.subject, grades);
    grades.set(g.grade, g.chapters);
  }
  return Array.from(boards.entries()).map(([board, subjects]) => ({
    board,
    subjects: Array.from(subjects.entries()).map(([subject, grades]) => ({
      subject,
      grades: Array.from(grades.entries()).map(([grade, chapters]) => ({
        grade,
        chapters,
      })),
    })),
  }));
}

function GradeSection({
  board,
  subject,
  node,
  selected,
  onSelect,
}: {
  board: string;
  subject: string;
  node: GradeNode;
  selected: SelectedChapter | null;
  onSelect: (c: SelectedChapter) => void;
}) {
  const [open, setOpen] = useState(false);
  const counts = countByStatus(node.chapters);

  return (
    <div className="rounded-lg border border-border bg-card">
      <button
        onClick={() => setOpen((p) => !p)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
        )}
        <span className="text-xs font-bold tracking-wide">{node.grade}</span>
        <StatusCounts counts={counts} />
      </button>
      {open && (
        <div className="space-y-1 border-t border-border p-2">
          {node.chapters.map((c) => {
            const active =
              !!selected &&
              selected.board === board &&
              selected.subject === subject &&
              selected.grade === node.grade &&
              selected.chapter === c.chapter;
            return (
              <ChapterRow
                key={c.chapter}
                chapter={c}
                active={active}
                onClick={() =>
                  onSelect({
                    board,
                    subject,
                    grade: node.grade,
                    chapter: c.chapter,
                  })
                }
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

function SubjectSection({
  board,
  node,
  selected,
  onSelect,
}: {
  board: string;
  node: SubjectNode;
  selected: SelectedChapter | null;
  onSelect: (c: SelectedChapter) => void;
}) {
  const [open, setOpen] = useState(false);
  const counts = countByStatus(node.grades.flatMap((g) => g.chapters));

  return (
    <div className="rounded-lg border border-border bg-card">
      <button
        onClick={() => setOpen((p) => !p)}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
        )}
        <span className="text-xs font-bold tracking-wide">{node.subject}</span>
        <StatusCounts counts={counts} />
      </button>
      {open && (
        <div className="space-y-2 border-t border-border p-2">
          {node.grades.map((g) => (
            <GradeSection
              key={g.grade}
              board={board}
              subject={node.subject}
              node={g}
              selected={selected}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function BoardSection({
  node,
  selected,
  onSelect,
}: {
  node: BoardNode;
  selected: SelectedChapter | null;
  onSelect: (c: SelectedChapter) => void;
}) {
  const [open, setOpen] = useState(false);
  const counts = countByStatus(
    node.subjects.flatMap((s) => s.grades.flatMap((g) => g.chapters))
  );

  return (
    <div className="rounded-lg border border-border bg-card">
      <button
        onClick={() => setOpen((p) => !p)}
        className="flex w-full items-center gap-2 px-3 py-3 text-left"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
        )}
        <span className="text-sm font-bold tracking-wide">{node.board}</span>
        <StatusCounts counts={counts} />
      </button>
      {open && (
        <div className="space-y-2 border-t border-border p-2">
          {node.subjects.map((s) => (
            <SubjectSection
              key={s.subject}
              board={node.board}
              node={s}
              selected={selected}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Chapter drill-down detail ───────────────────────────────────────────────────

function Bullets({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <ul className="mt-1 space-y-1">
      {items.map((it, i) => (
        <li key={i} className="text-[11px] leading-relaxed text-muted-foreground">
          • {it}
        </li>
      ))}
    </ul>
  );
}

function AttemptCard({ attempt }: { attempt: EscalationAttempt }) {
  return (
    <div className="rounded border border-border bg-background p-3">
      <div className="mb-2 text-[11px] font-bold">
        Attempt {attempt.attempt}
        {attempt.input_type && (
          <span className="ml-2 font-normal text-muted-foreground">
            ({attempt.input_type})
          </span>
        )}
      </div>
      <div className="space-y-2 text-[11px]">
        <div>
          <span className="font-semibold">Check 1 · Universal Rules: </span>
          {checkGlyph(attempt.check1_passed)}
          <Bullets items={attempt.check1_feedback} />
        </div>
        <div>
          <span className="font-semibold">Check 2 · CSM Coverage: </span>
          {checkGlyph(attempt.check2_passed)}
          <Bullets items={attempt.check2_feedback} />
          {attempt.missing_concepts.length > 0 && (
            <div className="mt-1 text-[11px] text-muted-foreground">
              <span className="font-semibold text-foreground/80">Missing concepts:</span>{" "}
              {attempt.missing_concepts.join(", ")}
            </div>
          )}
          {attempt.missing_skills.length > 0 && (
            <div className="mt-1 text-[11px] text-muted-foreground">
              <span className="font-semibold text-foreground/80">Missing skills:</span>{" "}
              {attempt.missing_skills.join(", ")}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function EscalationCard({ report }: { report: EscalationReport }) {
  const [showRaw, setShowRaw] = useState(false);
  const h = report.header;
  return (
    <div className="rounded-lg border border-[var(--qm-red)]/40 bg-card">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-border px-4 py-3 text-[11px]">
        <span className="font-bold text-[var(--qm-red)]">Escalated</span>
        <span className="text-muted-foreground">{h.date}</span>
        <span>
          <span className="text-muted-foreground">Failed: </span>
          <span className="font-semibold">{h.failed_check || "—"}</span>
        </span>
        <span>
          <span className="text-muted-foreground">Attempts: </span>
          <span className="font-semibold">{h.total_attempts ?? "—"}</span>
        </span>
      </div>
      <div className="space-y-2 p-3">
        {report.attempts.map((a, i) => (
          <AttemptCard key={i} attempt={a} />
        ))}
      </div>
      <div className="border-t border-border px-4 py-2">
        <button
          onClick={() => setShowRaw((p) => !p)}
          className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground hover:text-foreground"
        >
          {showRaw ? "Hide" : "Show"} full report.md
        </button>
        {showRaw && (
          <pre className="mt-2 max-h-96 overflow-auto rounded border border-border bg-background p-3 text-[10px] leading-relaxed whitespace-pre-wrap">
            {report.raw_report}
          </pre>
        )}
      </div>
    </div>
  );
}

const L1_COLUMNS = [
  "prereq_concepts_L1_same_chapter",
  "prereq_skills_L1_same_chapter",
];

function renderCell(column: string, value: string) {
  if (L1_COLUMNS.includes(column)) {
    try {
      const arr = JSON.parse(value || "[]");
      if (Array.isArray(arr)) {
        if (!arr.length) return <span className="text-muted-foreground">—</span>;
        return (
          <span className="flex flex-wrap gap-1">
            {arr.map((v: string, i: number) => (
              <span
                key={i}
                className="rounded bg-secondary px-1.5 py-0.5 text-[10px]"
              >
                {v}
              </span>
            ))}
          </span>
        );
      }
    } catch {
      /* fall through to raw */
    }
  }
  return value;
}

function ConfirmedCard({
  detail,
  chapter,
}: {
  detail: NonNullable<ChapterAnalytics["confirmed"]>;
  chapter: string;
}) {
  return (
    <div className="rounded-lg border border-[var(--qm-green)]/40 bg-card">
      <div className="flex items-center gap-3 border-b border-border px-4 py-3 text-[11px]">
        <span className="font-bold text-[var(--qm-green)]">Confirmed CSV</span>
        <span className="text-muted-foreground">
          {detail.rows.length} row{detail.rows.length !== 1 ? "s" : ""}
        </span>
        {!detail.has_prereqs && (
          <span className="text-[var(--qm-blue)]">L1 prerequisites not mapped</span>
        )}
        <div className="ml-auto flex gap-1">
          <button
            onClick={() => copyCsv(detail.csv_text)}
            title="Copy CSV"
            className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground"
          >
            <Copy className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => downloadCsv(detail.csv_text, `${chapter}_confirmed.csv`)}
            title="Download CSV"
            className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground"
          >
            <Download className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[11px]">
          <thead>
            <tr className="border-b border-border">
              {detail.headers.map((col) => (
                <th
                  key={col}
                  className="whitespace-nowrap px-3 py-2 text-left font-semibold text-muted-foreground"
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {detail.rows.map((row, i) => (
              <tr key={i} className="border-b border-border/50 align-top">
                {detail.headers.map((col) => (
                  <td key={col} className="px-3 py-2">
                    {renderCell(col, row[col] ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ConceptSkillMapCard({
  csm,
}: {
  csm: NonNullable<ChapterAnalytics["concept_skill_map"]>;
}) {
  return (
    <div className="rounded-lg border border-[var(--qm-amber)]/40 bg-card">
      <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3 text-[11px]">
        <span className="font-bold text-[var(--qm-amber)]">Concept-Skill Map</span>
        <span className="text-muted-foreground">
          {csm.concepts.length} concept{csm.concepts.length !== 1 ? "s" : ""} ·{" "}
          {csm.skills.length} skill{csm.skills.length !== 1 ? "s" : ""}
        </span>
      </div>
      <div className="grid grid-cols-1 gap-4 p-4 md:grid-cols-2">
        <div>
          <div className="mb-2 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
            Concepts
          </div>
          <ul className="space-y-1">
            {csm.concepts.map((c, i) => (
              <li key={i} className="text-[11px] leading-relaxed">
                • {c}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="mb-2 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
            Skills
          </div>
          <ul className="space-y-1">
            {csm.skills.map((s, i) => (
              <li key={i} className="text-[11px] leading-relaxed">
                • {s}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

// ─── Structured run insights (every CSV + checks + doctor trail) ────────────────

function AttemptInsightCard({
  attempt,
  loadCsv,
}: {
  attempt: RunAttempt;
  loadCsv: (file: string) => Promise<string>;
}) {
  const gen = attempt.generator;
  const doctorSteps = doctorStepsFromRecord(attempt.doctors, loadCsv);
  return (
    <div className="space-y-3 rounded border border-border bg-background p-3">
      <div className="flex items-center gap-2 text-[11px] font-bold">
        <span>
          Attempt {attempt.attempt}
          {attempt.input_type && (
            <span className="ml-2 font-normal text-muted-foreground">({attempt.input_type})</span>
          )}
        </span>
        <UsageBadge usage={attempt.attempt_usage} costUsd={attempt.attempt_cost_usd} />
      </div>

      {gen && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
              Generator
            </span>
            <UsageBadge usage={gen.usage} costUsd={gen.cost_usd} model={gen.model} />
          </div>
          <CsvEntry
            source={{
              kind: "ref",
              file: gen.csv_file,
              rows: gen.rows,
              label: "Generator CSV",
              load: loadCsv,
            }}
          />
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
              Eval
            </span>
            <UsageBadge
              usage={sumUsage([gen.check1?.usage, gen.check2?.usage])}
              costUsd={(gen.check1?.cost_usd ?? 0) + (gen.check2?.cost_usd ?? 0)}
              model={gen.check1?.model ?? gen.check2?.model}
            />
          </div>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            <CheckSummary title="Check 1 — Universal Rules" check={gen.check1} />
            <CheckSummary title="Check 2 — CSM Coverage" check={gen.check2} />
          </div>
        </div>
      )}

      <DoctorTrail steps={doctorSteps} />

      {attempt.revision && (
        <div className="flex items-center justify-between rounded border border-border bg-card/60 px-3 py-2">
          <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
            Revision
          </span>
          <UsageBadge
            usage={attempt.revision.usage}
            costUsd={attempt.revision.cost_usd}
            model={attempt.revision.model}
          />
        </div>
      )}
    </div>
  );
}

function RunInsightsCard({
  run,
  selected,
}: {
  run: ChapterRunRecord;
  selected: SelectedChapter;
}) {
  const [showRationale, setShowRationale] = useState(false);
  const loadCsv = (file: string) =>
    fetchRunCsv(selected.board, selected.subject, selected.grade, selected.chapter, file);

  const passed = run.final_status === "passed";
  const accent = passed ? "var(--qm-green)" : "var(--qm-red)";

  return (
    <div className="rounded-lg border bg-card" style={{ borderColor: `color-mix(in srgb, ${accent} 40%, transparent)` }}>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-border px-4 py-3 text-[11px]">
        <span className="font-bold" style={{ color: accent }}>
          Run Insights — {passed ? "Passed" : "Escalated"}
        </span>
        <span className="text-muted-foreground">{run.date}</span>
        <span>
          <span className="text-muted-foreground">Attempts: </span>
          <span className="font-semibold">{run.attempts.length}</span>
        </span>
        <UsageBadge usage={run.total_usage} costUsd={run.total_cost_usd} />
        {run.selected_by && (
          <span>
            <span className="text-muted-foreground">Selected by: </span>
            <span className="font-semibold">
              {run.selected_by}
              {run.selected_by === "judge" && ` (of ${run.candidate_count})`}
            </span>
          </span>
        )}
        {run.selected_by === "judge" && (
          <UsageBadge usage={run.judge?.usage} costUsd={run.judge?.cost_usd} model={run.judge?.model} />
        )}
        {run.judge?.rationale && (
          <button
            onClick={() => setShowRationale((p) => !p)}
            className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground hover:text-foreground"
          >
            {showRationale ? "Hide" : "Show"} judge rationale
          </button>
        )}
      </div>

      {(run.pipeline_agents?.map_extraction || run.pipeline_agents?.prerequisite) && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-border px-4 py-2 text-[11px]">
          {run.pipeline_agents?.map_extraction && (
            <span className="flex items-center gap-1.5">
              <span className="text-muted-foreground">Map Extraction:</span>
              <UsageBadge
                usage={run.pipeline_agents.map_extraction.usage}
                costUsd={run.pipeline_agents.map_extraction.cost_usd}
                model={run.pipeline_agents.map_extraction.model}
              />
            </span>
          )}
          {run.pipeline_agents?.prerequisite && (
            <span className="flex items-center gap-1.5">
              <span className="text-muted-foreground">Prerequisites:</span>
              <UsageBadge
                usage={run.pipeline_agents.prerequisite.usage}
                costUsd={run.pipeline_agents.prerequisite.cost_usd}
                model={run.pipeline_agents.prerequisite.model}
              />
            </span>
          )}
        </div>
      )}

      {showRationale && run.judge?.rationale && (
        <div className="border-b border-border px-4 py-2 text-[11px] leading-relaxed text-foreground/70">
          {run.judge.rationale}
        </div>
      )}

      <div className="space-y-2 p-3">
        {run.attempts.map((a) => (
          <AttemptInsightCard key={a.attempt} attempt={a} loadCsv={loadCsv} />
        ))}

        {run.final_csv_file && (
          <div className="rounded border border-[var(--qm-green)]/30 bg-background p-3">
            <div className="mb-2 flex items-center gap-2 text-[11px] font-bold">
              Final CSV
              <CheckStatus passed={passed ? true : null} />
            </div>
            <CsvEntry
              source={{
                kind: "ref",
                file: run.final_csv_file,
                label: passed ? "Confirmed (final)" : "Last CSV (final)",
                load: loadCsv,
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function DetailView({
  selected,
  detail,
  loading,
  error,
  onClear,
}: {
  selected: SelectedChapter;
  detail: ChapterAnalytics | null;
  loading: boolean;
  error: string | null;
  onClear: () => void;
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="mb-3 flex items-start gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-bold">{selected.chapter}</div>
          <div className="truncate text-[11px] text-muted-foreground">
            {selected.board} · {selected.subject} · {selected.grade}
          </div>
        </div>
        <button
          onClick={onClear}
          title="Close detail"
          className="ml-auto rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        {loading && (
          <div className="text-[11px] text-muted-foreground">Loading detail…</div>
        )}
        {error && <div className="text-[11px] text-[var(--qm-red)]">{error}</div>}
        {detail && (
          <div className="space-y-4 pr-2">
            {detail.confirmed && (
              <ConfirmedCard detail={detail.confirmed} chapter={selected.chapter} />
            )}
            {/* Structured run insights (every CSV + checks + doctor trail) for both
                passing and escalated chapters once a run.json exists. */}
            {detail.run && <RunInsightsCard run={detail.run} selected={selected} />}
            {/* Legacy escalation view only for chapters predating run records. */}
            {!detail.run &&
              detail.escalations.map((r) => (
                <EscalationCard key={r.folder} report={r} />
              ))}
            {!detail.confirmed && !detail.run && !detail.escalations.length && (
              <div className="text-[11px] text-muted-foreground">
                No confirmed CSV or escalation on record — reached concept-skill-map
                extraction only.
              </div>
            )}
            {detail.concept_skill_map && (
              <ConceptSkillMapCard csm={detail.concept_skill_map} />
            )}
          </div>
        )}
      </ScrollArea>
    </div>
  );
}

// ─── Top-level panel ─────────────────────────────────────────────────────────────

export function AnalyticsPanel({
  data,
  loading,
  error,
  modelPerformance,
  filters,
  onFiltersChange,
  folderOptions,
  allModelOptions,
  selected,
  detail,
  detailLoading,
  detailError,
  onSelect,
  onClear,
}: AnalyticsPanelProps) {
  if (loading) {
    return (
      <div className="p-6 text-sm text-muted-foreground">Loading analytics…</div>
    );
  }
  if (error) {
    return <div className="p-6 text-sm text-[var(--qm-red)]">{error}</div>;
  }

  const hasActiveFilter =
    !!filters.board || !!filters.subject || !!filters.grade || (filters.models?.length ?? 0) > 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-6 p-6">
      <AnalyticsFilterBar
        filters={filters}
        onFiltersChange={onFiltersChange}
        folderOptions={folderOptions}
        allModelOptions={allModelOptions}
      />
      {!data || !data.groups.length ? (
        <div className="text-sm text-muted-foreground">
          {hasActiveFilter
            ? "No chapters match the selected filters."
            : "No chapters have been run through the pipeline yet."}
        </div>
      ) : (
        <>
          <SummaryRow data={data} />
          <ModelPerformancePanel data={modelPerformance} />
          <div className="flex min-h-0 flex-1 gap-6">
            {/* Grouped tree */}
            <div
              className={cn(
                "min-h-0 flex-1",
                selected && "hidden lg:block lg:max-w-md lg:shrink-0"
              )}
            >
              <ScrollArea className="h-full">
                <div className="space-y-3 pr-2">
                  {buildBoardTree(data.groups).map((b) => (
                    <BoardSection
                      key={b.board}
                      node={b}
                      selected={selected}
                      onSelect={onSelect}
                    />
                  ))}
                </div>
              </ScrollArea>
            </div>

            {/* Drill-down */}
            {selected && (
              <div className="flex min-h-0 flex-1 flex-col">
                <DetailView
                  selected={selected}
                  detail={detail}
                  loading={detailLoading}
                  error={detailError}
                  onClear={onClear}
                />
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
