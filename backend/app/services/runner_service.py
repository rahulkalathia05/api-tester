"""
Runner service — orchestrates HTTP execution and result persistence.

Two entry points:
  run_single  — executes one request synchronously, stores a TestRun + TestResult,
                returns the full result immediately.
  create_collection_run — creates a pending TestRun, enqueues it for the
                background worker, returns the run id immediately.
"""
from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_request import ApiRequest
from app.models.assertion import Assertion
from app.models.assertion_result import AssertionResult
from app.models.environment import EnvironmentVariable
from app.models.test_result import TestResult
from app.models.test_run import TestRun
from app.models.user import User
from app.repositories.collection_repo import ApiRequestRepository, CollectionRepository
from app.repositories.test_run_repo import TestResultRepository, TestRunRepository
from app.repositories.workspace_repo import WorkspaceRepository
from app.schemas.runner import (
    AssertionResultOut,
    CollectionRunRequest,
    SingleRunRequest,
    TestResultOut,
    TestRunOut,
)
from app.services.assertion_engine import (
    AssertionOutcome,
    HttpResult,
    evaluate_assertions,
)
from app.utils.interpolation import interpolate, interpolate_dict

_404_REQUEST    = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
_404_COLLECTION = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
_404_WORKSPACE  = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")


# ── HTTP execution ────────────────────────────────────────────────────────────

@dataclass
class ExecutionPayload:
    """Fully interpolated, auth-injected, ready-to-send request."""
    method: str
    url: str
    headers: dict[str, str]
    body: bytes | None
    timeout: float             # seconds


def _build_payload(
    req: ApiRequest,
    variables: dict[str, str],
) -> ExecutionPayload:
    """Interpolate variables and inject auth into a ready-to-send payload."""
    url     = interpolate(req.url, variables)
    headers = interpolate_dict({k: v for k, v in req.headers.items()}, variables)

    # Auth injection
    if req.auth_type == "bearer":
        token = interpolate(req.auth_config.get("token", ""), variables)
        headers["Authorization"] = f"Bearer {token}"

    elif req.auth_type == "basic":
        username = interpolate(req.auth_config.get("username", ""), variables)
        password = interpolate(req.auth_config.get("password", ""), variables)
        encoded  = base64.b64encode(f"{username}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"

    elif req.auth_type == "api_key":
        header = interpolate(req.auth_config.get("header", "X-API-Key"), variables)
        value  = interpolate(req.auth_config.get("value", ""),            variables)
        headers[header] = value

    # Body
    body: bytes | None = None
    if req.body and req.body_type != "none":
        interpolated_body = interpolate(req.body, variables)
        body = interpolated_body.encode()
        if req.body_type == "json" and "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"

    return ExecutionPayload(
        method=req.method,
        url=url,
        headers=headers,
        body=body,
        timeout=req.timeout_ms / 1000,
    )


async def execute_http(payload: ExecutionPayload) -> HttpResult:
    """Send the request and capture all response data. Never raises."""
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.request(
                method=payload.method,
                url=payload.url,
                headers=payload.headers,
                content=payload.body,
                timeout=payload.timeout,
            )
        elapsed_ms = round((time.perf_counter() - start) * 1000)
        return HttpResult(
            status_code=response.status_code,
            headers=dict(response.headers),
            body=response.text,
            response_time_ms=elapsed_ms,
            error=None,
        )
    except httpx.TimeoutException:
        elapsed_ms = round((time.perf_counter() - start) * 1000)
        return HttpResult(
            status_code=None,
            headers={},
            body=None,
            response_time_ms=elapsed_ms,
            error=f"Request timed out after {payload.timeout:.1f}s",
        )
    except httpx.RequestError as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000)
        return HttpResult(
            status_code=None,
            headers={},
            body=None,
            response_time_ms=elapsed_ms,
            error=f"Connection error: {exc}",
        )


# ── Persistence helpers ───────────────────────────────────────────────────────

def _determine_status(
    http_result: HttpResult,
    outcomes: list[AssertionOutcome],
) -> str:
    if http_result.error:
        return "error"
    if outcomes and not all(o.passed for o in outcomes):
        return "failed"
    return "passed"


def _request_snapshot(req: ApiRequest) -> dict:
    """Capture the request state at execution time."""
    return {
        "id":          req.id,
        "name":        req.name,
        "method":      req.method,
        "url":         req.url,
        "headers":     req.headers,
        "body":        req.body,
        "body_type":   req.body_type,
        "auth_type":   req.auth_type,
        "timeout_ms":  req.timeout_ms,
    }


