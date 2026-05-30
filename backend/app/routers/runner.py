from fastapi import APIRouter, Query

from app.dependencies import CurrentUser, DBDep, RedisDep
from app.schemas.collection import Page
from app.schemas.runner import (
    AiAnalysisOut,
    CancelRunResponse,
    CollectionRunRequest,
    DiffRequest,
    QueueStatus,
    ResultDiff,
    ResultHistoryItem,
    RetryStatus,
    RunStats,
    SingleRunRequest,
    TestResultOut,
    TestRunDetail,
    TestRunOut,
)
from app.services.ai_service import AiService
from app.services.diff_service import DiffService
from app.services.queue_service import QueueService
from app.services.runner_service import RunnerService
from app.worker.queue import enqueue_run

router = APIRouter(tags=["runner"])


# ── Single-request run ────────────────────────────────────────────────────────

@router.post("/requests/{request_id}/run", response_model=TestResultOut, status_code=201)
async def run_single_request(
    request_id: str,
    body: SingleRunRequest,
    current_user: CurrentUser,
    db: DBDep,
) -> TestResultOut:
    return await RunnerService(db).run_single(current_user, request_id, body)


# ── Collection run ────────────────────────────────────────────────────────────

@router.post("/collections/{collection_id}/run", response_model=TestRunOut, status_code=202)
async def run_collection(
    collection_id: str,
    body: CollectionRunRequest,
    current_user: CurrentUser,
    db: DBDep,
    redis: RedisDep,
) -> TestRunOut:
    run = await RunnerService(db).create_collection_run(current_user, collection_id, body)
    await enqueue_run(redis, run.id, collection_id=collection_id)
    return run


# ── Run history ───────────────────────────────────────────────────────────────

@router.get("/workspaces/{workspace_id}/runs/stats", response_model=RunStats)
async def get_run_stats(
    workspace_id: str,
    current_user: CurrentUser,
    db: DBDep,
) -> RunStats:
    """Aggregate pass/fail counts for the history dashboard header."""
    return await RunnerService(db).get_stats(current_user, workspace_id)


@router.get("/workspaces/{workspace_id}/runs", response_model=Page[TestRunOut])
async def list_runs(
    workspace_id: str,
    current_user: CurrentUser,
    db: DBDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    # ── Filters ────────────────────────────────────────────────────────────────
    status: str | None = Query(default=None, description="passed|failed|error|running|pending"),
    trigger_type: str | None = Query(default=None, description="manual|scheduled|api"),
    collection_id: str | None = Query(default=None),
    started_after: str | None = Query(default=None, description="ISO 8601 datetime"),
    started_before: str | None = Query(default=None, description="ISO 8601 datetime"),
    # ── Sorting ────────────────────────────────────────────────────────────────
    sort_by: str = Query(default="started_at", description="started_at|completed_at|status|total|passed"),
    sort_dir: str = Query(default="desc", description="asc|desc"),
) -> Page[TestRunOut]:
    return await RunnerService(db).list_runs(
        current_user, workspace_id,
        page=page, page_size=page_size,
        status=status,
        trigger_type=trigger_type,
        collection_id=collection_id,
        started_after=started_after,
        started_before=started_before,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )


@router.get("/runs/{run_id}", response_model=TestRunDetail)
async def get_run(run_id: str, current_user: CurrentUser, db: DBDep) -> TestRunDetail:
    return await RunnerService(db).get_run(current_user, run_id)


@router.get("/results/{result_id}", response_model=TestResultOut)
async def get_result(result_id: str, current_user: CurrentUser, db: DBDep) -> TestResultOut:
    return await RunnerService(db).get_result(current_user, result_id)


# ── AI Analysis ───────────────────────────────────────────────────────────────

@router.post(
    "/results/{result_id}/analyze",
    response_model=AiAnalysisOut,
    status_code=201,
    summary="Generate AI root-cause analysis for a failed test result",
    description=(
        "Calls GPT-4o-mini with the full request/response/assertion context "
        "and returns structured root causes, debugging steps, and likely fixes. "
        "Results are cached — subsequent calls return the stored analysis. "
        "Pass ?force=true to regenerate."
    ),
)
async def analyze_result(
    result_id: str,
    current_user: CurrentUser,
    db: DBDep,
    force: bool = False,
) -> AiAnalysisOut:
    return await AiService(db).analyze(result_id, current_user.id, force=force)


@router.get(
    "/results/{result_id}/analysis",
    response_model=AiAnalysisOut,
    summary="Fetch a previously generated AI analysis",
)
async def get_analysis(
    result_id: str,
    current_user: CurrentUser,
    db: DBDep,
) -> AiAnalysisOut:
    return await AiService(db).get_analysis(result_id, current_user.id)


# ── Diff ──────────────────────────────────────────────────────────────────────

@router.post(
    "/results/diff",
    response_model=ResultDiff,
    summary="Diff two test results field-by-field",
    description=(
        "Compares two TestResult objects across five sections: "
        "status code, response time, headers, body (deep JSON diff), and schema "
        "(fields that changed type or appeared/disappeared)."
    ),
)
async def diff_results(
    body: DiffRequest,
    current_user: CurrentUser,
    db: DBDep,
) -> ResultDiff:
    return await DiffService(db).compare(
        body.result_id_a, body.result_id_b, current_user.id
    )


@router.get(
    "/requests/{request_id}/history",
    response_model=list[ResultHistoryItem],
    summary="Recent executions of a specific request",
    description=(
        "Returns the last N test results for a given request — "
        "used by the diff UI to let users pick which execution to compare against."
    ),
)
async def request_history(
    request_id: str,
    current_user: CurrentUser,
    db: DBDep,
    limit: int = Query(default=10, ge=1, le=50),
) -> list[ResultHistoryItem]:
    results = await DiffService(db).list_request_history(
        request_id, current_user.id, limit=limit
    )
    return [ResultHistoryItem.model_validate(r) for r in results]


# ── Async execution queue ─────────────────────────────────────────────────────

@router.get(
    "/workspaces/{workspace_id}/queue/status",
    response_model=QueueStatus,
    summary="Queue depth and retry counts",
)
async def queue_status(
    workspace_id: str,
    current_user: CurrentUser,
    db: DBDep,
    redis: RedisDep,
) -> QueueStatus:
    return await QueueService(db, redis).get_status(current_user, workspace_id)


@router.post(
    "/runs/{run_id}/cancel",
    response_model=CancelRunResponse,
    summary="Cancel a queued (pending) run",
)
async def cancel_run(
    run_id: str,
    current_user: CurrentUser,
    db: DBDep,
) -> CancelRunResponse:
    return await QueueService(db).cancel_run(current_user, run_id)


@router.get(
    "/runs/{run_id}/retry-status",
    response_model=RetryStatus,
    summary="Current retry state for a run",
    description=(
        "Returns attempt count, retry schedule, next retry timestamp, and "
        "failure classification (transient/permanent/exhausted)."
    ),
)
async def get_retry_status(
    run_id: str,
    current_user: CurrentUser,
    db: DBDep,
    redis: RedisDep,
) -> RetryStatus:
    return await QueueService(db, redis).get_retry_status(current_user, run_id)
