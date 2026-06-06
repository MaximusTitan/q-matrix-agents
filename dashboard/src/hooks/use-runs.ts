"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchRuns } from "@/lib/api";
import type { RunMetadata } from "@/lib/types";

const POLL_INTERVAL_MS = 10_000;

export function useRuns() {
  const [runs, setRuns] = useState<RunMetadata[]>([]);

  const loadRuns = useCallback(async () => {
    try {
      const data = await fetchRuns();
      setRuns(data);
    } catch {
      // ignore polling errors
    }
  }, []);

  useEffect(() => {
    loadRuns();
    const id = setInterval(loadRuns, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [loadRuns]);

  return { runs, refresh: loadRuns };
}
