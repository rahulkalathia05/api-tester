from fastapi import APIRouter, Query

from app.dependencies import CurrentUser, DBDep
from app.schemas.analytics import WorkspaceAnalytics
from app.services.analytics_service import AnalyticsService

router = APIRouter(tags=["analytics"])


@router.get(
    "/workspaces/{workspace_id}/analytics",
    response_model=WorkspaceAnalytics,
    summary="Full analytics for a workspace",
    description=(
        "Returns all dashboard data in a single call: KPI summary, "
        "daily pass/fail trend, top 10 slowest endpoints, and per-collection "
        "reliability stats. Scoped to the last `days` calendar days."
    ),
)
async def get_analytics(
    workspace_id: str,
    current_user: CurrentUser,
    db: DBDep,
    days: int = Query(default=30, ge=1, le=365, description="Look-back window in days"),
) -> WorkspaceAnalytics:
    return await AnalyticsService(db).get_workspace_analytics(
        current_user, workspace_id, days=days
    )
