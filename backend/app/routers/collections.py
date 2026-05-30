from fastapi import APIRouter, Query

from app.dependencies import CurrentUser, DBDep
from app.schemas.collection import (
    ApiRequestDetail,
    ApiRequestOut,
    AssertionOut,
    AssertionPreviewRequest,
    AssertionPreviewResponse,
    CollectionDetail,
    CollectionOut,
    CreateApiRequestBody,
    CreateAssertionRequest,
    CreateCollectionRequest,
    Page,
    UpdateApiRequestBody,
    UpdateAssertionRequest,
    UpdateCollectionRequest,
)
from app.services.collection_service import CollectionService

router = APIRouter()


# ── Collections ───────────────────────────────────────────────────────────────

@router.get(
    "/workspaces/{workspace_id}/collections",
    response_model=Page[CollectionOut],
    tags=["collections"],
)
async def list_collections(
    workspace_id: str,
    current_user: CurrentUser,
    db: DBDep,
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    name: str | None = Query(default=None, max_length=100, description="Filter by name (case-insensitive substring)"),
) -> Page[CollectionOut]:
    return await CollectionService(db).list_collections(
        current_user, workspace_id,
        page=page, page_size=page_size, name=name,
    )


@router.post(
    "/workspaces/{workspace_id}/collections",
    response_model=CollectionOut,
    status_code=201,
    tags=["collections"],
)
async def create_collection(
    workspace_id: str,
    body: CreateCollectionRequest,
    current_user: CurrentUser,
    db: DBDep,
) -> CollectionOut:
    return await CollectionService(db).create_collection(current_user, workspace_id, body)


@router.get("/collections/{collection_id}", response_model=CollectionDetail, tags=["collections"])
async def get_collection(
    collection_id: str,
    current_user: CurrentUser,
    db: DBDep,
) -> CollectionDetail:
    return await CollectionService(db).get_collection(current_user, collection_id)


@router.patch("/collections/{collection_id}", response_model=CollectionOut, tags=["collections"])
async def update_collection(
    collection_id: str,
    body: UpdateCollectionRequest,
    current_user: CurrentUser,
    db: DBDep,
) -> CollectionOut:
    return await CollectionService(db).update_collection(current_user, collection_id, body)


@router.delete("/collections/{collection_id}", status_code=204, tags=["collections"])
async def delete_collection(
    collection_id: str,
    current_user: CurrentUser,
    db: DBDep,
) -> None:
    await CollectionService(db).delete_collection(current_user, collection_id)


# ── API Requests ──────────────────────────────────────────────────────────────

@router.get(
    "/collections/{collection_id}/requests",
    response_model=list[ApiRequestOut],
    tags=["requests"],
)
async def list_requests(
    collection_id: str,
    current_user: CurrentUser,
    db: DBDep,
) -> list[ApiRequestOut]:
    return await CollectionService(db).list_requests(current_user, collection_id)


@router.post(
    "/collections/{collection_id}/requests",
    response_model=ApiRequestDetail,
    status_code=201,
    tags=["requests"],
)
async def create_request(
    collection_id: str,
    body: CreateApiRequestBody,
    current_user: CurrentUser,
    db: DBDep,
) -> ApiRequestDetail:
    return await CollectionService(db).create_request(current_user, collection_id, body)


@router.get("/requests/{request_id}", response_model=ApiRequestDetail, tags=["requests"])
async def get_request(
    request_id: str,
    current_user: CurrentUser,
    db: DBDep,
) -> ApiRequestDetail:
    return await CollectionService(db).get_request(current_user, request_id)


@router.patch("/requests/{request_id}", response_model=ApiRequestDetail, tags=["requests"])
async def update_request(
    request_id: str,
    body: UpdateApiRequestBody,
    current_user: CurrentUser,
    db: DBDep,
) -> ApiRequestDetail:
    return await CollectionService(db).update_request(current_user, request_id, body)


@router.delete("/requests/{request_id}", status_code=204, tags=["requests"])
async def delete_request(
    request_id: str,
    current_user: CurrentUser,
    db: DBDep,
) -> None:
    await CollectionService(db).delete_request(current_user, request_id)


# ── Assertions ────────────────────────────────────────────────────────────────

@router.get(
    "/requests/{request_id}/assertions",
    response_model=list[AssertionOut],
    tags=["assertions"],
)
async def list_assertions(
    request_id: str,
    current_user: CurrentUser,
    db: DBDep,
) -> list[AssertionOut]:
    return await CollectionService(db).list_assertions(current_user, request_id)


@router.get(
    "/assertions/{assertion_id}",
    response_model=AssertionOut,
    tags=["assertions"],
)
async def get_assertion(
    assertion_id: str,
    current_user: CurrentUser,
    db: DBDep,
) -> AssertionOut:
    return await CollectionService(db).get_assertion(current_user, assertion_id)


@router.post(
    "/requests/{request_id}/assertions/preview",
    response_model=AssertionPreviewResponse,
    tags=["assertions"],
    summary="Preview assertions against a sample response without executing the request",
)
async def preview_assertions(
    request_id: str,
    body: AssertionPreviewRequest,
    current_user: CurrentUser,
    db: DBDep,
) -> AssertionPreviewResponse:
    return await CollectionService(db).preview_assertions(current_user, request_id, body)


@router.post(
    "/requests/{request_id}/assertions",
    response_model=AssertionOut,
    status_code=201,
    tags=["assertions"],
)
async def create_assertion(
    request_id: str,
    body: CreateAssertionRequest,
    current_user: CurrentUser,
    db: DBDep,
) -> AssertionOut:
    return await CollectionService(db).create_assertion(current_user, request_id, body)


@router.patch("/assertions/{assertion_id}", response_model=AssertionOut, tags=["assertions"])
async def update_assertion(
    assertion_id: str,
    body: UpdateAssertionRequest,
    current_user: CurrentUser,
    db: DBDep,
) -> AssertionOut:
    return await CollectionService(db).update_assertion(current_user, assertion_id, body)


@router.delete("/assertions/{assertion_id}", status_code=204, tags=["assertions"])
async def delete_assertion(
    assertion_id: str,
    current_user: CurrentUser,
    db: DBDep,
) -> None:
    await CollectionService(db).delete_assertion(current_user, assertion_id)
