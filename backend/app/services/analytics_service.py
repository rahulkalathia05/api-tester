from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.analytics_repo import AnalyticsRepository
from app.repositories.workspace_repo import WorkspaceRepository
from app.schemas.analytics import WorkspaceAnalytics


class AnalyticsService:

    def __init__(self, db: AsyncSession) -> None:
        self._repo    = AnalyticsRepository(db)
        self._ws_repo = WorkspaceRepository(db)

    async def get_workspace_analytics(
        self,
        user: User,
        workspace_id: str,
        days: int = 30,
    ) -> WorkspaceAnalytics:
        ws = await self._ws_repo.get_owned(workspace_id, user.id)
        if ws is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found",
            )

        # All four queries run independently — each targets different tables
        # and could be parallelised with asyncio.gather if latency matters.
        summary = await self._repo.get_summary(workspace_id, user.id, days)
        trend   = await self._repo.get_daily_trend(workspace_id, user.id, days)
        slow    = await self._repo.get_slowest_endpoints(workspace_id, user.id, days)
        colls   = await self._repo.get_collection_stats(workspace_id, user.id, days)

        return WorkspaceAnalytics(
            summary=summary,
            daily_trend=trend,
            slowest_endpoints=slow,
            collection_stats=colls,
        )
