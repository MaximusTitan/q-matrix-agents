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
  id: string; // e.g. "anthropic/claude-sonnet-5", "openai/gpt-5-mini"
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
  "prerequisite_l2",
  "prerequisite_l3",
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
  model?: string | null;
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
  // When set, this item runs L2 (cross-chapter) prerequisite mapping instead of
  // the full generate pipeline — mirrors StartRunOptions.l2Prerequisite.
  l2Prerequisite?: boolean;
  // When set, this item runs L3 (cross-grade) prerequisite mapping instead of
  // the full generate pipeline — mirrors StartRunOptions.l3Prerequisite.
  l3Prerequisite?: boolean;
  models?: Partial<Record<AgentKey, string>>;
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
  confirmed_l2_prereqs: number; // subset of `confirmed` that also has L2 mapped
  // Subset of `confirmed` that also has L3 mapped. NOT a subset of
  // confirmed_l2_prereqs — L3's eligibility gate only requires L1 (own grade +
  // every earlier grade), not L2, so a chapter can have L3 without L2.
  confirmed_l3_prereqs: number;
  escalated: number;
  mapped_only: number;
}

export interface AnalyticsChapter {
  chapter: string;
  status: ChapterStatus;
  has_prereqs: boolean;
  has_l2_prereqs: boolean;
  // True once an L2 run has completed for this chapter's current data, regardless
  // of whether it found any genuine cross-chapter prerequisite — distinguishes
  // "L2 ran, found nothing" from "L2 was never run" (both look like has_l2_prereqs
  // === false otherwise).
  l2_attempted: boolean;
  has_l3_prereqs: boolean;
  // L3 analogue of l2_attempted — distinguishes "L3 ran, found nothing" from
  // "L3 was never run".
  l3_attempted: boolean;
  escalation_count: number;
  latest_failed_check: string | null;
  attempts: number | null;
}

// ─── L2 (cross-chapter) prerequisite mapping ──────────────────────────────────

export interface L2EligibleChaptersResponse {
  eligible: boolean;
  blocking_chapters: string[];
  chapters: { chapter: string; has_l2_prereqs: boolean }[];
}

// ─── L3 (cross-grade) prerequisite mapping ────────────────────────────────────

export interface L3EligibleChaptersResponse {
  eligible: boolean;
  blocking_chapters: string[];
  // How many grades earlier than the target grade exist for this board+subject.
  // 0 means there is nothing to map against yet — the UI should show a
  // "no earlier grades" state rather than a blocking-chapters list.
  prior_grade_count: number;
  chapters: { chapter: string; has_l3_prereqs: boolean }[];
}

// ─── Prerequisite mapping edges (L1 within-chapter / L2 cross-chapter / L3 cross-grade) ─
// Shapes match agents/prerequisite.py, agents/prerequisite_l2.py, and
// agents/prerequisite_l3.py's `run()` output, forwarded verbatim through the
// "Prerequisites"/"PrerequisitesL2"/"PrerequisitesL3" agent_completed SSE event.
// Older confirmed CSVs predate the "reason" field (and, for L1, may still hold
// bare strings) — treat both as optional/absent.

export interface PrereqItem {
  item: string;
  reason?: string;
}

export interface L2Edge {
  chapter: string;
  concept?: string;
  skill?: string;
  reason?: string;
}

export interface L3Edge {
  grade: string;
  chapter: string;
  concept?: string;
  skill?: string;
  reason?: string;
}

export interface PrerequisiteAgentOutput {
  concept_edges?: Record<string, PrereqItem[]>;
  skill_edges?: Record<string, PrereqItem[]>;
  concept_edge_count?: number;
  skill_edge_count?: number;
  warnings?: string[];
  checkpoint?: string | null;
  usage?: Usage;
  cost_usd?: number;
  model?: string | null;
}

// Partitions every sibling chapter in the grade/subject into exactly one bucket —
// contributed a prerequisite, screened as related but contributed nothing, or
// never made it past the cheap relevance screen. Absent entirely on runs
// persisted before this was added (older run.json / older SSE payload) — treat
// "field is undefined" as "no breakdown data available", not "empty".
export interface L2ChapterBreakdown {
  chapters_with_edges?: string[];
  chapters_screened_no_edges?: string[];
  chapters_excluded_by_screen?: string[];
}

