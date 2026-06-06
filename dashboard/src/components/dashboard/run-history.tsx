import { ScrollArea } from "@/components/ui/scroll-area";
import type { RunMetadata } from "@/lib/types";

interface RunHistoryProps {
  runs: RunMetadata[];
}

function statusIcon(status: string) {
  if (status === "passed") return <span className="text-[var(--qm-green)]">✓</span>;
  if (status === "escalated") return <span className="text-[var(--qm-red)]">⚠</span>;
  return <span className="text-[var(--qm-amber)]">⟳</span>;
}

export function RunHistory({ runs }: RunHistoryProps) {
  const sorted = [...runs].reverse();

  return (
    <div className="flex min-h-0 flex-1 flex-col p-4">
      <div className="mb-3 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
        Recent Runs
      </div>
      <ScrollArea className="flex-1">
        {!sorted.length ? (
          <div className="text-[11px] text-muted-foreground">No runs yet</div>
        ) : (
          <div className="space-y-1">
            {sorted.map((r) => (
              <div
                key={r.run_id}
                className="flex items-start gap-2 rounded border border-transparent px-2 py-1.5 hover:border-border hover:bg-secondary/50"
              >
                <span className="mt-0.5 text-xs">{statusIcon(r.status)}</span>
                <div className="min-w-0">
                  <div className="truncate text-xs font-medium">{r.chapter}</div>
                  <div className="truncate text-[10px] text-muted-foreground">
                    {r.subject} · {r.grade} · {r.run_id}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </ScrollArea>
    </div>
  );
}
