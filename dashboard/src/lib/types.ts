export interface Usage {
  input_tokens: number;
  output_tokens: number;
  cache_creation_input_tokens: number;
  cache_read_input_tokens: number;
}

// ─── Model selection ────────────────────────────────────────────────────────
// Mirrors the Gateway's /v1/models catalog (proxied through our backend's GET /models).

export interface ModelPricing {
  input?: string;
  output?: string;
  input_cache_read?: string;
  input_cache_write?: string;
}

export interface ModelInfo {
  id: string; // e.g. "anthropic/claude-sonnet-4-6", "openai/gpt-5-mini"
  name: string;
  owned_by: string;
  context_window: number;
  tags: string[]; // includes "tool-use" when the model supports forced tool calls
  pricing: ModelPricing;
}

// One entry per orchestrator.AGENT_KEYS — keep in sync with orchestrator.py.
export const AGENT_KEYS = [
  "map_extraction",
  "generator",
  "eval",
  "doctor",
  "rules_doctor",
  "revision",
  "judge",
  "prerequisite",
] as const;

export type AgentKey = (typeof AGENT_KEYS)[number];

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
  usage?: Usage;
  cost_usd?: number;
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

// ─── Structured run record (run.json) ──────────────────────────────────────
// Persisted for every run (pass or escalation), latest-only. Mirrors the backend
// skills/run_record.py schema. CSVs are referenced by pointer (CsvRef.file) and
// fetched lazily from /kb/analytics/chapter/run/file — never inlined here.

export interface CsvRef {
  file: string; // bare sibling filename, e.g. "gen_attempt_1.csv"
  rows?: number | null; // precomputed row count for the collapsed header
  label?: string; // optional display label
}

export type DoctorKind = "coverage" | "rules";

export interface DoctorGaps {
  missing_concepts?: string[];
  missing_skills?: string[];
  extra_concepts?: string[];
  extra_skills?: string[];
  violations?: string[];
}

export interface DoctorTrailEntry {
  kind: DoctorKind;
  chained_from: DoctorKind | null;
  gaps_addressed: DoctorGaps;
  csv_file: string | null; // null if the doctor errored / produced invalid CSV
  error: string | null;
  reeval: { check1: CheckResult | null; check2: CheckResult | null } | null;
  passed: boolean;
  regressed: boolean;
  regressed_concepts: string[];
  regressed_skills: string[];
  usage?: Usage;
  cost_usd?: number;
  model?: string | null;
}

export interface RunGenerator {
  csv_file: string;
  rows: number | null;
  check1: CheckResult | null;
  check2: CheckResult | null;
  passed: boolean;
  usage?: Usage;
  cost_usd?: number;
  model?: string | null;
}

export interface RunAttempt {
  attempt: number;
  input_type: string | null;
  prompt_file: string;
  generator: RunGenerator | null;
  doctors: DoctorTrailEntry[];
  revision: { usage: Usage; cost_usd: number; model?: string | null } | null;
  produced_candidate: boolean;
  attempt_usage?: Usage;
  attempt_cost_usd?: number;
}

export interface RunJudgeCandidate {
  id: string;
  source: string;
  cycle: number;
  csv_file: string;
  concept_count?: number | null;
  skill_count?: number | null;
  verdict?: string;
  note?: string;
  strengths?: string[];
  concerns?: string[];
}

export interface RunJudge {
  chosen_id: string | null;
  rationale: string | null;
  candidates: RunJudgeCandidate[];
  usage?: Usage;
  cost_usd?: number;
  model?: string | null;
}

export interface PipelineAgentUsage {
  usage: Usage;
  cost_usd: number;
  model?: string | null;
}

export interface ChapterRunRecord {
  schema_version: number;
  run_id: string;
  date: string;
  board: string;
  subject: string;
  grade: string;
  chapter: string;
  final_status: "passed" | "escalated";
  failed_check: string | null;
  mode: string;
  selected_by: "single" | "judge" | null;
  candidate_count: number;
  judge: RunJudge | null;
  final_csv_file: string | null;
  confirmed_checkpoint: boolean;
  has_prereqs: boolean;
  attempts: RunAttempt[];
  pipeline_agents?: {
    map_extraction?: PipelineAgentUsage;
    prerequisite?: PipelineAgentUsage;
  };
  total_usage?: Usage;
  total_cost_usd?: number;
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
  // Latest structured run; null for legacy chapters predating run records.
  run: ChapterRunRecord | null;
}

export interface StartRunOptions extends RunFormValues {
  humanFeedback?: string;
  mapGuidance?: string;
  rejectReason?: string;
  // When set, Stage 1 (generation) is skipped and only prerequisite mapping runs on
  // this CSV. board/subject/grade/chapter are derived server-side from the CSV.
  curriculumCsv?: string;
  // Per-agent model override (Gateway model id). Omitted keys fall back to the
  // pipeline default server-side. Not part of RunFormValues/QueueItem — batch-queued
  // chapters always use the pipeline default unless explicitly set here per-run.
  models?: Partial<Record<AgentKey, string>>;
}
