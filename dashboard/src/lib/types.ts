export type PipelineStatus = "idle" | "running" | "passed" | "escalated";

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
  source?: "generated" | "doctored";
  candidateCount?: number;
}

export interface RunFormValues {
  board: string;
  subject: string;
  grade: string;
  chapter: string;
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

export interface StartRunOptions extends RunFormValues {
  humanFeedback?: string;
  mapGuidance?: string;
  rejectReason?: string;
}
