"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  postReExtract,
  postReject,
  postRun,
  postRunL2Prerequisite,
  postRunL3Prerequisite,
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
        humanFeedback, mapGuidance, rejectReason, curriculumCsv,
        l2Prerequisite, l3Prerequisite, models,
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
        } else if (l2Prerequisite) {
          result = await postRunL2Prerequisite(base);
        } else if (l3Prerequisite) {
          result = await postRunL3Prerequisite(base);
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
            // Read the terminal status from the ref. The backend emits the pass/
            // escalate event and `done` back-to-back with no delay, so both can be
            // delivered and processed in the same tick — before React has committed
            // and run the passive ref-sync effect below. Relying on that effect here
            // would read a stale "running" status and misreport the outcome (e.g. to
            // the chapter queue), so the ref is also updated synchronously below,
            // inside the same setState call that computes the reduced status.
            finishRun(stateRef.current.status);
            return;
          }

          if (event.type === "heartbeat") {
            return;
          }

          setState((prev) => {
            const next = reduceEvent(prev, event);
            stateRef.current = next;
            return next;
          });
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