export interface PrerequisiteL2AgentOutput extends L2ChapterBreakdown {
  concept_edges?: Record<string, L2Edge[]>;
  skill_edges?: Record<string, L2Edge[]>;
  concept_edge_count?: number;
  skill_edge_count?: number;
  sibling_chapter_count?: number;
  candidate_chapter_count?: number;
  warnings?: string[];
  checkpoint?: string | null;
  usage?: Usage;
  cost_usd?: number;
  model?: string | null;
  error?: string;
}

// L3 analogue of L2ChapterBreakdown — grade-qualified since chapter names repeat
// across grades. Same "undefined = no breakdown data" vs "[] = empty bucket" rule.
export interface L3ChapterBreakdown {
  chapters_with_edges?: { grade: string; chapter: string }[];
  chapters_screened_no_edges?: { grade: string; chapter: string }[];
  chapters_excluded_by_screen?: { grade: string; chapter: string }[];
  prior_grade_count?: number;
}

export interface PrerequisiteL3AgentOutput extends L3ChapterBreakdown {
  concept_edges?: Record<string, L3Edge[]>;
  skill_edges?: Record<string, L3Edge[]>;
  concept_edge_count?: number;
  skill_edge_count?: number;
  sibling_chapter_count?: number;
  candidate_chapter_count?: number;
  warnings?: string[];
  checkpoint?: string | null;
  usage?: Usage;
  cost_usd?: number;
  model?: string | null;
  error?: string;
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

// ─── Model Performance ──────────────────────────────────────────────────────
// Rollup across every persisted run in the KB (backend: skills/model_stats.py),
// grouped by (agent, model) — which model configuration has actually performed
// best for each agent, and what it has cost so far.

export interface ModelPerformanceEntry {
  agent: AgentKey;
  model: string;
  runs: number;
  passed: number;
  escalated: number;
  pass_rate: number; // 0-1
  total_cost_usd: number;
  avg_cost_usd: number;
  avg_usage: Usage;
  avg_rows: number | null; // Generator only
  last_used: string | null; // ISO date
}

export interface ModelPerformanceProvider {
  provider: string;
  runs: number;
  total_cost_usd: number;
}

export interface ModelPerformanceResponse {
  total_runs: number;
  total_cost_usd: number;
  distinct_models: number;
  by_provider: ModelPerformanceProvider[];
  entries: ModelPerformanceEntry[];
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
    prerequisite_l2?: PipelineAgentUsage & L2ChapterBreakdown;
    prerequisite_l3?: PipelineAgentUsage & L3ChapterBreakdown;
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
    has_l2_prereqs: boolean;
    l2_attempted: boolean;
    has_l3_prereqs: boolean;
    l3_attempted: boolean;
  } | null;
  escalations: EscalationReport[];
  concept_skill_map: {
    concepts: string[];
    skills: string[];
  } | null;
  // One entry per pipeline stage that has actually been run (full L1 pipeline,
  // L1-only prerequisite mapping, L2, L3) — each stage's own latest run, never
  // overwritten by another stage. Empty for legacy chapters predating run records.
  runs: ChapterRunRecord[];
}

export interface StartRunOptions extends RunFormValues {
  humanFeedback?: string;
  mapGuidance?: string;
  rejectReason?: string;
  // When set, Stage 1 (generation) is skipped and only prerequisite mapping runs on
  // this CSV. board/subject/grade/chapter are derived server-side from the CSV.
  curriculumCsv?: string;
  // When set, runs L2 (cross-chapter) prerequisite mapping for the given
  // board/subject/grade/chapter instead of the full pipeline or L1 CSV mode.
  l2Prerequisite?: boolean;
  // When set, runs L3 (cross-grade) prerequisite mapping for the given
  // board/subject/grade/chapter instead of the full pipeline or L1/L2 CSV mode.
  l3Prerequisite?: boolean;
  // Per-agent model override (Gateway model id). Omitted keys fall back to the
  // pipeline default server-side. Not part of RunFormValues/QueueItem — batch-queued
  // chapters always use the pipeline default unless explicitly set here per-run.
  models?: Partial<Record<AgentKey, string>>;
}
