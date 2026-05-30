import time
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from app.config import settings
from app.models.test_run import TestRun
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.workspace_repo import WorkspaceRepository
from app.schemas.runner import CancelRunResponse, QueueStatus, RetryStatus
from app.utils.backoff import compute_delay_no_jitter, delay_sequence
from app.worker.queue import get_retry_count, queue_length, scheduled_count


class QueueService:

    def __init__(
        self,
        db: AsyncSession,
        redis: aioredis.Redis | None = None,
    ) -> None:
        self._db      = db
        self._redis   = redis
        self._ws_repo = WorkspaceRepository(db)

    async def _load_run_owned(self, run_id: str, user_id: str) -> TestRun:
        row = await self._db.execute(
            select(TestRun)
            .join(Workspace, Workspace.id == TestRun.workspace_id)
            .where(TestRun.id == run_id, Workspace.user_id == user_id)
        )
        run = row.scalar_one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    async def get_status(
        self, user: User, workspace_id: str
    ) -> QueueStatus:
        if await self._ws_repo.get_owned(workspace_id, user.id) is None:
            raise HTTPException(status_code=404, detail="Workspace not found")

        pending_row = await self._db.execute(
            select(func.count(TestRun.id))
            .join(Workspace, Workspace.id == TestRun.workspace_id)
            .where(
                TestRun.workspace_id == workspace_id,
                Workspace.user_id    == user.id,
                TestRun.status       == "pending",
            )
        )
        total_pending = pending_row.scalar() or 0

        depth     = await queue_length(self._redis) if self._redis else 0
        scheduled = await scheduled_count(self._redis) if self._redis else 0

        return QueueStatus(
            queue_depth=depth,
            scheduled_retries=scheduled,
            total_pending=total_pending,
        )

    async def cancel_run(self, user: User, run_id: str) -> CancelRunResponse:
        run = await self._load_run_owned(run_id, user.id)

        if run.status == "cancelled":
            return CancelRunResponse(
                run_id=run_id, cancelled=False,
                message="Run was already cancelled",
            )

        if run.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Cannot cancel a run with status='{run.status}'. "
                       "Only pending runs can be cancelled.",
            )

        run.status = "cancelled"
        await self._db.flush()
        return CancelRunResponse(run_id=run_id, cancelled=True,
                                  message="Run cancelled successfully")

    async def get_retry_status(
        self, user: User, run_id: str
    ) -> RetryStatus:
        """
        Return the current retry state for a run — attempt count, next retry
        timestamp, projected schedule for remaining attempts, and failure kind.
        """
        run = await self._load_run_owned(run_id, user.id)

        attempt_count = 0
        next_retry_at = None
        is_retrying   = False
        failure_kind  = None

        if self._redis:
            attempt_count = await get_retry_count(self._redis, run_id)

            if run.status == "pending":
                # Check if it has a scheduled retry (vs. just newly queued)
                score = await self._redis.zscore(
                    settings.RUN_SCHEDULED_KEY, run_id
                )
                if score is not None:
                    is_retrying   = True
                    next_retry_at = datetime.fromtimestamp(score, tz=timezone.utc)

        # Determine failure_kind from run status
        if run.status == "error":
            if attempt_count == 0:
                failure_kind = "permanent"
            else:
                failure_kind = "exhausted"
        elif is_retrying:
            failure_kind = "transient"

        remaining = max(0, settings.RUN_MAX_RETRIES - attempt_count)
        # Projected delays for remaining retries (deterministic, no jitter)
        retry_schedule = [
            compute_delay_no_jitter(attempt_count + i + 1)
            for i in range(remaining)
        ]

        return RetryStatus(
            run_id=run_id,
            run_status=run.status,
            attempt_count=attempt_count,
            max_retries=settings.RUN_MAX_RETRIES,
            attempts_remaining=remaining,
            is_retrying=is_retrying,
            next_retry_at=next_retry_at,
            retry_schedule=retry_schedule,
            failure_kind=failure_kind,
        )
