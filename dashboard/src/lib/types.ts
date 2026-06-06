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
