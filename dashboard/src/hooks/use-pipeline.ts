"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { postReExtract, postReject, postRun, streamUrl } from "@/lib/api";
import {
  initialPipelineState,
  reduceEvent,
} from "@/lib/pipeline-reducer";
import type { PipelineState, StartRunOptions } from "@/lib/types";

interface UsePipelineOptions {
  onRunComplete?: () => void;
}

export function usePipeline({ onRunComplete }: UsePipelineOptions = {}) {
  const [state, setState] = useState<PipelineState>(initialPipelineState);
  const [isRunning, setIsRunning] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const onRunCompleteRef = useRef(onRunComplete);
  onRunCompleteRef.current = onRunComplete;

  const closeSSE = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => closeSSE();
  }, [closeSSE]);

  const startRun = useCallback(
    async (options: StartRunOptions) => {
      const {
        board,
        subject,
        grade,
        chapter,
        humanFeedback,
        mapGuidance,
        rejectReason,
        model,
      } = options;

      if (!board || !subject || !grade || !chapter) {
        alert("Please fill in all fields.");
        return;
      }

      closeSSE();
      setIsRunning(true);
      setState({
        ...initialPipelineState,
        status: "running",
      });

      try {
        const base = { board, subject, grade, chapter, no_sync: true };
        let result: { run_id: string };

        if (humanFeedback) {
          result = await postRun({ ...base, human_feedback: humanFeedback, model });
        } else if (mapGuidance) {
          result = await postReExtract({ ...base, map_guidance: mapGuidance });
        } else if (rejectReason) {
          result = await postReject({ ...base, reason: rejectReason });
        } else {
          result = await postRun({ ...base, model });
        }

        const { run_id } = result;
        setState((prev) => ({ ...prev, runId: run_id }));

        const es = new EventSource(streamUrl(run_id));
        esRef.current = es;

        es.onmessage = (e) => {
          const event = JSON.parse(e.data) as { type: string; data: Record<string, unknown> };

          if (event.type === "done") {
            closeSSE();
            setIsRunning(false);
            onRunCompleteRef.current?.();
            return;
          }

          if (event.type === "heartbeat") {
            return;
          }

          setState((prev) => reduceEvent(prev, event));
        };

        es.onerror = () => {
          closeSSE();
          setIsRunning(false);
        };
      } catch {
        setIsRunning(false);
        setState((prev) => ({
          ...prev,
          status: "escalated",
          escalation: { error: "Failed to start pipeline run." },
        }));
      }
    },
    [closeSSE]
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
