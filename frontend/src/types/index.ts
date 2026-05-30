// ── Auth ──────────────────────────────────────────────────────────────────────

export interface User {
  id: string;
  email: string;
  name: string;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: User;
}

// ── Workspaces ────────────────────────────────────────────────────────────────

export interface Workspace {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
}

// ── Environments ──────────────────────────────────────────────────────────────

export interface Environment {
  id: string;
  workspace_id: string;
  name: string;
  is_active: boolean;
  created_at: string;
  variable_count?: number;
}

export interface EnvironmentDetail extends Environment {
  variables: EnvVariable[];
}

export interface EnvVariable {
  id: string;
  environment_id: string;
  key: string;
  value: string;       // "***" when is_secret=true
  is_secret: boolean;
}

export interface PreviewResponse {
  result: string;
  resolved_keys: string[];
  unresolved_keys: string[];
}

// ── Collections & Requests ────────────────────────────────────────────────────

export interface Collection {
  id: string;
  workspace_id: string;
  name: string;
  description: string | null;
  requests: ApiRequest[];
  created_at: string;
  updated_at: string;
}

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
export type BodyType = "json" | "form" | "raw" | "none";
export type AuthType = "none" | "bearer" | "basic" | "api_key";

export interface ApiRequest {
  id: string;
  collection_id: string;
  name: string;
  method: HttpMethod;
  url: string;
  headers: Record<string, string>;
  body: string | null;
  body_type: BodyType;
  auth_type: AuthType;
  auth_config: Record<string, string>;
  timeout_ms: number;
  order_index: number;
  assertions: Assertion[];
}

// ── Assertions ────────────────────────────────────────────────────────────────

export type AssertionType =
  | "status_code"
  | "response_time"
  | "json_path"
  | "header"
  | "body_contains";

export type AssertionOperator =
  | "eq" | "ne"
  | "gt" | "lt" | "gte" | "lte"
  | "contains" | "not_contains"
  | "exists" | "matches";

export interface Assertion {
  id: string;
  request_id: string;
  type: AssertionType;
  operator: AssertionOperator;
  expected_value: string;
  path: string | null;   // JSONPath for json_path type
}

// ── Test Runs ─────────────────────────────────────────────────────────────────

export type RunStatus = "pending" | "running" | "passed" | "failed" | "error";
export type ResultStatus = "passed" | "failed" | "error" | "skipped";

export interface TestRun {
  id: string;
  workspace_id: string;
  collection_id: string | null;
  collection_name: string | null;
  environment_id: string | null;
  triggered_by: string | null;
  trigger_type: "manual" | "scheduled" | "api";
  status: RunStatus;
  total: number;
  passed: number;
  failed: number;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
}

export interface TestRunDetail extends TestRun {
  results: TestResult[];
}

export interface RunStats {
  total_runs: number;
  passed_runs: number;
  failed_runs: number;
  error_runs: number;
  pass_rate: number;
  avg_duration_ms: number | null;
  avg_response_time_ms: number | null;
}

export type SortDir = "asc" | "desc";

export interface TestResult {
  id: string;
  test_run_id: string;
  request_id: string | null;
  request_snapshot: ApiRequest;
  status: ResultStatus;
  response_status: number | null;
  response_headers: Record<string, string>;
  response_body: string | null;
  response_time_ms: number | null;
  executed_at: string;
  retry_count: number;
  error_message: string | null;
  assertion_results: AssertionResult[];
}

export interface AssertionResult {
  id: string;
  test_result_id: string;
  assertion_id: string | null;
  assertion_snapshot: Assertion;
  passed: boolean;
  actual_value: string | null;
  error_message: string | null;
}

// ── AI Analysis ───────────────────────────────────────────────────────────────

export interface AiSuggestion {
  title: string;
  description: string;
  code?: string;
}

export interface AiAnalysis {
  id: string;
  test_result_id: string;
  model: string;
  analysis: string;          // markdown
  suggestions: AiSuggestion[];
  prompt_tokens: number;
  completion_tokens: number;
  created_at: string;
}

// ── Schedules ─────────────────────────────────────────────────────────────────

export interface Schedule {
  id: string;
  collection_id: string;
  environment_id: string | null;
  cron_expression: string;
  is_active: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
}

// ── Diff ──────────────────────────────────────────────────────────────────────

export type ChangeType = "added" | "removed" | "changed" | "unchanged";

export interface FieldChange {
  path: string;
  from_value: string | null;
  to_value: string | null;
  change_type: ChangeType;
}

export interface SectionDiff {
  section: string;
  label: string;
  summary: string;
  changes: FieldChange[];
  has_changes: boolean;
}

export interface ResultSnapshot {
  result_id: string;
  executed_at: string;
  run_status: string;
  status_code: number | null;
  response_time_ms: number | null;
  request_name: string;
  request_method: string;
  request_url: string;
}

export interface ResultDiff {
  a: ResultSnapshot;
  b: ResultSnapshot;
  sections: SectionDiff[];
  total_changes: number;
  is_identical: boolean;
}

export interface ResultHistoryItem {
  id: string;
  test_run_id: string;
  status: string;
  response_status: number | null;
  response_time_ms: number | null;
  executed_at: string;
}

// ── Analytics ─────────────────────────────────────────────────────────────────

export interface AnalyticsSummary {
  days: number;
  total_runs: number;
  passed_runs: number;
  failed_runs: number;
  error_runs: number;
  pass_rate: number;
  total_executions: number;
  passed_executions: number;
  failed_executions: number;
  avg_response_time_ms: number | null;
  p95_response_time_ms: number | null;
}

export interface DayStat {
  date: string;
  total: number;
  passed: number;
  failed: number;
  pass_rate: number;
}

export interface EndpointStat {
  request_id: string | null;
  name: string;
  method: string;
  url: string;
  total_executions: number;
  avg_response_time_ms: number;
  max_response_time_ms: number;
  pass_rate: number;
}

export interface CollectionStat {
  collection_id: string;
  collection_name: string;
  total_runs: number;
  passed_runs: number;
  pass_rate: number;
  avg_response_time_ms: number | null;
}

export interface WorkspaceAnalytics {
  summary: AnalyticsSummary;
  daily_trend: DayStat[];
  slowest_endpoints: EndpointStat[];
  collection_stats: CollectionStat[];
}

// ── Pagination ────────────────────────────────────────────────────────────────

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

// ── API errors ────────────────────────────────────────────────────────────────

export interface ApiError {
  detail: string;
  code?: string;
}
