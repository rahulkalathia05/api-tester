from __future__ import annotations

from datetime import datetime

from sqlalchemy import asc, case, desc, func, select
from sqlalchemy.orm import selectinload

from app.models.collection import Collection
from app.models.test_result import TestResult
from app.models.test_run import TestRun
from app.models.workspace import Workspace
from app.repositories.base import BaseRepository

_SORT_COLUMNS = {
    "started_at":   TestRun.started_at,
    "completed_at": TestRun.completed_at,
    "status":       TestRun.status,
    "total":        TestRun.total,
    "passed":       TestRun.passed,
}


class TestRunRepository(BaseRepository[TestRun]):
    model = TestRun

    async def get_owned(self, run_id: str, user_id: str) -> TestRun | None:
        result = await self._session.execute(
            select(TestRun)
            .join(Workspace, Workspace.id == TestRun.workspace_id)
            .where(TestRun.id == run_id, Workspace.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_detail(self, run_id: str, user_id: str) -> TestRun | None:
        """Run with eagerly loaded results and their assertion outcomes."""
        result = await self._session.execute(
            select(TestRun)
            .join(Workspace, Workspace.id == TestRun.workspace_id)
            .where(TestRun.id == run_id, Workspace.user_id == user_id)
            .options(
                selectinload(TestRun.results).selectinload(TestResult.assertion_results)
            )
        )
        return result.scalar_one_or_none()

    async def list_by_workspace(
        self,
        workspace_id: str,
        user_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        trigger_type: str | None = None,
        collection_id: str | None = None,
        started_after: datetime | None = None,
        started_before: datetime | None = None,
        sort_by: str = "started_at",
        sort_dir: str = "desc",
    ) -> tuple[list[tuple[TestRun, str | None]], int]:
        """
        Return ((TestRun, collection_name), total).

        collection_name is left-joined so the list can show it without N+1.
        """
        base = (
            select(TestRun, Collection.name.label("cname"))
            .join(Workspace, Workspace.id == TestRun.workspace_id)
            .outerjoin(Collection, Collection.id == TestRun.collection_id)
            .where(
                TestRun.workspace_id == workspace_id,
                Workspace.user_id == user_id,
            )
        )

        if status:
            base = base.where(TestRun.status == status)
        if trigger_type:
            base = base.where(TestRun.trigger_type == trigger_type)
        if collection_id:
            base = base.where(TestRun.collection_id == collection_id)
        if started_after:
            base = base.where(TestRun.started_at >= started_after)
        if started_before:
            base = base.where(TestRun.started_at <= started_before)

        total: int = (
            await self._session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar() or 0

        col_expr = _SORT_COLUMNS.get(sort_by, TestRun.started_at)
        order_fn = asc if sort_dir == "asc" else desc
        rows = await self._session.execute(
            base.order_by(order_fn(col_expr).nullslast(), desc(TestRun.id))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return [(r.TestRun, r.cname) for r in rows.all()], total

    async def get_stats(self, workspace_id: str, user_id: str) -> dict:
        """Aggregate counts — one query for all history header cards."""
        result = await self._session.execute(
            select(
                func.count(TestRun.id).label("total"),
                func.sum(case((TestRun.status == "passed", 1), else_=0)).label("passed"),
                func.sum(case((TestRun.status == "failed", 1), else_=0)).label("failed"),
                func.sum(case((TestRun.status == "error",  1), else_=0)).label("errors"),
            )
            .join(Workspace, Workspace.id == TestRun.workspace_id)
            .where(
                TestRun.workspace_id == workspace_id,
                Workspace.user_id == user_id,
            )
        )
        return dict(result.mappings().one())


class TestResultRepository(BaseRepository[TestResult]):
    model = TestResult

    async def get_detail(self, result_id: str, user_id: str) -> TestResult | None:
        result = await self._session.execute(
            select(TestResult)
            .join(TestRun, TestRun.id == TestResult.test_run_id)
            .join(Workspace, Workspace.id == TestRun.workspace_id)
            .where(TestResult.id == result_id, Workspace.user_id == user_id)
            .options(selectinload(TestResult.assertion_results))
        )
        return result.scalar_one_or_none()
