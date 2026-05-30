from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.utils.cron import cron_description, next_after, validate_cron


# ── Preset schedules ──────────────────────────────────────────────────────────
# Returned by GET /schedules/presets so the UI can offer a picker.

class SchedulePreset(BaseModel):
    label: str           # "Every hour"
    cron: str            # "0 * * * *"
    description: str     # human-readable expansion


PRESETS: list[SchedulePreset] = [
    SchedulePreset(label="Every hour",       cron="0 * * * *",   description="At minute 0 of every hour"),
    SchedulePreset(label="Every 6 hours",    cron="0 */6 * * *", description="At minute 0, every 6 hours"),
    SchedulePreset(label="Daily at 9 am",    cron="0 9 * * *",   description="Every day at 09:00 UTC"),
    SchedulePreset(label="Daily at midnight",cron="0 0 * * *",   description="Every day at 00:00 UTC"),
    SchedulePreset(label="Weekly (Mon 9am)", cron="0 9 * * 1",   description="Every Monday at 09:00 UTC"),
    SchedulePreset(label="Every 15 minutes", cron="*/15 * * * *",description="Every 15 minutes"),
]


# ── CRUD schemas ──────────────────────────────────────────────────────────────

class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    collection_id: str
    collection_name: str | None = None    # joined from collections table
    environment_id: str | None
    cron_expression: str
    cron_description: str = ""            # computed on read
    is_active: bool
    last_run_at: datetime | None
    next_run_at: datetime | None
    created_at: datetime


class CreateScheduleRequest(BaseModel):
    cron_expression: str = Field(min_length=5, max_length=100)
    environment_id: str | None = None
    is_active: bool = True

    @field_validator("cron_expression")
    @classmethod
    def valid_cron(cls, v: str) -> str:
        v = v.strip()
        if not validate_cron(v):
            raise ValueError(
                f"'{v}' is not a valid cron expression. "
                "Expected 5 fields: minute hour day-of-month month day-of-week. "
                "Example: '0 9 * * *' (daily at 09:00 UTC)"
            )
        return v


class UpdateScheduleRequest(BaseModel):
    cron_expression: str | None = Field(default=None, min_length=5, max_length=100)
    environment_id: str | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def at_least_one(self) -> "UpdateScheduleRequest":
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update")
        return self

    @field_validator("cron_expression")
    @classmethod
    def valid_cron(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not validate_cron(v):
            raise ValueError(f"'{v}' is not a valid cron expression")
        return v


# ── History summary ───────────────────────────────────────────────────────────

class ScheduleHistoryItem(BaseModel):
    """Compact TestRun summary used in schedule history."""
    model_config = ConfigDict(from_attributes=True)

    run_id: str
    status: str
    total: int
    passed: int
    failed: int
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
