"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  QueueItem,
  RunFormValues,
  RunOutcome,
  StartRunOptions,
} from "@/lib/types";

interface UseChapterQueueArgs {
  startRun: (options: StartRunOptions) => void;
  isRunning: boolean;
}

// Monotonic id source. Avoids Math.random / Date.now (unstable across renders and
// disallowed in some execution contexts) — a plain counter is enough for the UI.
let idCounter = 0;
const nextId = () => `q${++idCounter}`;

// Map a run's terminal outcome onto the queue item's display status.
function outcomeToStatus(outcome: RunOutcome): QueueItem["status"] {
  if (outcome === "passed") return "done";
  if (outcome === "escalated") return "escalated";
  return "error";
}

/**
 * Client-side sequential queue for Generate-from-KB runs.
 *
 * Drains one chapter at a time by driving `startRun`. Advancement is triggered by
 * `handleRunComplete`, which the owner wires to `usePipeline`'s `onRunComplete` so it
 * fires on every terminal outcome (passed / escalated / error). All advance logic
 * runs outside React state updaters and reads `queueRef`, so it can't double-advance
 * under StrictMode's double-invocation.
 */
export function useChapterQueue({ startRun, isRunning }: UseChapterQueueArgs) {
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [processing, setProcessing] = useState(false);

  // Latest queue snapshot for the async callbacks (start / handleRunComplete),
  // which run after commit — synced in an effect per the react-hooks/refs rule.
  const queueRef = useRef<QueueItem[]>(queue);
  useEffect(() => {
    queueRef.current = queue;
  }, [queue]);
  const processingRef = useRef(false);

  const enqueue = useCallback((v: RunFormValues) => {
    setQueue((q) => [
      ...q,
      {
        board: v.board,
        subject: v.subject,
        grade: v.grade,
        chapter: v.chapter,
        id: nextId(),
        status: "pending",
      },
    ]);
  }, []);

  // Drop an item unless it is the one currently running.
  const remove = useCallback((id: string) => {
    setQueue((q) => q.filter((it) => it.id !== id || it.status === "running"));
  }, []);

  // Clear everything except a running item (and any already-finished items are dropped too).
  const clear = useCallback(() => {
    setQueue((q) => q.filter((it) => it.status === "running"));
  }, []);

  // Mark an item running and kick off its pipeline run.
  const startItem = useCallback(
    (item: QueueItem) => {
      setQueue((q) =>
        q.map((it) => (it.id === item.id ? { ...it, status: "running" } : it))
      );
      startRun({
        board: item.board,
        subject: item.subject,
        grade: item.grade,
        chapter: item.chapter,
      });
    },
    [startRun]
  );

  // Begin draining from the first pending item.
  const start = useCallback(() => {
    if (processingRef.current || isRunning) return;
    const first = queueRef.current.find((it) => it.status === "pending");
    if (!first) return;
    processingRef.current = true;
    setProcessing(true);
    startItem(first);
  }, [isRunning, startItem]);

  // Called when the active run finishes. Records the outcome on the running item,
  // then starts the next pending item — or stops when the queue is drained.
  const handleRunComplete = useCallback(
    (outcome: RunOutcome) => {
      if (!processingRef.current) return;

      const current = queueRef.current;
      const running = current.find((it) => it.status === "running");
      const settled = current.map((it) =>
        it.id === running?.id ? { ...it, status: outcomeToStatus(outcome) } : it
      );
      setQueue(settled);

      const next = settled.find((it) => it.status === "pending");
      if (next) {
        startItem(next);
      } else {
        processingRef.current = false;
        setProcessing(false);
      }
    },
    [startItem]
  );

  return { queue, processing, enqueue, remove, clear, start, handleRunComplete };
}
