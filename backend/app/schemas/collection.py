from __future__ import annotations

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

T = TypeVar("T")

# ── Pagination ────────────────────────────────────────────────────────────────

class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int

    @classmethod
    def build(cls, items: list[T], total: int, page: int, page_size: int) -> "Page[T]":
        pages = max(1, (total + page_size - 1) // page_size)
        return cls(items=items, total=total, page=page, page_size=page_size, pages=pages)


# ── Assertion schemas (used in request detail) ────────────────────────────────

ASSERTION_TYPES = Literal[
    "status_code", "response_time", "json_path", "header", "body_contains"
]
ASSERTION_OPERATORS = Literal[
    "eq", "ne", "gt", "lt", "gte", "lte",
    "contains", "not_contains", "exists", "matches",
]


class AssertionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    request_id: str
    type: str
    operator: str
    expected_value: str
    path: str | None


class CreateAssertionRequest(BaseModel):
    type: ASSERTION_TYPES
    operator: ASSERTION_OPERATORS
    expected_value: str = Field(min_length=0, max_length=2000)
    path: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def path_required_for_json_path(self) -> "CreateAssertionRequest":
        if self.type == "json_path" and not self.path:
            raise ValueError("path is required when type is 'json_path'")
        return self


class UpdateAssertionRequest(BaseModel):
    type: ASSERTION_TYPES | None = None
    operator: ASSERTION_OPERATORS | None = None
    expected_value: str | None = Field(default=None, max_length=2000)
    path: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def at_least_one(self) -> "UpdateAssertionRequest":
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update")
        return self


class AssertionPreviewRequest(BaseModel):
    """
    Sample response to evaluate assertions against.

    Used by POST /requests/{id}/assertions/preview so users can validate
    their assertions locally before running a real request.
    """
    status_code: int = Field(default=200, ge=100, le=599)
    response_time_ms: int = Field(default=100, ge=0)
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = Field(default=None, max_length=1_000_000)


class AssertionPreviewResultItem(BaseModel):
    """Outcome for one assertion in a preview evaluation."""
    assertion_id: str
    type: str
    operator: str
    expected_value: str
    path: str | None
    passed: bool
    actual_value: str | None
    error_message: str | None


class AssertionPreviewResponse(BaseModel):
    """Full preview result — one item per assertion on the request."""
    total: int
    passed: int
    failed: int
    results: list[AssertionPreviewResultItem]


# ── API Request schemas ───────────────────────────────────────────────────────

HTTP_METHODS = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
BODY_TYPES   = Literal["json", "form", "raw", "none"]
AUTH_TYPES   = Literal["none", "bearer", "basic", "api_key"]


class ApiRequestOut(BaseModel):
    """Summary — returned in collection list and request list."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    collection_id: str
    name: str
    method: str
    url: str
    body_type: str
    auth_type: str
    timeout_ms: int
    order_index: int
    created_at: datetime
    updated_at: datetime


class ApiRequestDetail(ApiRequestOut):
    """Full view — includes headers, body, auth_config, and assertions."""
    headers: dict
    body: str | None
    auth_config: dict
    assertions: list[AssertionOut]


class CreateApiRequestBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    method: HTTP_METHODS = "GET"
    url: str = Field(min_length=1, max_length=2000)
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = Field(default=None, max_length=1_000_000)
    body_type: BODY_TYPES = "none"
    auth_type: AUTH_TYPES = "none"
    auth_config: dict[str, str] = Field(default_factory=dict)
    timeout_ms: int = Field(default=30_000, ge=100, le=120_000)
    order_index: int = Field(default=0, ge=0)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Request name cannot be blank")
        return v

    @field_validator("url")
    @classmethod
    def url_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("URL cannot be blank")
        return v

    @field_validator("headers")
    @classmethod
    def headers_size(cls, v: dict) -> dict:
        if len(v) > 50:
            raise ValueError("Cannot have more than 50 headers")
        return v

    @model_validator(mode="after")
    def body_required_for_body_type(self) -> "CreateApiRequestBody":
        if self.body_type != "none" and self.body_type != "json" and self.body is None:
            pass  # body is optional even with body_type set
        if self.auth_type == "none" and self.auth_config:
            self.auth_config = {}
        return self


class UpdateApiRequestBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    method: HTTP_METHODS | None = None
    url: str | None = Field(default=None, min_length=1, max_length=2000)
    headers: dict[str, str] | None = None
    body: str | None = None
    body_type: BODY_TYPES | None = None
    auth_type: AUTH_TYPES | None = None
    auth_config: dict[str, str] | None = None
    timeout_ms: int | None = Field(default=None, ge=100, le=120_000)
    order_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def at_least_one(self) -> "UpdateApiRequestBody":
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
            raise ValueError("Request name cannot be blank")
        return v


# ── Collection schemas ────────────────────────────────────────────────────────

class CollectionOut(BaseModel):
    """Summary — returned in list and after create/update."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    name: str
    description: str | None
    request_count: int = 0
    created_at: datetime
    updated_at: datetime


class CollectionDetail(CollectionOut):
    """Full view — includes all requests (without assertion detail)."""
    requests: list[ApiRequestOut]


class CreateCollectionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Collection name cannot be blank")
        return v

    @field_validator("description")
    @classmethod
    def normalise_desc(cls, v: str | None) -> str | None:
        return v.strip() or None if v else None


class UpdateCollectionRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None

    @model_validator(mode="after")
    def at_least_one(self) -> "UpdateCollectionRequest":
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
            raise ValueError("Collection name cannot be blank")
        return v
