"use client";

import type { Usage } from "@/lib/types";
import { formatCost, formatTokens, hasUsage } from "@/lib/usage";

// Small token/cost pill shared by the live dashboard (agent-timeline) and the
// analytics dashboard (analytics-panel). Renders nothing when there's no usage
// to show (e.g. a run persisted before this feature, or an agent that made no
// LLM call — Judge on a single-candidate pass, a doctor that never ran).
export function UsageBadge({
  usage,
  costUsd,
}: {
  usage?: Usage | null;
  costUsd?: number | null;
}) {
  if (!hasUsage(usage)) return null;

  return (
    <span className="inline-flex items-center gap-1.5 text-[10px] font-bold whitespace-nowrap">
      <span className="text-muted-foreground">{formatTokens(usage)}</span>
      {costUsd != null && (
        <span className="text-[var(--qm-amber)]">{formatCost(costUsd)}</span>
      )}
    </span>
  );
}
