from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assertion import Assertion
from app.models.user import User
from app.repositories.collection_repo import ApiRequestRepository, CollectionRepository
from app.repositories.workspace_repo import WorkspaceRepository
from app.schemas.collection import (
    ApiRequestDetail,
    ApiRequestOut,
    AssertionOut,
    CollectionDetail,
    CollectionOut,
    CreateApiRequestBody,
    CreateAssertionRequest,
    CreateCollectionRequest,
    AssertionPreviewRequest,
    AssertionPreviewResponse,
    AssertionPreviewResultItem,
    Page,
    UpdateApiRequestBody,
    UpdateAssertionRequest,
    UpdateCollectionRequest,
)

_404_COLLECTION = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
_404_REQUEST    = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
_404_ASSERTION  = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assertion not found")
_404_WORKSPACE  = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")


class CollectionService:

    def __init__(self, db: AsyncSession) -> None:
        self._db       = db
        self._repo     = CollectionRepository(db)
        self._req_repo = ApiRequestRepository(db)
        self._ws_repo  = WorkspaceRepository(db)

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _assert_workspace_owned(self, workspace_id: str, user_id: str) -> None:
        if await self._ws_repo.get_owned(workspace_id, user_id) is None:
            raise _404_WORKSPACE

    async def _collection_out(self, col) -> CollectionOut:
        count = await self._repo.count_requests(col.id)
        return CollectionOut(
            id=col.id,
            workspace_id=col.workspace_id,
            name=col.name,
            description=col.description,
            request_count=count,
            created_at=col.created_at,
            updated_at=col.updated_at,
        )

    def _request_detail(self, req) -> ApiRequestDetail:
        return ApiRequestDetail(
            **ApiRequestOut.model_validate(req).model_dump(),
            headers=req.headers,
            body=req.body,
            auth_config=req.auth_config,
            assertions=[AssertionOut.model_validate(a) for a in req.assertions],
        )

    # ── Collections ───────────────────────────────────────────────────────────

    async def list_collections(
        self,
        user: User,
        workspace_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        name: str | None = None,
    ) -> Page[CollectionOut]:
        await self._assert_workspace_owned(workspace_id, user.id)
        rows, total = await self._repo.list_by_workspace(
            workspace_id, user.id,
            page=page, page_size=page_size, name=name,
        )
        items = [await self._collection_out(c) for c in rows]
        return Page.build(items, total, page, page_size)

    async def create_collection(
        self,
        user: User,
        workspace_id: str,
        body: CreateCollectionRequest,
    ) -> CollectionOut:
        await self._assert_workspace_owned(workspace_id, user.id)
        col = await self._repo.create(
            workspace_id=workspace_id,
            name=body.name,
            description=body.description,
        )
        return await self._collection_out(col)

    async def get_collection(self, user: User, collection_id: str) -> CollectionDetail:
        col = await self._repo.get_detail(collection_id, user.id)
        if col is None:
            raise _404_COLLECTION
        requests = [ApiRequestOut.model_validate(r) for r in col.requests]
        return CollectionDetail(
            id=col.id,
            workspace_id=col.workspace_id,
            name=col.name,
            description=col.description,
            request_count=len(requests),
            created_at=col.created_at,
            updated_at=col.updated_at,
            requests=requests,
        )

    async def update_collection(
        self,
        user: User,
        collection_id: str,
        body: UpdateCollectionRequest,
    ) -> CollectionOut:
        col = await self._repo.get_owned(collection_id, user.id)
        if col is None:
            raise _404_COLLECTION
        if body.name is not None:
            col.name = body.name
        if "description" in body.model_fields_set:
            col.description = body.description
        col.updated_at = datetime.now(timezone.utc)
        return await self._collection_out(col)

    async def delete_collection(self, user: User, collection_id: str) -> None:
        col = await self._repo.get_owned(collection_id, user.id)
        if col is None:
            raise _404_COLLECTION
        await self._repo.delete(col)

    # ── Requests ──────────────────────────────────────────────────────────────

    async def list_requests(self, user: User, collection_id: str) -> list[ApiRequestOut]:
        if await self._repo.get_owned(collection_id, user.id) is None:
            raise _404_COLLECTION
        rows = await self._req_repo.list_by_collection(collection_id, user.id)
        return [ApiRequestOut.model_validate(r) for r in rows]

    async def create_request(
        self,
        user: User,
        collection_id: str,
        body: CreateApiRequestBody,
    ) -> ApiRequestDetail:
        if await self._repo.get_owned(collection_id, user.id) is None:
            raise _404_COLLECTION

        order_index = body.order_index
        if "order_index" not in body.model_fields_set:
            order_index = (await self._req_repo.max_order_index(collection_id)) + 1

        req = await self._req_repo.create(
            collection_id=collection_id,
            name=body.name,
            method=body.method,
            url=body.url,
            headers=body.headers,
            body=body.body,
            body_type=body.body_type,
            auth_type=body.auth_type,
            auth_config=body.auth_config,
            timeout_ms=body.timeout_ms,
            order_index=order_index,
        )
        # Build response directly — new requests have no assertions yet so we
        # avoid touching the lazy-raise relationship.
        return ApiRequestDetail(
            **ApiRequestOut.model_validate(req).model_dump(),
            headers=req.headers,
            body=req.body,
            auth_config=req.auth_config,
            assertions=[],
        )

    async def get_request(self, user: User, request_id: str) -> ApiRequestDetail:
        req = await self._req_repo.get_detail(request_id, user.id)
        if req is None:
            raise _404_REQUEST
        return self._request_detail(req)

    async def update_request(
        self,
        user: User,
        request_id: str,
        body: UpdateApiRequestBody,
    ) -> ApiRequestDetail:
        req = await self._req_repo.get_detail(request_id, user.id)
        if req is None:
            raise _404_REQUEST

        for field in ("name", "method", "url", "headers", "body",
                      "body_type", "auth_type", "auth_config",
                      "timeout_ms", "order_index"):
            if field in body.model_fields_set:
                setattr(req, field, getattr(body, field))

        req.updated_at = datetime.now(timezone.utc)
        return self._request_detail(req)

    async def delete_request(self, user: User, request_id: str) -> None:
        req = await self._req_repo.get_owned(request_id, user.id)
        if req is None:
            raise _404_REQUEST
        await self._req_repo.delete(req)

    # ── Assertions ────────────────────────────────────────────────────────────

    async def _get_assertion_owned(self, assertion_id: str, user_id: str) -> Assertion:
        """Fetch an assertion and verify ownership through the request → workspace chain."""
        result = await self._db.execute(
            select(Assertion).where(Assertion.id == assertion_id)
        )
        assertion = result.scalar_one_or_none()
        if assertion is None:
            raise _404_ASSERTION
        # Walk up: if the owning request is inaccessible, treat assertion as not found.
        if await self._req_repo.get_owned(assertion.request_id, user_id) is None:
            raise _404_ASSERTION
        return assertion

    async def create_assertion(
        self,
        user: User,
        request_id: str,
        body: CreateAssertionRequest,
    ) -> AssertionOut:
        if await self._req_repo.get_owned(request_id, user.id) is None:
            raise _404_REQUEST

        assertion = Assertion(
            request_id=request_id,
            type=body.type,
            operator=body.operator,
            expected_value=body.expected_value,
            path=body.path,
        )
        self._db.add(assertion)
        await self._db.flush()
        return AssertionOut.model_validate(assertion)

    async def update_assertion(
        self,
        user: User,
        assertion_id: str,
        body: UpdateAssertionRequest,
    ) -> AssertionOut:
        assertion = await self._get_assertion_owned(assertion_id, user.id)
        for field in ("type", "operator", "expected_value", "path"):
            if field in body.model_fields_set:
                setattr(assertion, field, getattr(body, field))
        await self._db.flush()
        return AssertionOut.model_validate(assertion)

    async def delete_assertion(self, user: User, assertion_id: str) -> None:
        assertion = await self._get_assertion_owned(assertion_id, user.id)
        await self._db.delete(assertion)
        await self._db.flush()

    async def list_assertions(self, user: User, request_id: str) -> list[AssertionOut]:
        """Return all assertions for a request the user owns."""
        if await self._req_repo.get_owned(request_id, user.id) is None:
            raise _404_REQUEST
        rows = await self._db.execute(
            select(Assertion)
            .where(Assertion.request_id == request_id)
            .order_by(Assertion.created_at)
        )
        return [AssertionOut.model_validate(a) for a in rows.scalars().all()]

    async def get_assertion(self, user: User, assertion_id: str) -> AssertionOut:
        """Return a single assertion verified through ownership."""
        assertion = await self._get_assertion_owned(assertion_id, user.id)
        return AssertionOut.model_validate(assertion)

    async def preview_assertions(
        self,
        user: User,
        request_id: str,
        body: AssertionPreviewRequest,
    ) -> AssertionPreviewResponse:
        """
        Evaluate all assertions on a request against a provided sample response.

        This lets users iterate on their assertions locally without making a
        real HTTP request.  The sample response is never persisted.
        """
        from app.services.assertion_engine import HttpResult, evaluate_assertions

        if await self._req_repo.get_owned(request_id, user.id) is None:
            raise _404_REQUEST

        rows = await self._db.execute(
            select(Assertion)
            .where(Assertion.request_id == request_id)
            .order_by(Assertion.created_at)
        )
        assertions = list(rows.scalars().all())

        http_result = HttpResult(
            status_code=body.status_code,
            headers={k.lower(): v for k, v in body.headers.items()},
            body=body.body,
            response_time_ms=body.response_time_ms,
            error=None,
        )

        outcomes = evaluate_assertions(assertions, http_result)

        items = [
            AssertionPreviewResultItem(
                assertion_id=o.assertion_id or "",
                type=o.assertion_snapshot["type"],
                operator=o.assertion_snapshot["operator"],
                expected_value=o.assertion_snapshot["expected_value"],
                path=o.assertion_snapshot.get("path"),
                passed=o.passed,
                actual_value=o.actual_value,
                error_message=o.error_message,
            )
            for o in outcomes
        ]
        passed = sum(1 for i in items if i.passed)
        return AssertionPreviewResponse(
            total=len(items),
            passed=passed,
            failed=len(items) - passed,
            results=items,
        )
