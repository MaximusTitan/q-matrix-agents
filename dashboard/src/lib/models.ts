import type { ModelInfo } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

// Fetches the Gateway's model catalog via our backend's cached GET /models proxy
// (see api.py::list_models). Already filtered server-side to language models.
export async function fetchModels(): Promise<ModelInfo[]> {
  const res = await fetch(`${API_BASE}/models`);
  if (!res.ok) {
    throw new Error(`Failed to fetch model catalog: ${res.status}`);
  }
  const data = (await res.json()) as { models: ModelInfo[] };
  return data.models;
}

export function supportsToolUse(model: ModelInfo): boolean {
  return model.tags.includes("tool-use");
}

// Agents that force a single tool call for schema-shaped output — only these
// need supportsToolUse-filtered models; the rest parse plain-text/JSON responses.
export const TOOL_CALLING_AGENTS = new Set(["generator", "eval", "doctor", "rules_doctor"]);
