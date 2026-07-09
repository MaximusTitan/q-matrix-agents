"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  postReExtract,
  postReject,
  postRun,
  postRunPrerequisiteOnly,
  streamUrl,
} from "@/lib/api";
import {
  initialPipelineState,
  reduceEvent,
} from "@/lib/pipeline-reducer";
import type { PipelineState, RunOutcome, StartRunOptions } from "@/lib/types";

interface UsePipelineOptions {
  // Fired once when a run finishes (any outcome). `finalStatus` reflects the
  // terminal pipeline state so callers (e.g. the queue) can advance accordingly.
  onRunComplete?: (finalStatus: RunOutcome) => void;
}

export function usePipeline({ onRunComplete }: UsePipelineOptions = {}) {
  const [state, setState] = useState<PipelineState>(initialPipelineState);
  const [isRunning, setIsRunning] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const onRunCompleteRef = useRef(onRunComplete);

  // Mirror of `state` so the SSE handlers can read the latest terminal status
  // without re-subscribing on every render.
  const stateRef = useRef(state);

  // Keep the latest prop/state available to the async SSE handlers. Synced in an
  // effect rather than during render (per the react-hooks/refs rule).
  useEffect(() => {
    onRunCompleteRef.current = onRunComplete;
    stateRef.current = state;
  });

  // Guards `onRunComplete` to fire at most once per run — the `done` event and a
  // subsequent `onerror` (or vice-versa) must not both advance the queue.
  const finishedRef = useRef(false);

  const closeSSE = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }, []);

  const finishRun = useCallback((finalStatus: RunOutcome) => {
    if (finishedRef.current) return;
    finishedRef.current = true;
    closeSSE();
    setIsRunning(false);
    onRunCompleteRef.current?.(finalStatus);
  }, [closeSSE]);

  useEffect(() => {
    return () => closeSSE();
  }, [closeSSE]);

  const startRun = useCallback(
    async (options: StartRunOptions) => {
      const {
        board, subject, grade, chapter,
        humanFeedback, mapGuidance, rejectReason, curriculumCsv, models,
      } = options;

      // The "provide CSV" path derives identifiers server-side, so the KB fields are
      // not required; every other path needs all four.
      if (!curriculumCsv && (!board || !subject || !grade || !chapter)) {
        alert("Please fill in all fields.");
        return;
      }

      closeSSE();
      finishedRef.current = false;
      setIsRunning(true);
      setState({
        ...initialPipelineState,
        status: "running",
      });

      try {
        const base = { board, subject, grade, chapter, no_sync: true, models };
        let result: { run_id: string };

        if (curriculumCsv) {
          result = await postRunPrerequisiteOnly({ csv_text: curriculumCsv, models });
        } else if (humanFeedback) {
          result = await postRun({ ...base, human_feedback: humanFeedback });
        } else if (mapGuidance) {
          result = await postReExtract({ ...base, map_guidance: mapGuidance });
        } else if (rejectReason) {
          result = await postReject({ ...base, reason: rejectReason });
        } else {
          result = await postRun(base);
        }

        const { run_id } = result;
        setState((prev) => ({ ...prev, runId: run_id }));

        const es = new EventSource(streamUrl(run_id));
        esRef.current = es;

        es.onmessage = (e) => {
          const event = JSON.parse(e.data) as { type: string; data: Record<string, unknown> };

          if (event.type === "done") {
            // Read the terminal status from the ref — the reducer has already
            // flushed the pass/escalate event that arrived before `done`.
            finishRun(stateRef.current.status);
            return;
          }

          if (event.type === "heartbeat") {
            return;
          }

          setState((prev) => reduceEvent(prev, event));
        };

        es.onerror = () => {
          // EventSource fires `error` on TRANSIENT drops too, after which the browser
          // auto-reconnects (readyState === CONNECTING) and the run's remaining events
          // — including `done` — still arrive on the reconnected stream. Only a
          // permanent close (readyState === CLOSED) is terminal. Treating a transient
          // blip as terminal would advance a queued batch mid-run, causing overlapping
          // runs that clobber each other's shared state.
          if (es.readyState === EventSource.CLOSED) {
            finishRun("error");
          }
        };
      } catch {
        setState((prev) => ({
          ...prev,
          status: "escalated",
          escalation: { error: "Failed to start pipeline run." },
        }));
        // Report completion so a queued batch keeps draining past a failed start.
        finishRun("error");
      }
    },
    [closeSSE, finishRun]
  );

  const setActiveTab = useCallback((tab: number) => {
    setState((prev) => ({ ...prev, activeTab: tab }));
  }, []);

  return {
    state,
    isRunning,
    startRun,
    setActiveTab,
  };
}
