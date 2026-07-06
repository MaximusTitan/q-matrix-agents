import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { QueueItem, QueueItemStatus } from "@/lib/types";

interface QueuePanelProps {
  queue: QueueItem[];
  processing: boolean;
  // True whenever any run (queued or manual single run) is in progress.
  isRunning: boolean;
  onRun: () => void;
  onClear: () => void;
  onRemove: (id: string) => void;
}

function statusIcon(status: QueueItemStatus) {
  switch (status) {
    case "running":
      return <span className="text-[var(--qm-amber)]">▶</span>;
    case "done":
      return <span className="text-[var(--qm-green)]">✓</span>;
    case "escalated":
      return <span className="text-[var(--qm-red)]">⚠</span>;
    case "error":
      return <span className="text-[var(--qm-red)]">✕</span>;
    default:
      return <span className="text-muted-foreground">⟳</span>;
  }
}

export function QueuePanel({
  queue,
  processing,
  isRunning,
  onRun,
  onClear,
  onRemove,
}: QueuePanelProps) {
  // Keep the sidebar clean when nothing is queued.
  if (queue.length === 0) return null;

  const hasPending = queue.some((it) => it.status === "pending");

  return (
    <div className="flex flex-col border-b border-border p-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
          Queue ({queue.length})
        </div>
        <button
          onClick={onClear}
          disabled={!queue.some((it) => it.status !== "running")}
          className="text-[10px] font-bold uppercase tracking-wide text-muted-foreground hover:text-foreground disabled:opacity-40"
        >
          Clear
        </button>
      </div>

      <ScrollArea className="max-h-48">
        <div className="space-y-1">
          {queue.map((item) => (
            <div
              key={item.id}
              className="group flex items-start gap-2 rounded border border-transparent px-2 py-1.5 hover:border-border hover:bg-secondary/50"
            >
              <span className="mt-0.5 text-xs">{statusIcon(item.status)}</span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs font-medium">{item.chapter}</div>
                <div className="truncate text-[10px] text-muted-foreground">
                  {item.subject} · {item.grade}
                </div>
              </div>
              {item.status !== "running" && (
                <button
                  onClick={() => onRemove(item.id)}
                  className={cn(
                    "mt-0.5 text-xs text-muted-foreground opacity-0 transition-opacity",
                    "hover:text-[var(--qm-red)] group-hover:opacity-100"
                  )}
                  title="Remove from queue"
                >
                  ✕
                </button>
              )}
            </div>
          ))}
        </div>
      </ScrollArea>

      <Button
        className="mt-3 w-full text-xs font-bold"
        disabled={processing || isRunning || !hasPending}
        onClick={onRun}
      >
        {processing ? "⟳ Running Queue…" : "▶ Run Queue"}
      </Button>
    </div>
  );
}
