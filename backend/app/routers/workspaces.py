from fastapi import APIRouter

from app.dependencies import CurrentUser, DBDep
from app.schemas.workspace import CreateWorkspaceRequest, UpdateWorkspaceRequest, WorkspaceOut
from app.services.workspace_service import WorkspaceService

router = APIRouter()


@router.get("", response_model=list[WorkspaceOut])
async def list_workspaces(current_user: CurrentUser, db: DBDep) -> list[WorkspaceOut]:
    return await WorkspaceService(db).list(current_user)


@router.post("", response_model=WorkspaceOut, status_code=201)
async def create_workspace(
    body: CreateWorkspaceRequest, current_user: CurrentUser, db: DBDep
) -> WorkspaceOut:
    return await WorkspaceService(db).create(current_user, body)


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
async def update_workspace(
    workspace_id: str,
    body: UpdateWorkspaceRequest,
    current_user: CurrentUser,
    db: DBDep,
) -> WorkspaceOut:
    return await WorkspaceService(db).update(workspace_id, current_user, body)


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: str, current_user: CurrentUser, db: DBDep
) -> None:
    await WorkspaceService(db).delete(workspace_id, current_user)
