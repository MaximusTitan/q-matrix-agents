import type {
  AgentRecord,
  AttemptRecord,
  EscalationData,
  PipelineEvent,
  PipelineState,
  UsageMetrics,
} from "./types";

export const initialPipelineState: PipelineState = {
  runId: null,
  status: "idle",
  attempts: [],
  currentAttempt: 0,
  activeTab: 0,
  agents: [],
  csv: null,
  escalation: null,
  metrics: null,
};

export function reduceEvent(
  state: PipelineState,
  event: PipelineEvent
): PipelineState {
  const { type, data } = event;

  if (type === "heartbeat") {
    return state;
  }

  if (type === "pipeline_started") {
    return { ...state, status: "running" };
  }

  if (type === "attempt_started") {
    const attempt = data.attempt as number;
    const attempts = [...state.attempts];
    attempts[attempt - 1] = {
      attempt,
      agents: [],
      check1: null,
      check2: null,
    };
    return {
      ...state,
      currentAttempt: attempt,
      attempts,
      activeTab: attempt - 1,
    };
  }

  if (type === "agent_started") {
    const agent: AgentRecord = {
      name: data.agent as string,
      status: "running",
      input: (data.input as Record<string, unknown>) || {},
      output: null,
      parallel: (data.parallel as boolean) || false,
      attempt: state.currentAttempt,
    };
    const agents = [...state.agents, agent];
    const attempts = state.attempts.map((att, i) =>
      i === state.currentAttempt - 1
        ? { ...att, agents: [...att.agents, agent] }
        : att
    );
    return { ...state, agents, attempts };
  }

  if (type === "agent_completed") {
    const agentName = data.agent as string;
    const output = data.output as Record<string, unknown>;
    const agents = [...state.agents];
    for (let i = agents.length - 1; i >= 0; i--) {
      if (agents[i].name === agentName && agents[i].status === "running") {
        agents[i] = { ...agents[i], status: "done", output };
        break;
      }
    }
    const attempts = state.attempts.map((att) => ({
      ...att,
      agents: att.agents.map((ag) =>
        ag.name === agentName && ag.status === "running"
          ? { ...ag, status: "done" as const, output }
          : ag
      ),
    }));
    return { ...state, agents, attempts };
  }

  if (type === "pipeline_passed") {
    return {
      ...state,
      status: "passed",
      csv: data.csv as string,
      escalation: null,
      metrics: (data.metrics as UsageMetrics | undefined) ?? null,
      selectedBy: (data.selected_by as "single" | "judge" | undefined) ?? undefined,
      source: (data.source as "generated" | "doctored" | undefined) ?? undefined,
      candidateCount: (data.candidate_count as number | undefined) ?? undefined,
    };
  }

  if (type === "pipeline_escalated") {
    return {
      ...state,
      status: "escalated",
      escalation: data as EscalationData,
      metrics: (data.metrics as UsageMetrics | undefined) ?? null,
    };
  }

  if (type === "error") {
    return {
      ...state,
      status: "escalated",
      escalation: { error: data.message as string },
    };
  }

  return state;
}

export function getAttemptsWithEval(
  attempts: AttemptRecord[]
): AttemptRecord[] {
  return attempts.filter(
    (a) =>
      a &&
      a.agents &&
      a.agents.some((ag) => ag.name === "Eval" && ag.output)
  );
}
