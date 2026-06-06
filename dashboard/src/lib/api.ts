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
