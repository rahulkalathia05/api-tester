from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    name: str
    description: str | None
    created_at: datetime


class CreateWorkspaceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Workspace name cannot be blank")
        return v

    @field_validator("description")
    @classmethod
    def normalise_desc(cls, v: str | None) -> str | None:
        return v.strip() or None if v else None


class UpdateWorkspaceRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None

    @model_validator(mode="after")
    def at_least_one(self) -> "UpdateWorkspaceRequest":
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update")
        return self

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Workspace name cannot be blank")
        return v
