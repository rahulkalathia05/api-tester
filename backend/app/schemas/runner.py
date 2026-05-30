from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ── Request bodies ────────────────────────────────────────────────────────────

class SingleRunRequest(BaseModel):
    environment_id: str | None = None


class CollectionRunRequest(BaseModel):
    environment_id: str | None = None
    config: dict = Field(default_factory=dict)
    # config keys: stop_on_failure (bool)


# ── Sort / filter types ───────────────────────────────────────────────────────

RunStatus   = Literal["pending", "running", "passed", "failed", "error"]
TriggerType = Literal["manual", "scheduled", "api"]
SortBy      = Literal["started_at", "completed_at", "status", "total", "passed", "duration_ms"]
SortDir     = Literal["asc", "desc"]


# ── Output ────────────────────────────────────────────────────────────────────

class AssertionResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    assertion_id: str | None
    assertion_snapshot: dict   # {type, operator, expected_value, path}
    passed: bool
    actual_value: str | None
    error_message: str | None


class TestResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    test_run_id: str
    request_id: str | None
    request_snapshot: dict     # copy of the request at execution time
    status: str                # passed | failed | error | skipped
    response_status: int | None
    response_headers: dict
    response_body: str | None
    response_time_ms: int | None
    executed_at: datetime
    retry_count: int
    error_message: str | None
    assertion_results: list[AssertionResultOut] = []


class TestRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    collection_id: str | None
    collection_name: str | None = None   # joined from collections table in list queries
    environment_id: str | None
    triggered_by: str | None
    trigger_type: str
    status: str
    total: int
    passed: int
    failed: int
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None = None       # computed: completed_at - started_at


class TestRunDetail(TestRunOut):
    results: list[TestResultOut] = []


# ── AI Analysis ──────────────────────────────────────────────────────────────

class RootCause(BaseModel):
    title: str
    description: str
    confidence: Literal["high", "medium", "low"]


class DebuggingStep(BaseModel):
    step: int
    action: str
    detail: str


class LikelyFix(BaseModel):
    title: str
    description: str
    code: str | None = None


class AiAnalysisOut(BaseModel):
    """
    Full structured output from the AI analysis.

    The `suggestions` column in the DB stores a flat list for legacy compat;
    this schema exposes the rich sectioned structure returned from the model.
    """
    model_config = ConfigDict(from_attributes=True)

    id: str
    test_result_id: str
    model: str
    summary: str                         # one-sentence diagnosis
    root_causes: list[RootCause] = []
    debugging_steps: list[DebuggingStep] = []
    likely_fixes: list[LikelyFix] = []
    prompt_tokens: int
    completion_tokens: int
    created_at: datetime

    @classmethod
    def model_validate(cls, obj, **kwargs):
        """
        When loading from an ORM AiAnalysis object, reconstruct the structured
        fields from the flat `suggestions` column.
        """
        if hasattr(obj, "__tablename__"):
            suggestions = obj.suggestions or []
            return cls(
                id=obj.id,
                test_result_id=obj.test_result_id,
                model=obj.model,
                summary=obj.analysis,
                root_causes=[
                    s for s in suggestions if s.get("section") == "root_cause"
                ],
                debugging_steps=[
                    s for s in suggestions if s.get("section") == "debugging_step"
                ],
                likely_fixes=[
                    s for s in suggestions if s.get("section") == "likely_fix"
                ],
                prompt_tokens=obj.prompt_tokens,
                completion_tokens=obj.completion_tokens,
                created_at=obj.created_at,
            )
        return super().model_validate(obj, **kwargs)


# ── Diff ─────────────────────────────────────────────────────────────────────
# Re-export the Pydantic models defined in diff_service so the router only
# imports from one schemas module.

from app.services.diff_service import (  # noqa: E402
    FieldChange,
    ResultDiff,
    ResultSnapshot,
    SectionDiff,
)

__all__ = [
    "FieldChange", "ResultDiff", "ResultSnapshot", "SectionDiff",
]


class DiffRequest(BaseModel):
    """Body for POST /results/diff."""
    result_id_a: str
    result_id_b: str


class ResultHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    test_run_id: str
    status: str
    response_status: int | None
    response_time_ms: int | None
    executed_at: datetime


# ── Queue / async execution ───────────────────────────────────────────────────

class QueueStatus(BaseModel):
    """Snapshot of the async execution queue."""
    queue_depth: int        # jobs waiting to be picked up by a worker
    scheduled_retries: int  # jobs waiting in the sorted retry set
    total_pending: int      # pending TestRun rows (includes both above)


class CancelRunResponse(BaseModel):
    run_id: str
    cancelled: bool
    message: str


class RetryStatus(BaseModel):
    """Current retry state for a run."""
    run_id: str
    run_status: str
    attempt_count: int          # how many times this run has been attempted
    max_retries: int            # global ceiling from config
    attempts_remaining: int     # max_retries - attempt_count
    is_retrying: bool           # True when a retry is scheduled
    next_retry_at: datetime | None  # when the next attempt is scheduled (UTC)
    # Projected schedule for remaining attempts (deterministic, no jitter)
    retry_schedule: list[int]   # delay_s per remaining attempt
    failure_kind: str | None    # "transient" | "permanent" | "exhausted" | null


# ── Aggregate stats ───────────────────────────────────────────────────────────

class RunStats(BaseModel):
    """Workspace-level aggregate stats for the history dashboard header."""
    total_runs: int
    passed_runs: int
    failed_runs: int
    error_runs: int
    pass_rate: float            # 0.0–1.0
    avg_duration_ms: float | None
    avg_response_time_ms: float | None
