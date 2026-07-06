export type PipelineStatus = "idle" | "running" | "passed" | "escalated";

// Terminal outcome reported when a run finishes. Extends PipelineStatus with
// "error" for the case where the SSE connection drops before a terminal event.
export type RunOutcome = PipelineStatus | "error";

export type AgentStatus = "running" | "done";

export interface AgentRecord {
  name: string;
  status: AgentStatus;
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  parallel: boolean;
  attempt: number;
}

export interface CheckResult {
  passed?: boolean;
  feedback?: string[];
  missing_concepts?: string[];
  missing_skills?: string[];
  // Values are lists of the actual CSV item(s) that cover each expected item
  // (1:N union coverage). Older runs may have bare-string values.
  matched_concepts?: Record<string, string[] | string>;
  matched_skills?: Record<string, string[] | string>;
  // Actual CSV items not covering any expected item (computed in the backend).
  extra_concepts?: string[];
  extra_skills?: string[];
  // Pass-2 reconciliation audit trail: for each expected item that was first
  // marked missing but had a lexically-similar extra, the candidates + verdict.
  reconciliation?: Reconciliation;
}

export interface ReconciliationEntry {
  outcome: "recovered" | "rejected";
  candidates: { actual: string; score: number }[];
  covered_by: string[];
}

export interface Reconciliation {
  concepts: Record<string, ReconciliationEntry>;
  skills: Record<string, ReconciliationEntry>;
}

export interface AttemptRecord {
  attempt: number;
  agents: AgentRecord[];
  check1: CheckResult | null;
  check2: CheckResult | null;
}

export interface EscalationData {
  attempt?: number;
  failed_check?: string;
  folder?: string;
  last_feedback?: {
    check1?: string[];
    check2?: {
      feedback?: string[];
      missing_concepts?: string[];
      missing_skills?: string[];
    };
  };
  error?: string;
}

export interface PipelineState {
  runId: string | null;
  status: PipelineStatus;
  attempts: AttemptRecord[];
  currentAttempt: number;
  activeTab: number;
  agents: AgentRecord[];
  csv: string | null;
  escalation: EscalationData | null;
  // How the final CSV was selected among passing candidates.
  selectedBy?: "single" | "judge";
  source?: "generated" | "doctored" | "user_provided";
  candidateCount?: number;
}

export interface RunFormValues {
  board: string;
  subject: string;
  grade: string;
  chapter: string;
}

export type QueueItemStatus =
  | "pending"
  | "running"
  | "done"
  | "escalated"
  | "error";

// A chapter queued for a sequential Generate-from-KB run. Lives client-side;
// the queue drains one chapter at a time, advancing on each run's `done`
// event regardless of outcome (progress is persisted server-side in q-matrix-kb).
export interface QueueItem extends RunFormValues {
  id: string;
  status: QueueItemStatus;
}

export interface RunMetadata {
  run_id: string;
  board: string;
  subject: string;
  grade: string;
  chapter: string;
  status: string;
}

export interface PipelineEvent {
  type: string;
  data: Record<string, unknown>;
}

// ─── KB Analytics ─────────────────────────────────────────────────────────────
// Read-only pipeline history derived from the q-matrix-kb filesystem.

export type ChapterStatus = "confirmed" | "escalated" | "mapped";

export interface AnalyticsSummary {
  total_chapters: number;
  confirmed: number; // confirmed CSV WITH L1 prerequisites mapped
  confirmed_no_prereqs: number; // confirmed CSV but L1 columns empty
  escalated: number;
  mapped_only: number;
}

export interface AnalyticsChapter {
  chapter: string;
  status: ChapterStatus;
  has_prereqs: boolean;
  escalation_count: number;
  latest_failed_check: string | null;
  attempts: number | null;
}

export interface AnalyticsGroup {
  board: string;
  subject: string;
  grade: string;
  chapters: AnalyticsChapter[];
}

export interface AnalyticsResponse {
  summary: AnalyticsSummary;
  groups: AnalyticsGroup[];
}

export interface EscalationAttempt {
  attempt: number | null;
  input_type: string;
  check1_passed: boolean | null;
  check1_feedback: string[];
  check2_passed: boolean | null;
  check2_feedback: string[];
  missing_concepts: string[];
  missing_skills: string[];
}

export interface EscalationReport {
  folder: string;
  header: {
    board: string;
    subject: string;
    grade: string;
    chapter: string;
    date: string;
    failed_check: string;
    total_attempts: number | null;
  };
  attempts: EscalationAttempt[];
  files: string[];
  raw_report: string;
}

export interface ChapterAnalytics {
  board: string;
  subject: string;
  grade: string;
  chapter: string;
  confirmed: {
    csv_text: string;
    headers: string[];
    rows: Record<string, string>[];
    has_prereqs: boolean;
  } | null;
  escalations: EscalationReport[];
  concept_skill_map: {
    concepts: string[];
    skills: string[];
  } | null;
}

export interface StartRunOptions extends RunFormValues {
  humanFeedback?: string;
  mapGuidance?: string;
  rejectReason?: string;
  // When set, Stage 1 (generation) is skipped and only prerequisite mapping runs on
  // this CSV. board/subject/grade/chapter are derived server-side from the CSV.
  curriculumCsv?: string;
}
