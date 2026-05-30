from sqlalchemy import select
from app.models.workspace import Workspace
from app.repositories.base import BaseRepository


class WorkspaceRepository(BaseRepository[Workspace]):
    model = Workspace

    async def list_by_user(self, user_id: str) -> list[Workspace]:
        result = await self._session.execute(
            select(Workspace)
            .where(Workspace.user_id == user_id)
            .order_by(Workspace.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_owned(self, workspace_id: str, user_id: str) -> Workspace | None:
        """Return the workspace only if it belongs to user_id."""
        result = await self._session.execute(
            select(Workspace).where(
                Workspace.id == workspace_id,
                Workspace.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()
