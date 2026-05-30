"""
Analytics aggregation queries.

All queries join through workspaces to enforce ownership.
Uses func.date() for day-bucketing — works on both SQLite and PostgreSQL.
Uses JSON column subscript for portable JSON field extraction.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection import Collection
from app.models.test_result import TestResult
from app.models.test_run import TestRun
from app.models.workspace import Workspace
from app.schemas.analytics import (
    AnalyticsSummary,
    CollectionStat,
    DayStat,
    EndpointStat,
)


class AnalyticsRepository:

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _cutoff(self, days: int) -> datetime:
        return datetime.now(timezone.utc) - timedelta(days=days)

    # ── Query 1: KPI summary ──────────────────────────────────────────────────

    async def get_summary(
        self, workspace_id: str, user_id: str, days: int
    ) -> AnalyticsSummary:
        cutoff = self._cutoff(days)

        # ── Run-level aggregation ──────────────────────────────────────────────
        run_row = (await self._session.execute(
            select(
                func.count(TestRun.id).label("total"),
                func.sum(case((TestRun.status == "passed", 1), else_=0)).label("passed"),
                func.sum(case((TestRun.status == "failed", 1), else_=0)).label("failed"),
                func.sum(case((TestRun.status == "error",  1), else_=0)).label("errors"),
            )
            .join(Workspace, Workspace.id == TestRun.workspace_id)
            .where(
                TestRun.workspace_id == workspace_id,
                Workspace.user_id    == user_id,
                TestRun.started_at   >= cutoff,
            )
        )).mappings().one()

        # ── Result-level aggregation (latency + exec counts) ──────────────────
        res_row = (await self._session.execute(
            select(
                func.count(TestResult.id).label("total"),
                func.sum(case((TestResult.status == "passed", 1), else_=0)).label("passed"),
                func.sum(case((TestResult.status == "failed", 1), else_=0)).label("failed"),
                func.avg(TestResult.response_time_ms).label("avg_ms"),
            )
            .join(TestRun,   TestRun.id   == TestResult.test_run_id)
            .join(Workspace, Workspace.id == TestRun.workspace_id)
            .where(
                TestRun.workspace_id    == workspace_id,
                Workspace.user_id       == user_id,
                TestResult.executed_at  >= cutoff,
            )
        )).mappings().one()

        # ── Approximate P95 — fetch all latencies, compute in Python ─────────
        # Avoid window functions that differ across databases.
        latencies_result = await self._session.execute(
            select(TestResult.response_time_ms)
            .join(TestRun,   TestRun.id   == TestResult.test_run_id)
            .join(Workspace, Workspace.id == TestRun.workspace_id)
            .where(
                TestRun.workspace_id       == workspace_id,
                Workspace.user_id          == user_id,
                TestResult.executed_at     >= cutoff,
                TestResult.response_time_ms.isnot(None),
            )
            .order_by(TestResult.response_time_ms)
        )
        latencies = [r[0] for r in latencies_result.all()]
        p95: float | None = None
        if latencies:
            idx = max(0, int(len(latencies) * 0.95) - 1)
            p95 = float(latencies[idx])

        total   = int(run_row["total"] or 0)
        passed  = int(run_row["passed"] or 0)
        failed  = int(run_row["failed"] or 0)
        errors  = int(run_row["errors"] or 0)

        return AnalyticsSummary(
            days=days,
            total_runs=total,
            passed_runs=passed,
            failed_runs=failed,
            error_runs=errors,
            pass_rate=passed / total if total else 0.0,
            total_executions=int(res_row["total"] or 0),
            passed_executions=int(res_row["passed"] or 0),
            failed_executions=int(res_row["failed"] or 0),
            avg_response_time_ms=float(res_row["avg_ms"]) if res_row["avg_ms"] else None,
            p95_response_time_ms=p95,
        )

    # ── Query 2: Daily trend ──────────────────────────────────────────────────

    async def get_daily_trend(
        self, workspace_id: str, user_id: str, days: int
    ) -> list[DayStat]:
        cutoff = self._cutoff(days)

        rows = (await self._session.execute(
            select(
                func.date(TestRun.started_at).label("day"),
                func.count(TestRun.id).label("total"),
                func.sum(case((TestRun.status == "passed", 1), else_=0)).label("passed"),
                func.sum(case((TestRun.status == "failed", 1), else_=0)).label("failed"),
            )
            .join(Workspace, Workspace.id == TestRun.workspace_id)
            .where(
                TestRun.workspace_id == workspace_id,
                Workspace.user_id    == user_id,
                TestRun.started_at   >= cutoff,
                TestRun.started_at.isnot(None),
            )
            .group_by(func.date(TestRun.started_at))
            .order_by(func.date(TestRun.started_at))
        )).mappings().all()

        return [
            DayStat(
                date=str(r["day"]),
                total=int(r["total"]),
                passed=int(r["passed"] or 0),
                failed=int(r["failed"] or 0),
                pass_rate=int(r["passed"] or 0) / int(r["total"]) if r["total"] else 0.0,
            )
            for r in rows
        ]

    # ── Query 3: Slowest endpoints ────────────────────────────────────────────

    async def get_slowest_endpoints(
        self,
        workspace_id: str,
        user_id: str,
        days: int,
        limit: int = 10,
    ) -> list[EndpointStat]:
        cutoff = self._cutoff(days)

        # JSON subscript notation — SQLAlchemy 2.x maps this to:
        #   SQLite   → json_extract(col, '$.key')
        #   PostgreSQL → col->>'key'
        name_col   = TestResult.request_snapshot["name"].as_string()
        method_col = TestResult.request_snapshot["method"].as_string()
        url_col    = TestResult.request_snapshot["url"].as_string()

        rows = (await self._session.execute(
            select(
                TestResult.request_id,
                func.max(name_col).label("name"),
                func.max(method_col).label("method"),
                func.max(url_col).label("url"),
                func.count(TestResult.id).label("total"),
                func.avg(TestResult.response_time_ms).label("avg_ms"),
                func.max(TestResult.response_time_ms).label("max_ms"),
                func.sum(case((TestResult.status == "passed", 1), else_=0)).label("passed"),
            )
            .join(TestRun,   TestRun.id   == TestResult.test_run_id)
            .join(Workspace, Workspace.id == TestRun.workspace_id)
            .where(
                TestRun.workspace_id       == workspace_id,
                Workspace.user_id          == user_id,
                TestResult.executed_at     >= cutoff,
                TestResult.response_time_ms.isnot(None),
            )
            .group_by(TestResult.request_id)
            .order_by(func.avg(TestResult.response_time_ms).desc())
            .limit(limit)
        )).mappings().all()

        return [
            EndpointStat(
                request_id=r["request_id"],
                name=r["name"] or "Unknown",
                method=r["method"] or "?",
                url=r["url"] or "—",
                total_executions=int(r["total"]),
                avg_response_time_ms=float(r["avg_ms"] or 0),
                max_response_time_ms=int(r["max_ms"] or 0),
                pass_rate=int(r["passed"] or 0) / int(r["total"]) if r["total"] else 0.0,
            )
            for r in rows
        ]

    # ── Query 4: Collection reliability ───────────────────────────────────────

    async def get_collection_stats(
        self, workspace_id: str, user_id: str, days: int
    ) -> list[CollectionStat]:
        cutoff = self._cutoff(days)

        rows = (await self._session.execute(
            select(
                TestRun.collection_id,
                Collection.name.label("collection_name"),
                func.count(TestRun.id).label("total"),
                func.sum(case((TestRun.status == "passed", 1), else_=0)).label("passed"),
                func.avg(TestResult.response_time_ms).label("avg_ms"),
            )
            .join(Workspace,  Workspace.id  == TestRun.workspace_id)
            .join(Collection, Collection.id == TestRun.collection_id)
            # Left join results for avg latency (optional — runs may have no results)
            .outerjoin(TestResult, TestResult.test_run_id == TestRun.id)
            .where(
                TestRun.workspace_id == workspace_id,
                Workspace.user_id    == user_id,
                TestRun.started_at   >= cutoff,
                TestRun.collection_id.isnot(None),
            )
            .group_by(TestRun.collection_id, Collection.name)
            .order_by(func.count(TestRun.id).desc())
        )).mappings().all()

        return [
            CollectionStat(
                collection_id=r["collection_id"],
                collection_name=r["collection_name"] or "Unknown",
                total_runs=int(r["total"]),
                passed_runs=int(r["passed"] or 0),
                pass_rate=int(r["passed"] or 0) / int(r["total"]) if r["total"] else 0.0,
                avg_response_time_ms=float(r["avg_ms"]) if r["avg_ms"] else None,
            )
            for r in rows
        ]
