from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_SENTINEL = "***"

# ── Variable ──────────────────────────────────────────────────────────────────

class VariableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    environment_id: str
    key: str
    value: str      # "***" when is_secret=True — real value never returned
    is_secret: bool


class CreateVariableRequest(BaseModel):
    key: str = Field(min_length=1, max_length=255)
    value: str = Field(max_length=4096)
    is_secret: bool = False

    @field_validator("key")
    @classmethod
    def key_identifier(cls, v: str) -> str:
        v = v.strip()
        if not _KEY_RE.match(v):
            raise ValueError(
                "Key must start with a letter or underscore and contain only "
                "letters, digits, and underscores (no spaces or special chars)"
            )
        return v


class UpdateVariableRequest(BaseModel):
    key: str | None = Field(default=None, max_length=255)
    value: str | None = Field(default=None, max_length=4096)
    is_secret: bool | None = None

    @model_validator(mode="after")
    def at_least_one(self) -> "UpdateVariableRequest":
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update")
        return self

    @field_validator("key")
    @classmethod
    def key_identifier(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not _KEY_RE.match(v):
            raise ValueError("Key must be a valid identifier")
        return v


class BulkVariableItem(BaseModel):
    key: str = Field(min_length=1, max_length=255)
    value: str = Field(max_length=4096)
    is_secret: bool = False

    @field_validator("key")
    @classmethod
    def key_identifier(cls, v: str) -> str:
        v = v.strip()
        if not _KEY_RE.match(v):
            raise ValueError("Key must be a valid identifier")
        return v


class BulkUpsertRequest(BaseModel):
    """
    Replace all variables for an environment.

    For secret variables (is_secret=True) where value equals "***"
    (the read-masked sentinel), the existing DB value is preserved.
    Set a non-"***" value to update a secret.
    """
    variables: list[BulkVariableItem] = Field(max_length=100)

    @model_validator(mode="after")
    def no_duplicate_keys(self) -> "BulkUpsertRequest":
        keys = [v.key for v in self.variables]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate keys are not allowed")
        return self


# ── Environment ───────────────────────────────────────────────────────────────

class EnvironmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    name: str
    is_active: bool
    created_at: datetime
    variable_count: int = 0


class EnvironmentDetail(EnvironmentOut):
    """Full view — includes variables with secrets masked."""
    variables: list[VariableOut] = []


class CreateEnvironmentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Environment name cannot be blank")
        return v


class UpdateEnvironmentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Environment name cannot be blank")
        return v


# ── Variable preview ──────────────────────────────────────────────────────────

class PreviewRequest(BaseModel):
    """
    Test how a template string would be interpolated with this environment's
    variables.  Useful for verifying {{env.BASE_URL}}/users before running.
    """
    template: str = Field(min_length=0, max_length=4000)


class PreviewResponse(BaseModel):
    result: str
    resolved_keys: list[str]    # keys that were found and substituted
    unresolved_keys: list[str]  # keys that appeared in template but had no variable
