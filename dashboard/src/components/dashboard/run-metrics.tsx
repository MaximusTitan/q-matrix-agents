import type { UsageMetrics } from "@/lib/types";

interface RunMetricsProps {
  metrics: UsageMetrics | null | undefined;
}

export function RunMetrics({ metrics }: RunMetricsProps) {
  if (!metrics) {
    return null;
  }

  return (
    <div className="rounded border border-border bg-secondary/50 p-4 text-xs text-foreground">
      <div className="mb-2 font-semibold uppercase tracking-[0.24em] text-muted-foreground">
        Run Statistics
      </div>
      <div className="grid gap-2 text-[11px]">
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">Input Tokens</span>
          <span className="font-semibold">{metrics.prompt_tokens}</span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">Output Tokens</span>
          <span className="font-semibold">{metrics.completion_tokens}</span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">Total Tokens</span>
          <span className="font-semibold">{metrics.total_tokens}</span>
        </div>
        <div className="flex justify-between gap-4 border-t border-border pt-2">
          <span className="text-muted-foreground">Estimated Cost</span>
          <span className="font-semibold">${metrics.cost.toFixed(4)}</span>
        </div>
      </div>
    </div>
  );
}