async def _persist_result(
    session: AsyncSession,
    run: TestRun,
    req: ApiRequest,
    http_result: HttpResult,
    outcomes: list[AssertionOutcome],
) -> tuple[TestResult, list[AssertionResult]]:
    """
    Write TestResult + AssertionResults; update TestRun counters.

    Returns both objects so callers can build the response without accessing
    the lazy-raise relationship on TestResult.
    """
    result_status = _determine_status(http_result, outcomes)

    test_result = TestResult(
        test_run_id=run.id,
        request_id=req.id,
        request_snapshot=_request_snapshot(req),
        status=result_status,
        response_status=http_result.status_code,
        response_headers=http_result.headers,
        response_body=http_result.body,
        response_time_ms=http_result.response_time_ms,
        error_message=http_result.error,
    )
    session.add(test_result)
    await session.flush()

    ar_objects: list[AssertionResult] = []
    for outcome in outcomes:
        ar = AssertionResult(
            test_result_id=test_result.id,
            assertion_id=outcome.assertion_id,
            assertion_snapshot=outcome.assertion_snapshot,
            passed=outcome.passed,
            actual_value=outcome.actual_value,
            error_message=outcome.error_message,
        )
        session.add(ar)
        ar_objects.append(ar)

    run.total  += 1
    run.passed += int(result_status == "passed")
    run.failed += int(result_status in ("failed", "error"))

    await session.flush()
    return test_result, ar_objects


def _result_to_out(
    result: TestResult,
    ar_objects: list[AssertionResult] | None = None,
) -> TestResultOut:
    """
    Build a TestResultOut.

    Pass ar_objects when the assertion_results relationship has not been
    eagerly loaded (e.g. immediately after creation).  When ar_objects is
    None the relationship is accessed directly — only safe after selectinload.
    """
    ars = ar_objects if ar_objects is not None else result.assertion_results
    return TestResultOut(
        id=result.id,
        test_run_id=result.test_run_id,
        request_id=result.request_id,
        request_snapshot=result.request_snapshot,
        status=result.status,
        response_status=result.response_status,
        response_headers=result.response_headers,
        response_body=result.response_body,
        response_time_ms=result.response_time_ms,
        executed_at=result.executed_at,
        retry_count=result.retry_count,
        error_message=result.error_message,
        assertion_results=[AssertionResultOut.model_validate(ar) for ar in ars],
    )


def _run_to_out(run: TestRun, collection_name: str | None = None) -> TestRunOut:
    duration_ms = None
    if run.started_at and run.completed_at:
        duration_ms = round(
            (run.completed_at - run.started_at).total_seconds() * 1000
        )
    return TestRunOut(
        id=run.id,
        workspace_id=run.workspace_id,
        collection_id=run.collection_id,
        collection_name=collection_name,
        environment_id=run.environment_id,
        triggered_by=run.triggered_by,
        trigger_type=run.trigger_type,
        status=run.status,
        total=run.total,
        passed=run.passed,
        failed=run.failed,
        started_at=run.started_at,
        completed_at=run.completed_at,
        duration_ms=duration_ms,
    )


# ── Service class ─────────────────────────────────────────────────────────────

