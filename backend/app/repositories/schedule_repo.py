from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection import Collection
from app.models.scheduled_run import ScheduledRun
from app.models.workspace import Workspace
from app.repositories.base import BaseRepository


class ScheduleRepository(BaseRepository[ScheduledRun]):
    model = ScheduledRun

    async def get_owned(self, schedule_id: str, user_id: str) -> ScheduledRun | None:
        """Return the schedule only if its collection's workspace belongs to user_id."""
        row = await self._session.execute(
            select(ScheduledRun)
            .join(Collection, Collection.id == ScheduledRun.collection_id)
            .join(Workspace,  Workspace.id  == Collection.workspace_id)
            .where(
                ScheduledRun.id == schedule_id,
                Workspace.user_id == user_id,
            )
        )
        return row.scalar_one_or_none()

    async def list_by_collection(
        self, collection_id: str, user_id: str
    ) -> list[tuple[ScheduledRun, str]]:
        """
        Return (schedule, collection_name) tuples for all schedules on the
        given collection, verifying workspace ownership.
        """
        rows = await self._session.execute(
            select(ScheduledRun, Collection.name.label("cname"))
            .join(Collection, Collection.id == ScheduledRun.collection_id)
            .join(Workspace,  Workspace.id  == Collection.workspace_id)
            .where(
                ScheduledRun.collection_id == collection_id,
                Workspace.user_id          == user_id,
            )
            .order_by(ScheduledRun.created_at)
        )
        return [(r.ScheduledRun, r.cname) for r in rows.all()]

    async def find_due(self, now: datetime) -> list[tuple[ScheduledRun, str]]:
        """
        Return (schedule, workspace_id) tuples for active schedules whose
        next_run_at has arrived.

        The workspace_id is needed to create the TestRun record.
        """
        rows = await self._session.execute(
            select(ScheduledRun, Workspace.id.label("workspace_id"))
            .join(Collection, Collection.id == ScheduledRun.collection_id)
            .join(Workspace,  Workspace.id  == Collection.workspace_id)
            .where(
                ScheduledRun.is_active    == True,      # noqa: E712
                ScheduledRun.next_run_at  <= now,
                ScheduledRun.next_run_at.isnot(None),
            )
        )
        return [(r.ScheduledRun, r.workspace_id) for r in rows.all()]
