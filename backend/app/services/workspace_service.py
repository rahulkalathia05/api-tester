from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.workspace_repo import WorkspaceRepository
from app.schemas.workspace import CreateWorkspaceRequest, UpdateWorkspaceRequest, WorkspaceOut


class WorkspaceService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = WorkspaceRepository(db)

    async def list(self, user: User) -> list[WorkspaceOut]:
        rows = await self._repo.list_by_user(user.id)
        return [WorkspaceOut.model_validate(w) for w in rows]

    async def create(self, user: User, body: CreateWorkspaceRequest) -> WorkspaceOut:
        workspace = await self._repo.create(
            user_id=user.id,
            name=body.name,
            description=body.description,
        )
        return WorkspaceOut.model_validate(workspace)

    async def update(self, workspace_id: str, user: User, body: UpdateWorkspaceRequest) -> WorkspaceOut:
        workspace = await self._repo.get_owned(workspace_id, user.id)
        if workspace is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        if body.name is not None:
            workspace.name = body.name
        if "description" in body.model_fields_set:
            workspace.description = body.description
        return WorkspaceOut.model_validate(workspace)

    async def delete(self, workspace_id: str, user: User) -> None:
        workspace = await self._repo.get_owned(workspace_id, user.id)
        if workspace is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        await self._repo.delete(workspace)
