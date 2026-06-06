import type { PipelineStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

interface HeaderProps {
  status: PipelineStatus;
  runCount: number;
}

function statusLabel(status: PipelineStatus): string {
  if (status === "idle") return "Idle";
  return status.charAt(0).toUpperCase() + status.slice(1);
}

export function Header({ status, runCount }: HeaderProps) {
  const dotStatus =
    status === "running"
      ? "running"
      : status === "passed"
        ? "passed"
        : status === "escalated"
          ? "failed"
          : "idle";

  return (
    <header className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-card px-6 py-3.5">
      <div className="flex items-center gap-2.5 text-sm font-bold tracking-widest">
        <div
          className={cn(
            "h-2 w-2 rounded-full bg-muted-foreground transition-colors",
            dotStatus === "running" && "animate-pulse bg-[var(--qm-amber)]",
            dotStatus === "passed" && "bg-[var(--qm-green)]",
            dotStatus === "failed" && "bg-[var(--qm-red)]"
          )}
        />
        Q-MATRIX PIPELINE
      </div>
      <div className="flex items-center gap-4 text-xs text-muted-foreground">
        <span>
          {runCount} run{runCount !== 1 ? "s" : ""}
        </span>
        <span>{statusLabel(status)}</span>
      </div>
    </header>
  );
}
