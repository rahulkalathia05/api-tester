from fastapi import APIRouter

from app.dependencies import CurrentUser, DBDep
from app.schemas.environments import (
    BulkUpsertRequest,
    CreateEnvironmentRequest,
    CreateVariableRequest,
    EnvironmentDetail,
    EnvironmentOut,
    PreviewRequest,
    PreviewResponse,
    UpdateEnvironmentRequest,
    UpdateVariableRequest,
    VariableOut,
)
from app.services.environment_service import EnvironmentService

router = APIRouter(tags=["environments"])


# ── Environments ──────────────────────────────────────────────────────────────

@router.get("/workspaces/{workspace_id}/environments",
            response_model=list[EnvironmentOut])
async def list_environments(
    workspace_id: str, current_user: CurrentUser, db: DBDep
) -> list[EnvironmentOut]:
    return await EnvironmentService(db).list_environments(current_user, workspace_id)


@router.post("/workspaces/{workspace_id}/environments",
             response_model=EnvironmentOut, status_code=201)
async def create_environment(
    workspace_id: str,
    body: CreateEnvironmentRequest,
    current_user: CurrentUser,
    db: DBDep,
) -> EnvironmentOut:
    return await EnvironmentService(db).create_environment(current_user, workspace_id, body)


@router.get("/environments/{env_id}", response_model=EnvironmentDetail)
async def get_environment(
    env_id: str, current_user: CurrentUser, db: DBDep
) -> EnvironmentDetail:
    return await EnvironmentService(db).get_environment(current_user, env_id)


@router.patch("/environments/{env_id}", response_model=EnvironmentOut)
async def update_environment(
    env_id: str,
    body: UpdateEnvironmentRequest,
    current_user: CurrentUser,
    db: DBDep,
) -> EnvironmentOut:
    return await EnvironmentService(db).update_environment(current_user, env_id, body)


@router.delete("/environments/{env_id}", status_code=204)
async def delete_environment(
    env_id: str, current_user: CurrentUser, db: DBDep
) -> None:
    await EnvironmentService(db).delete_environment(current_user, env_id)


@router.post("/environments/{env_id}/activate", response_model=EnvironmentOut)
async def activate_environment(
    env_id: str, current_user: CurrentUser, db: DBDep
) -> EnvironmentOut:
    """Set this environment as active; deactivates all others in the workspace."""
    return await EnvironmentService(db).activate_environment(current_user, env_id)


@router.post("/environments/{env_id}/deactivate", response_model=EnvironmentOut)
async def deactivate_environment(
    env_id: str, current_user: CurrentUser, db: DBDep
) -> EnvironmentOut:
    return await EnvironmentService(db).deactivate_environment(current_user, env_id)


# ── Variables ─────────────────────────────────────────────────────────────────

@router.get("/environments/{env_id}/variables",
            response_model=list[VariableOut])
async def list_variables(
    env_id: str, current_user: CurrentUser, db: DBDep
) -> list[VariableOut]:
    return await EnvironmentService(db).list_variables(current_user, env_id)


@router.post("/environments/{env_id}/variables",
             response_model=VariableOut, status_code=201)
async def create_variable(
    env_id: str,
    body: CreateVariableRequest,
    current_user: CurrentUser,
    db: DBDep,
) -> VariableOut:
    return await EnvironmentService(db).create_variable(current_user, env_id, body)


@router.put("/environments/{env_id}/variables",
            response_model=list[VariableOut],
            summary="Bulk replace all variables for an environment")
async def bulk_upsert_variables(
    env_id: str,
    body: BulkUpsertRequest,
    current_user: CurrentUser,
    db: DBDep,
) -> list[VariableOut]:
    return await EnvironmentService(db).bulk_upsert_variables(current_user, env_id, body)


@router.patch("/variables/{var_id}", response_model=VariableOut)
async def update_variable(
    var_id: str,
    body: UpdateVariableRequest,
    current_user: CurrentUser,
    db: DBDep,
) -> VariableOut:
    return await EnvironmentService(db).update_variable(current_user, var_id, body)


@router.delete("/variables/{var_id}", status_code=204)
async def delete_variable(
    var_id: str, current_user: CurrentUser, db: DBDep
) -> None:
    await EnvironmentService(db).delete_variable(current_user, var_id)


# ── Preview ───────────────────────────────────────────────────────────────────

@router.post("/environments/{env_id}/preview",
             response_model=PreviewResponse,
             summary="Test variable interpolation without executing a request")
async def preview_interpolation(
    env_id: str,
    body: PreviewRequest,
    current_user: CurrentUser,
    db: DBDep,
) -> PreviewResponse:
    return await EnvironmentService(db).preview_interpolation(current_user, env_id, body)
