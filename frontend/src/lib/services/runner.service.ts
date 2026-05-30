import api from "@/lib/api";
import type {
  PaginatedResponse,
  ResultDiff,
  ResultHistoryItem,
  RunStats,
  TestResult,
  TestRun,
  TestRunDetail,
} from "@/types";

export interface ListRunsParams {
  page?: number;
  page_size?: number;
  status?: string;
  trigger_type?: string;
  collection_id?: string;
  started_after?: string;
  started_before?: string;
  sort_by?: string;
  sort_dir?: string;
}

export const runnerService = {
  // ── Execution ───────────────────────────────────────────────────────────────
  runSingle: (requestId: string, environmentId?: string) =>
    api.post<TestResult>(`/requests/${requestId}/run`, {
      environment_id: environmentId ?? null,
    }),

  runCollection: (collectionId: string, environmentId?: string, config?: object) =>
    api.post<TestRun>(`/collections/${collectionId}/run`, {
      environment_id: environmentId ?? null,
      config: config ?? {},
    }),

  // ── History ─────────────────────────────────────────────────────────────────
  getStats: (workspaceId: string) =>
    api.get<RunStats>(`/workspaces/${workspaceId}/runs/stats`),

  listRuns: (workspaceId: string, params: ListRunsParams = {}) =>
    api.get<PaginatedResponse<TestRun>>(`/workspaces/${workspaceId}/runs`, {
      params: {
        page:           params.page        ?? 1,
        page_size:      params.page_size   ?? 20,
        status:         params.status      || undefined,
        trigger_type:   params.trigger_type || undefined,
        collection_id:  params.collection_id || undefined,
        started_after:  params.started_after || undefined,
        started_before: params.started_before || undefined,
        sort_by:        params.sort_by     ?? "started_at",
        sort_dir:       params.sort_dir    ?? "desc",
      },
    }),

  getRun: (runId: string) =>
    api.get<TestRunDetail>(`/runs/${runId}`),

  getResult: (resultId: string) =>
    api.get<TestResult>(`/results/${resultId}`),

  // ── Diff ────────────────────────────────────────────────────────────────────
  diffResults: (resultIdA: string, resultIdB: string) =>
    api.post<ResultDiff>("/results/diff", {
      result_id_a: resultIdA,
      result_id_b: resultIdB,
    }),

  getRequestHistory: (requestId: string, limit = 10) =>
    api.get<ResultHistoryItem[]>(`/requests/${requestId}/history`, {
      params: { limit },
    }),

  // SSE stream URL (used directly with EventSource, not via axios)
  streamUrl: (runId: string) =>
    `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/runs/${runId}/stream`,
};
