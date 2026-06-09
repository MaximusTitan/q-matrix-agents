import type { RunFormValues, RunMetadata } from "./types";

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
  values: RunFormValues & { human_feedback?: string; no_sync?: boolean }
): Promise<{ run_id: string }> {
  return post("/run", { ...values, no_sync: true });
}

export async function postReject(
  values: RunFormValues & { reason: string; no_sync?: boolean }
): Promise<{ run_id: string }> {
  return post("/reject", { ...values, no_sync: true });
}

export async function postReExtract(
  values: RunFormValues & { map_guidance: string; no_sync?: boolean }
): Promise<{ run_id: string }> {
  return post("/re-extract", { ...values, no_sync: true });
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