class RunnerService:

    def __init__(self, db: AsyncSession) -> None:
        self._db          = db
        self._req_repo    = ApiRequestRepository(db)
        self._col_repo    = CollectionRepository(db)
        self._run_repo    = TestRunRepository(db)
        self._result_repo = TestResultRepository(db)
        self._ws_repo     = WorkspaceRepository(db)

    # ── Environment variables ──────────────────────────────────────────────────

    async def _load_variables(self, environment_id: str | None) -> dict[str, str]:
        if not environment_id:
            return {}
        rows = await self._db.execute(
            select(EnvironmentVariable).where(
                EnvironmentVariable.environment_id == environment_id
            )
        )
        return {v.key: v.value for v in rows.scalars().all()}

    # ── Single request run ─────────────────────────────────────────────────────

    async def run_single(
        self,
        user: User,
        request_id: str,
        body: SingleRunRequest,
    ) -> TestResultOut:
        """
        Execute one request synchronously.

        Creates a TestRun (trigger_type='manual', collection_id=None),
        executes the request, evaluates assertions, persists everything,
        and returns the full result in the same HTTP call.
        """
        # Load the request with assertions, verify ownership.
        req = await self._req_repo.get_detail(request_id, user.id)
        if req is None:
            raise _404_REQUEST

        # Derive workspace_id through the collection.
        col = await self._col_repo.get_owned(req.collection_id, user.id)
        if col is None:
            raise _404_REQUEST

        variables = await self._load_variables(body.environment_id)

        # Create a TestRun scoped to this single request.
        now = datetime.now(timezone.utc)
        run = TestRun(
            workspace_id=col.workspace_id,
            collection_id=None,
            environment_id=body.environment_id,
            triggered_by=user.id,
            trigger_type="manual",
            status="running",
            started_at=now,
        )
        self._db.add(run)
        await self._db.flush()

        # Execute
        payload              = _build_payload(req, variables)
        http_result          = await execute_http(payload)
        outcomes             = evaluate_assertions(req.assertions, http_result)
        test_result, ar_objs = await _persist_result(self._db, run, req, http_result, outcomes)

        # Finalise run
        run.status       = "passed" if run.failed == 0 else "failed"
        run.completed_at = datetime.now(timezone.utc)
        await self._db.flush()

        # Pass ar_objs directly — avoids touching the lazy-raise relationship.
        return _result_to_out(test_result, ar_objects=ar_objs)

    # ── Collection run (async) ─────────────────────────────────────────────────

    async def create_collection_run(
        self,
        user: User,
        collection_id: str,
        body: CollectionRunRequest,
    ) -> TestRunOut:
        """
        Create a pending TestRun for a collection and enqueue it.

        The background worker picks up the job and calls execute_collection_run().
        Returns immediately with status='pending'.
        """
        col = await self._col_repo.get_owned(collection_id, user.id)
        if col is None:
            raise _404_COLLECTION

        run = TestRun(
            workspace_id=col.workspace_id,
            collection_id=collection_id,
            environment_id=body.environment_id,
            triggered_by=user.id,
            trigger_type="manual",
            status="pending",
            config=body.config,
        )
        self._db.add(run)
        await self._db.flush()

        return _run_to_out(run)

    # ── History ────────────────────────────────────────────────────────────────

    async def list_runs(
        self,
        user: User,
        workspace_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        trigger_type: str | None = None,
        collection_id: str | None = None,
        started_after: str | None = None,
        started_before: str | None = None,
        sort_by: str = "started_at",
        sort_dir: str = "desc",
    ):
        from datetime import timezone
        from app.schemas.collection import Page

        ws = await self._ws_repo.get_owned(workspace_id, user.id)
        if ws is None:
            raise HTTPException(status_code=404, detail="Workspace not found")

        from datetime import datetime as _dt

        def _parse_dt(s: str | None):
            if not s:
                return None
            try:
                return _dt.fromisoformat(s).replace(tzinfo=timezone.utc) if s.endswith("Z") is False else _dt.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                return None

        rows, total = await self._run_repo.list_by_workspace(
            workspace_id, user.id,
            page=page, page_size=page_size,
            status=status,
            trigger_type=trigger_type,
            collection_id=collection_id,
            started_after=_parse_dt(started_after),
            started_before=_parse_dt(started_before),
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        items = [_run_to_out(run, cname) for run, cname in rows]
        return Page.build(items, total, page, page_size)

    async def get_stats(self, user: User, workspace_id: str):
        from app.schemas.runner import RunStats

        ws = await self._ws_repo.get_owned(workspace_id, user.id)
        if ws is None:
            raise HTTPException(status_code=404, detail="Workspace not found")

        data = await self._run_repo.get_stats(workspace_id, user.id)
        total   = data["total"] or 0
        passed  = int(data["passed"] or 0)
        failed  = int(data["failed"] or 0)
        errors  = int(data["errors"] or 0)
        return RunStats(
            total_runs=total,
            passed_runs=passed,
            failed_runs=failed,
            error_runs=errors,
            pass_rate=passed / total if total else 0.0,
            avg_duration_ms=None,
            avg_response_time_ms=None,
        )

    async def get_run(self, user: User, run_id: str):
        from app.schemas.runner import TestRunDetail
        run = await self._run_repo.get_detail(run_id, user.id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return TestRunDetail(
            **_run_to_out(run).model_dump(),
            results=[_result_to_out(r) for r in run.results],
        )

    async def get_result(self, user: User, result_id: str) -> TestResultOut:
        result = await self._result_repo.get_detail(result_id, user.id)
        if result is None:
            raise HTTPException(status_code=404, detail="Result not found")
        return _result_to_out(result)
