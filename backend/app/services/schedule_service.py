"""
Schedule management service.

CRUD for ScheduledRun rows plus business logic:
  - Compute next_run_at on create/update using croniter
  - Recompute next_run_at on activate if it's in the past
  - Ownership verified through collection → workspace → user
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection import Collection
from app.models.scheduled_run import ScheduledRun
from app.models.test_run import TestRun
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.collection_repo import CollectionRepository
from app.repositories.schedule_repo import ScheduleRepository
from app.schemas.schedules import (
    CreateScheduleRequest,
    ScheduleHistoryItem,
    ScheduleOut,
    UpdateScheduleRequest,
)
from app.utils.cron import cron_description, next_after

_404_SCHEDULE    = HTTPException(status_code=404, detail="Schedule not found")
_404_COLLECTION  = HTTPException(status_code=404, detail="Collection not found")


def _to_out(schedule: ScheduledRun, collection_name: str | None = None) -> ScheduleOut:
    return ScheduleOut(
        id=schedule.id,
        collection_id=schedule.collection_id,
        collection_name=collection_name,
        environment_id=schedule.environment_id,
        cron_expression=schedule.cron_expression,
        cron_description=cron_description(schedule.cron_expression),
        is_active=schedule.is_active,
        last_run_at=schedule.last_run_at,
        next_run_at=schedule.next_run_at,
        created_at=schedule.created_at,
    )


class ScheduleService:

    def __init__(self, db: AsyncSession) -> None:
        self._db      = db
        self._repo    = ScheduleRepository(db)
        self._col_repo = CollectionRepository(db)

    async def _assert_collection_owned(self, collection_id: str, user_id: str) -> Collection:
        col = await self._col_repo.get_owned(collection_id, user_id)
        if col is None:
            raise _404_COLLECTION
        return col

    # ── CRUD ──────────────────────────────────────────────────────────────────

    async def list_schedules(
        self, user: User, collection_id: str
    ) -> list[ScheduleOut]:
        await self._assert_collection_owned(collection_id, user.id)
        rows = await self._repo.list_by_collection(collection_id, user.id)
        return [_to_out(s, cname) for s, cname in rows]

    async def create_schedule(
        self,
        user: User,
        collection_id: str,
        body: CreateScheduleRequest,
    ) -> ScheduleOut:
        await self._assert_collection_owned(collection_id, user.id)

        now      = datetime.now(timezone.utc)
        next_run = next_after(body.cron_expression, now) if body.is_active else None

        schedule = ScheduledRun(
            collection_id=collection_id,
            environment_id=body.environment_id,
            cron_expression=body.cron_expression,
            is_active=body.is_active,
            next_run_at=next_run,
        )
        self._db.add(schedule)
        await self._db.flush()
        return _to_out(schedule)

    async def get_schedule(self, user: User, schedule_id: str) -> ScheduleOut:
        schedule = await self._repo.get_owned(schedule_id, user.id)
        if schedule is None:
            raise _404_SCHEDULE
        return _to_out(schedule)

    async def update_schedule(
        self,
        user: User,
        schedule_id: str,
        body: UpdateScheduleRequest,
    ) -> ScheduleOut:
        schedule = await self._repo.get_owned(schedule_id, user.id)
        if schedule is None:
            raise _404_SCHEDULE

        now = datetime.now(timezone.utc)

        if body.cron_expression is not None:
            schedule.cron_expression = body.cron_expression
            # Recompute next fire time based on new expression
            if schedule.is_active:
                schedule.next_run_at = next_after(schedule.cron_expression, now)

        if "environment_id" in body.model_fields_set:
            schedule.environment_id = body.environment_id

        if body.is_active is not None:
            was_active = schedule.is_active
            schedule.is_active = body.is_active

            if body.is_active and not was_active:
                # Re-activating: compute next run from now
                schedule.next_run_at = next_after(schedule.cron_expression, now)
            elif not body.is_active:
                schedule.next_run_at = None  # clear when deactivated

        await self._db.flush()
        return _to_out(schedule)

    async def delete_schedule(self, user: User, schedule_id: str) -> None:
        schedule = await self._repo.get_owned(schedule_id, user.id)
        if schedule is None:
            raise _404_SCHEDULE
        await self._db.delete(schedule)
        await self._db.flush()

    async def activate(self, user: User, schedule_id: str) -> ScheduleOut:
        schedule = await self._repo.get_owned(schedule_id, user.id)
        if schedule is None:
            raise _404_SCHEDULE
        schedule.is_active   = True
        schedule.next_run_at = next_after(schedule.cron_expression, datetime.now(timezone.utc))
        await self._db.flush()
        return _to_out(schedule)

    async def deactivate(self, user: User, schedule_id: str) -> ScheduleOut:
        schedule = await self._repo.get_owned(schedule_id, user.id)
        if schedule is None:
            raise _404_SCHEDULE
        schedule.is_active   = False
        schedule.next_run_at = None
        await self._db.flush()
        return _to_out(schedule)

    # ── Execution history ──────────────────────────────────────────────────────

    async def get_history(
        self,
        user: User,
        schedule_id: str,
        limit: int = 20,
    ) -> list[ScheduleHistoryItem]:
        """
        Return the most recent TestRuns triggered by this schedule.

        Since TestRun has no schedule_id FK, we filter by collection_id +
        trigger_type='scheduled', ordered newest first.
        """
        schedule = await self._repo.get_owned(schedule_id, user.id)
        if schedule is None:
            raise _404_SCHEDULE

        rows = await self._db.execute(
            select(TestRun)
            .join(Workspace, Workspace.id == TestRun.workspace_id)
            .where(
                TestRun.collection_id  == schedule.collection_id,
                TestRun.trigger_type   == "scheduled",
                Workspace.user_id      == user.id,
            )
            .order_by(TestRun.started_at.desc().nullslast())
            .limit(limit)
        )
        runs = list(rows.scalars().all())

        def _duration(run: TestRun) -> int | None:
            if run.started_at and run.completed_at:
                return round((run.completed_at - run.started_at).total_seconds() * 1000)
            return None

        return [
            ScheduleHistoryItem(
                run_id=r.id,
                status=r.status,
                total=r.total,
                passed=r.passed,
                failed=r.failed,
                started_at=r.started_at,
                completed_at=r.completed_at,
                duration_ms=_duration(r),
            )
            for r in runs
        ]
