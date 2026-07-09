import type {
  AgentKey,
  AnalyticsResponse,
  ChapterAnalytics,
  RunFormValues,
  RunMetadata,
} from "./types";

type ModelsOverride = { models?: Partial<Record<AgentKey, string>> };

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

async function post<T>(url: string, body: Record<string, unknown>): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`Request failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export function streamUrl(runId: string): string {
  return `${API_BASE}/stream/${runId}`;
}

export async function postRun(
  values: RunFormValues & { human_feedback?: string; no_sync?: boolean } & ModelsOverride
): Promise<{ run_id: string }> {
  return post("/run", { ...values, no_sync: true });
}

export async function postReject(
  values: RunFormValues & { reason: string; no_sync?: boolean } & ModelsOverride
): Promise<{ run_id: string }> {
  return post("/reject", { ...values, no_sync: true });
}

export async function postReExtract(
  values: RunFormValues & { map_guidance: string; no_sync?: boolean } & ModelsOverride
): Promise<{ run_id: string }> {
  return post("/re-extract", { ...values, no_sync: true });
}

export async function postRunPrerequisiteOnly(
  values: { csv_text: string; no_sync?: boolean } & ModelsOverride
): Promise<{ run_id: string }> {
  return post("/run-prerequisite-only", { ...values, no_sync: true });
}

export async function fetchRuns(): Promise<RunMetadata[]> {
  const res = await fetch(`${API_BASE}/runs`);
  if (!res.ok) {
    throw new Error(`Failed to fetch runs: ${res.status}`);
  }
  return res.json() as Promise<RunMetadata[]>;
}

export async function fetchKbBoards(): Promise<string[]> {
  const res = await fetch(`${API_BASE}/kb/boards`);
  if (!res.ok) return [];
  const data = (await res.json()) as { boards: string[] };
  return data.boards;
}

export async function fetchKbSubjects(board: string): Promise<string[]> {
  const params = new URLSearchParams({ board });
  const res = await fetch(`${API_BASE}/kb/subjects?${params}`);
  if (!res.ok) return [];
  const data = (await res.json()) as { subjects: string[] };
  return data.subjects;
}

export async function fetchKbGrades(board: string, subject: string): Promise<string[]> {
  const params = new URLSearchParams({ board, subject });
  const res = await fetch(`${API_BASE}/kb/grades?${params}`);
  if (!res.ok) return [];
  const data = (await res.json()) as { grades: string[] };
  return data.grades;
}

export async function fetchKbChapters(board: string, subject: string, grade: string): Promise<string[]> {
  const params = new URLSearchParams({ board, subject, grade });
  const res = await fetch(`${API_BASE}/kb/chapters?${params}`);
  if (!res.ok) return [];
  const data = (await res.json()) as { chapters: string[] };
  return data.chapters;
}

export async function fetchAnalytics(): Promise<AnalyticsResponse> {
  const res = await fetch(`${API_BASE}/kb/analytics`);
  if (!res.ok) {
    throw new Error(`Failed to fetch analytics: ${res.status}`);
  }
  return res.json() as Promise<AnalyticsResponse>;
}

export async function fetchChapterAnalytics(
  board: string,
  subject: string,
  grade: string,
  chapter: string
): Promise<ChapterAnalytics> {
  const params = new URLSearchParams({ board, subject, grade, chapter });
  const res = await fetch(`${API_BASE}/kb/analytics/chapter?${params}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch chapter analytics: ${res.status}`);
  }
  return res.json() as Promise<ChapterAnalytics>;
}

// Fetch one CSV / prompt sibling from a chapter's run/ folder. `file` must be a bare
// name from run.json's *_file pointers; the backend validates it against a whitelist.
export async function fetchRunCsv(
  board: string,
  subject: string,
  grade: string,
  chapter: string,
  file: string
): Promise<string> {
  const params = new URLSearchParams({ board, subject, grade, chapter, filename: file });
  const res = await fetch(`${API_BASE}/kb/analytics/chapter/run/file?${params}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch run CSV ${file}: ${res.status}`);
  }
  const data = (await res.json()) as { csv_text: string };
  return data.csv_text;
}
