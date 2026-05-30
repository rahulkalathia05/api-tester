from fastapi import APIRouter, Query

from app.dependencies import CurrentUser, DBDep
from app.schemas.schedules import (
    CreateScheduleRequest,
    PRESETS,
    ScheduleHistoryItem,
    ScheduleOut,
    SchedulePreset,
    UpdateScheduleRequest,
)
from app.services.schedule_service import ScheduleService

router = APIRouter(tags=["schedules"])


# ── Presets ───────────────────────────────────────────────────────────────────

@router.get("/schedules/presets", response_model=list[SchedulePreset])
async def list_presets() -> list[SchedulePreset]:
    """Return common cron preset options for the UI picker."""
    return PRESETS


# ── Collection-scoped CRUD ────────────────────────────────────────────────────

@router.get(
    "/collections/{collection_id}/schedules",
    response_model=list[ScheduleOut],
)
async def list_schedules(
    collection_id: str,
    current_user: CurrentUser,
    db: DBDep,
) -> list[ScheduleOut]:
    return await ScheduleService(db).list_schedules(current_user, collection_id)


@router.post(
    "/collections/{collection_id}/schedules",
    response_model=ScheduleOut,
    status_code=201,
)
async def create_schedule(
    collection_id: str,
    body: CreateScheduleRequest,
    current_user: CurrentUser,
    db: DBDep,
) -> ScheduleOut:
    return await ScheduleService(db).create_schedule(current_user, collection_id, body)


# ── Individual schedule operations ───────────────────────────────────────────

@router.get("/schedules/{schedule_id}", response_model=ScheduleOut)
async def get_schedule(
    schedule_id: str,
    current_user: CurrentUser,
    db: DBDep,
) -> ScheduleOut:
    return await ScheduleService(db).get_schedule(current_user, schedule_id)


@router.patch("/schedules/{schedule_id}", response_model=ScheduleOut)
async def update_schedule(
    schedule_id: str,
    body: UpdateScheduleRequest,
    current_user: CurrentUser,
    db: DBDep,
) -> ScheduleOut:
    return await ScheduleService(db).update_schedule(current_user, schedule_id, body)


@router.delete("/schedules/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: str,
    current_user: CurrentUser,
    db: DBDep,
) -> None:
    await ScheduleService(db).delete_schedule(current_user, schedule_id)


@router.post("/schedules/{schedule_id}/activate", response_model=ScheduleOut)
async def activate_schedule(
    schedule_id: str,
    current_user: CurrentUser,
    db: DBDep,
) -> ScheduleOut:
    """Enable the schedule and recompute next_run_at from now."""
    return await ScheduleService(db).activate(current_user, schedule_id)


@router.post("/schedules/{schedule_id}/deactivate", response_model=ScheduleOut)
async def deactivate_schedule(
    schedule_id: str,
    current_user: CurrentUser,
    db: DBDep,
) -> ScheduleOut:
    """Pause the schedule without deleting it."""
    return await ScheduleService(db).deactivate(current_user, schedule_id)


# ── Execution history ─────────────────────────────────────────────────────────

@router.get(
    "/schedules/{schedule_id}/history",
    response_model=list[ScheduleHistoryItem],
    summary="Recent runs triggered by this schedule",
)
async def schedule_history(
    schedule_id: str,
    current_user: CurrentUser,
    db: DBDep,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[ScheduleHistoryItem]:
    return await ScheduleService(db).get_history(current_user, schedule_id, limit=limit)
