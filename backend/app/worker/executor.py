"""
Collection run executor — called by the background worker.

Execution contract
──────────────────
execute_collection_run(run_id, redis) is the single entry point.

  1. Load the TestRun and validate it is in a runnable state.
  2. Mark status=running, record started_at.
  3. Load collection + requests + assertions (eager).
  4. Load environment variables (if any).
  5. Execute each request in order_index order, evaluate assertions,
     persist TestResult + AssertionResult rows after every request.
  6. Mark run as passed/failed on clean exit.

Failure classification and retry strategy
──────────────────────────────────────────
Not every failure deserves a retry.  The executor classifies exceptions:

  TRANSIENT  — network timeouts, temporary DB unavailability, connection
               refused.  These *should* be retried with backoff.
               Examples: httpx.TimeoutException, sqlalchemy.exc.OperationalError,
               OSError, ConnectionError

  PERMANENT  — programming errors, data integrity violations, assertion
               failures.  Retrying will not help.
               Examples: ValueError, TypeError, IntegrityError

Uncaught exceptions from the execution engine:
  • classify_exception(exc) → TRANSIENT | PERMANENT
  • TRANSIENT:
      count = increment_retry(redis, run_id)
      if count <= MAX_RETRIES:
          delay = compute_delay(count)   ← exponential backoff with jitter
          schedule_retry(redis, run_id, delay)
          run.status = "pending"         ← re-queued after delay
      else:
          run.status = "error"           ← permanent failure after exhaustion
  • PERMANENT:
      run.status = "error"              ← no retry; save time and cost

Assertion failures (run.status == 'failed') are never retried.

Exponential backoff parameters (all configurable via env):
  RUN_RETRY_BASE_DELAY_S  = 30    → attempt 1: ~30s
  RUN_RETRY_MULTIPLIER    = 4.0   → attempt 2: ~120s, attempt 3: ~480s
  RUN_RETRY_MAX_DELAY_S   = 3600  → capped at 1 hour
  RUN_RETRY_JITTER        = 0.2   → ±20% spread to prevent thundering herd

Stall recovery
──────────────
recover_stalled_runs() is called once at worker startup.  It finds TestRun
rows with status="running" and started_at older than RUN_STALL_THRESHOLD_SECONDS,
resets them to status="pending", and re-enqueues them.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from enum import Enum

import httpx
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.models.api_request import ApiRequest
from app.models.collection import Collection
from app.models.environment import EnvironmentVariable
from app.models.test_run import TestRun
from app.services.assertion_engine import evaluate_assertions
from app.services.runner_service import _build_payload, _persist_result, execute_http
from app.utils.backoff import compute_delay, compute_delay_no_jitter
from app.worker.queue import (
    clear_retry_count,
    enqueue_run,
    get_retry_count,
    increment_retry,
    schedule_retry,
)

logger = logging.getLogger("app.worker.executor")


# ── Failure classification ────────────────────────────────────────────────────

class FailureKind(Enum):
    TRANSIENT = "transient"   # temporary — worth retrying
    PERMANENT = "permanent"   # structural — retry will not help


_TRANSIENT_TYPES = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.NetworkError,
    ConnectionError,
    ConnectionResetError,
    ConnectionRefusedError,
    OSError,
    TimeoutError,
    asyncio.TimeoutError,
)

_PERMANENT_TYPES = (
    ValueError,
    TypeError,
    AttributeError,
    NotImplementedError,
    KeyError,
)


def classify_exception(exc: Exception) -> FailureKind:
    """
    Classify an exception as TRANSIENT or PERMANENT.

    Transient failures are retried with exponential backoff.
    Permanent failures fail immediately without retry.

    Unknown exception types default to TRANSIENT — it is safer to retry
    an unexpected error than to silently drop a run.
    """
    if isinstance(exc, _PERMANENT_TYPES):
        return FailureKind.PERMANENT
    if isinstance(exc, _TRANSIENT_TYPES):
        return FailureKind.TRANSIENT
    # Default: assume transient so the run has a chance to succeed
    return FailureKind.TRANSIENT


# ── Public entry point ────────────────────────────────────────────────────────

async def execute_collection_run(run_id: str, redis: aioredis.Redis) -> None:
    """
    Execute one collection run end-to-end.

    Handles failure classification, exponential backoff retry scheduling,
    and permanent failure marking internally — never raises to the caller.
    """
    async with AsyncSessionLocal() as session:
        run = await session.get(TestRun, run_id)
        if run is None:
            logger.warning("Run %s not found — skipping", run_id)
            return

        if run.status == "cancelled":
            logger.info("Run %s was cancelled — skipping", run_id)
            return

        if run.status not in ("pending",):
            logger.warning("Run %s has status=%s — skipping", run_id, run.status)
            return

        run.status     = "running"
        run.started_at = datetime.now(timezone.utc)
        await session.commit()
        logger.info("Run %s started", run_id, extra={"run_id": run_id})

        try:
            await _execute(session, run)
            await clear_retry_count(redis, run_id)

        except Exception as exc:
            kind = classify_exception(exc)
            logger.log(
                logging.WARNING if kind == FailureKind.TRANSIENT else logging.ERROR,
                "Run %s raised %s [%s]: %s",
                run_id, type(exc).__name__, kind.value, exc,
                extra={"run_id": run_id, "exc_type": type(exc).__name__,
                       "failure_kind": kind.value},
            )
            await _handle_failure(session, run, redis, exc, kind)


# ── Internal execution ────────────────────────────────────────────────────────

async def _execute(session, run: TestRun) -> None:
    """Run all requests in the collection.  Raises on unexpected errors."""
    collection_row = await session.execute(
        select(Collection)
        .where(Collection.id == run.collection_id)
        .options(selectinload(Collection.requests).selectinload(ApiRequest.assertions))
    )
    collection = collection_row.scalar_one_or_none()

    if collection is None:
        run.status       = "error"
        run.completed_at = datetime.now(timezone.utc)
        await session.commit()
        logger.error("Run %s: collection %s not found", run.id, run.collection_id)
        return

    variables: dict[str, str] = {}
    if run.environment_id:
        env_rows = await session.execute(
            select(EnvironmentVariable).where(
                EnvironmentVariable.environment_id == run.environment_id
            )
        )
        variables = {v.key: v.value for v in env_rows.scalars().all()}

    stop_on_failure: bool = run.config.get("stop_on_failure", False)

    for req in collection.requests:
        payload     = _build_payload(req, variables)
        http_result = await execute_http(payload)
        outcomes    = evaluate_assertions(req.assertions, http_result)
        result, _   = await _persist_result(session, run, req, http_result, outcomes)

        logger.info(
            "Run %s | %s %s → %s | %dms",
            run.id, req.method, req.name, result.status,
            http_result.response_time_ms,
            extra={"run_id": run.id, "request": req.name,
                   "status": result.status, "ms": http_result.response_time_ms},
        )

        if stop_on_failure and result.status in ("failed", "error"):
            logger.info("Run %s stopping early (stop_on_failure=True)", run.id)
            break

        await session.commit()

    run.status       = "passed" if run.failed == 0 else "failed"
    run.completed_at = datetime.now(timezone.utc)
    await session.commit()

    logger.info(
        "Run %s complete: %s (%d/%d passed)",
        run.id, run.status, run.passed, run.total,
        extra={"run_id": run.id, "status": run.status,
               "passed": run.passed, "total": run.total},
    )


# ── Retry / failure handling ──────────────────────────────────────────────────

async def _handle_failure(
    session,
    run: TestRun,
    redis: aioredis.Redis,
    exc: Exception,
    kind: FailureKind = FailureKind.TRANSIENT,
) -> None:
    """
    Decide whether to retry or permanently fail the run.

    For TRANSIENT errors:
      - Increment the retry counter.
      - If attempts remaining: compute exponential backoff delay, schedule.
      - If exhausted: mark error, clear counter.

    For PERMANENT errors:
      - Mark error immediately; no retry.
    """
    current_count = await get_retry_count(redis, run.id)

    # Permanent errors skip the retry path entirely
    if kind == FailureKind.PERMANENT:
        await clear_retry_count(redis, run.id)
        run.status       = "error"
        run.completed_at = datetime.now(timezone.utc)
        await session.commit()

        logger.error(
            "Run %s permanently failed (non-retriable %s): %s",
            run.id, type(exc).__name__, exc,
            extra={
                "run_id":       run.id,
                "failure_kind": "permanent",
                "exc_type":     type(exc).__name__,
                "attempts":     current_count + 1,
            },
        )
        return

    # Transient error — increment and decide
    count = await increment_retry(redis, run.id)

    if count <= settings.RUN_MAX_RETRIES:
        delay_s      = compute_delay(count)
        expected_s   = compute_delay_no_jitter(count)   # for logging (no jitter)

        await schedule_retry(redis, run.id, delay_seconds=delay_s)
        run.status = "pending"
        await session.commit()

        logger.warning(
            "Run %s will retry in ~%ds (attempt %d/%d, expected %ds, exc=%s)",
            run.id, delay_s, count, settings.RUN_MAX_RETRIES,
            expected_s, type(exc).__name__,
            extra={
                "run_id":       run.id,
                "attempt":      count,
                "max_retries":  settings.RUN_MAX_RETRIES,
                "delay_s":      delay_s,
                "expected_s":   expected_s,
                "failure_kind": "transient",
                "exc_type":     type(exc).__name__,
            },
        )
    else:
        await clear_retry_count(redis, run.id)
        run.status       = "error"
        run.completed_at = datetime.now(timezone.utc)
        await session.commit()

        logger.error(
            "Run %s permanently failed after %d/%d attempts (last exc=%s): %s",
            run.id, count, settings.RUN_MAX_RETRIES, type(exc).__name__, exc,
            extra={
                "run_id":       run.id,
                "attempts":     count,
                "max_retries":  settings.RUN_MAX_RETRIES,
                "failure_kind": "exhausted",
                "exc_type":     type(exc).__name__,
            },
        )


# ── Startup recovery ──────────────────────────────────────────────────────────

async def recover_stalled_runs(redis: aioredis.Redis) -> int:
    """
    Called once at worker startup.

    Finds TestRun rows with status='running' and started_at older than
    RUN_STALL_THRESHOLD_SECONDS (meaning the previous worker crashed
    mid-execution) and re-queues them as 'pending'.

    Returns the number of runs recovered.
    """
    stall_cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.RUN_STALL_THRESHOLD_SECONDS
    )

    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(TestRun).where(
                TestRun.status == "running",
                TestRun.started_at <= stall_cutoff,
            )
        )
        stalled = list(rows.scalars().all())

        if not stalled:
            return 0

        for run in stalled:
            run.status = "pending"
            await enqueue_run(redis, run.id)
            logger.warning(
                "Recovered stalled run %s (started at %s)",
                run.id, run.started_at,
                extra={"run_id": run.id},
            )

        await session.commit()

    logger.info("Recovered %d stalled run(s)", len(stalled))
    return len(stalled)
