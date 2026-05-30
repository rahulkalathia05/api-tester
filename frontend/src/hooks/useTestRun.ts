"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { runnerService } from "@/lib/services/runner.service";
import { useAuthStore } from "@/stores/authStore";
import type { TestRun, TestResult } from "@/types";

interface RunState {
  run: TestRun | null;
  results: TestResult[];
  isRunning: boolean;
  error: string | null;
}

export function useTestRun() {
  const [state, setState] = useState<RunState>({
    run: null,
    results: [],
    isRunning: false,
    error: null,
  });
  const eventSourceRef = useRef<EventSource | null>(null);
  const { accessToken } = useAuthStore();

  const closeStream = () => {
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
  };

  // Stream live updates via SSE
  const streamRun = useCallback(
    (runId: string) => {
      closeStream();
      // Append token as query param since EventSource can't set headers
      const url = `${runnerService.streamUrl(runId)}?token=${accessToken}`;
      const es = new EventSource(url);
      eventSourceRef.current = es;

      es.addEventListener("result", (e) => {
        const result: TestResult = JSON.parse(e.data);
        setState((prev) => ({ ...prev, results: [...prev.results, result] }));
      });

      es.addEventListener("status", (e) => {
        const run: TestRun = JSON.parse(e.data);
        setState((prev) => ({ ...prev, run }));
      });

      es.addEventListener("done", () => {
        setState((prev) => ({ ...prev, isRunning: false }));
        closeStream();
      });

      es.onerror = () => {
        setState((prev) => ({ ...prev, isRunning: false, error: "Stream disconnected" }));
        closeStream();
      };
    },
    [accessToken]
  );

  const startRun = useCallback(
    async (collectionId: string, environmentId?: string) => {
      setState({ run: null, results: [], isRunning: true, error: null });
      try {
        const { data: run } = await runnerService.runCollection(collectionId, environmentId);
        setState((prev) => ({ ...prev, run }));
        streamRun(run.id);
      } catch {
        setState((prev) => ({
          ...prev,
          isRunning: false,
          error: "Failed to start run",
        }));
      }
    },
    [streamRun]
  );

  useEffect(() => () => closeStream(), []);

  return { ...state, startRun };
}
