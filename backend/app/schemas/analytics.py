from __future__ import annotations

from pydantic import BaseModel


# ── KPI summary ───────────────────────────────────────────────────────────────

class AnalyticsSummary(BaseModel):
    """Top-level KPI cards — computed from test_runs + test_results."""
    days: int                        # the time-window this covers

    # Test run counters
    total_runs: int
    passed_runs: int
    failed_runs: int
    error_runs: int
    pass_rate: float                 # 0.0–1.0

    # Request execution counters (one result row per request in a run)
    total_executions: int
    passed_executions: int
    failed_executions: int

    # Latency
    avg_response_time_ms: float | None
    p95_response_time_ms: float | None   # approximate: computed in Python


# ── Daily trend ───────────────────────────────────────────────────────────────

class DayStat(BaseModel):
    """Pass/fail counts for one calendar day (UTC)."""
    date: str           # "YYYY-MM-DD"
    total: int
    passed: int
    failed: int
    pass_rate: float    # 0.0–1.0


# ── Slowest endpoints ─────────────────────────────────────────────────────────

class EndpointStat(BaseModel):
    """Aggregate latency + reliability per unique API request."""
    request_id: str | None
    name: str
    method: str
    url: str
    total_executions: int
    avg_response_time_ms: float
    max_response_time_ms: int
    pass_rate: float


# ── Collection reliability ────────────────────────────────────────────────────

class CollectionStat(BaseModel):
    """Pass rate and latency rolled up per collection."""
    collection_id: str
    collection_name: str
    total_runs: int
    passed_runs: int
    pass_rate: float
    avg_response_time_ms: float | None


# ── Combined response ─────────────────────────────────────────────────────────

class WorkspaceAnalytics(BaseModel):
    """Everything the dashboard needs in a single API call."""
    summary: AnalyticsSummary
    daily_trend: list[DayStat]
    slowest_endpoints: list[EndpointStat]
    collection_stats: list[CollectionStat]
