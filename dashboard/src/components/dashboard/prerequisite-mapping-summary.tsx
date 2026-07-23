"use client";

import { AGENT_LABELS } from "@/lib/models";
import type {
  AgentRecord,
  L2Edge,
  L3Edge,
  PrereqItem,
  PrerequisiteAgentOutput,
  PrerequisiteL2AgentOutput,
  PrerequisiteL3AgentOutput,
} from "@/lib/types";
import { UsageBadge } from "./shared/usage-badge";
import { ChapterBreakdown } from "./shared/chapter-breakdown";

interface PrerequisiteMappingSummaryProps {
  agent: AgentRecord | undefined;
}

type AnyEdge = PrereqItem | L2Edge | L3Edge;

function isL3Entry(entry: AnyEdge): entry is L3Edge {
  return "grade" in entry && "chapter" in entry;
}

function isL2Entry(entry: AnyEdge): entry is L2Edge {
  return "chapter" in entry && !("grade" in entry);
}

function entryLabel(entry: AnyEdge): string {
  if (isL3Entry(entry)) {
    const item = entry.concept ?? entry.skill ?? "";
    return `${item} (from ${entry.chapter}, ${entry.grade})`;
  }
  if (isL2Entry(entry)) {
    const item = entry.concept ?? entry.skill ?? "";
    return `${item} (from ${entry.chapter})`;
  }
  return entry.item;
}

function EdgeGroup({
  title,
  edges,
}: {
  title: string;
  edges: Record<string, AnyEdge[]> | undefined;
}) {
  const entries = Object.entries(edges ?? {}).filter(([, v]) => v.length > 0);
  if (!entries.length) {
    return (
      <div>
        <div className="mb-1 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
          {title}
        </div>
        <div className="text-[11px] text-muted-foreground">No {title.toLowerCase()} found.</div>
      </div>
    );
  }
  return (
    <div>
      <div className="mb-1 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
        {title} ({entries.reduce((n, [, v]) => n + v.length, 0)})
      </div>
      <ul className="space-y-2">
        {entries.map(([target, prereqs]) => (
          <li key={target} className="text-[11px] leading-relaxed">
            <span className="font-semibold">{target}</span>
            <ul className="ml-4 mt-1 space-y-1">
              {prereqs.map((p, i) => (
                <li key={i} className="text-foreground/80">
                  <span className="text-muted-foreground">← </span>
                  {entryLabel(p)}
                  {p.reason && (
                    <div className="ml-4 text-[10px] italic text-muted-foreground">
                      {p.reason}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  );
}

// Surfaces exactly what a completed "Prerequisites"/"PrerequisitesL2"/
// "PrerequisitesL3" agent run mapped — the concept/skill edges plus each one's
// LLM-provided reasoning — so the user doesn't have to decode the JSON embedded
// in the CSV cells to see what happened. Rendered above the raw CSV preview.
export function PrerequisiteMappingSummary({ agent }: PrerequisiteMappingSummaryProps) {
  if (!agent || agent.status !== "done" || !agent.output) return null;

  const isL2 = agent.name === "PrerequisitesL2";
  const isL3 = agent.name === "PrerequisitesL3";
  const output = agent.output as PrerequisiteAgentOutput &
    PrerequisiteL2AgentOutput &
    PrerequisiteL3AgentOutput;
  if (output.error) return null;

  const hasEdges =
    Object.keys(output.concept_edges ?? {}).length > 0 ||
    Object.keys(output.skill_edges ?? {}).length > 0;

  const label = isL3
    ? AGENT_LABELS.prerequisite_l3
    : isL2
      ? AGENT_LABELS.prerequisite_l2
      : AGENT_LABELS.prerequisite;
  const scopeLabel = isL3 ? "cross-grade" : isL2 ? "cross-chapter" : "within-chapter";

  return (
    <div className="mb-6 rounded-md border border-border bg-card p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
          {label} — mapped
        </span>
        <UsageBadge usage={output.usage} costUsd={output.cost_usd} model={output.model} />
      </div>

      {(isL2 || isL3) && (
        <ChapterBreakdown
          withEdges={output.chapters_with_edges}
          screenedNoEdges={output.chapters_screened_no_edges}
          excludedByScreen={output.chapters_excluded_by_screen}
        />
      )}

      {hasEdges ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <EdgeGroup title="Concept prerequisites" edges={output.concept_edges} />
          <EdgeGroup title="Skill prerequisites" edges={output.skill_edges} />
        </div>
      ) : (
        <div className="text-[11px] text-muted-foreground">
          No {scopeLabel} prerequisites were found for this chapter.
        </div>
      )}

      {output.warnings && output.warnings.length > 0 && (
        <div className="mt-3 border-t border-border pt-2 text-[10px] text-muted-foreground">
          {output.warnings.length} warning{output.warnings.length !== 1 ? "s" : ""} during
          mapping.
        </div>
      )}
    </div>
  );
}
