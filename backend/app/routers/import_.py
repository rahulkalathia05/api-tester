"""
Import endpoints.

POST /workspaces/{workspace_id}/import/postman
  – Accepts a Postman Collection JSON file (multipart) or JSON body.
  – Parses, creates the collection + all requests in one transaction.
  – Returns a detailed ImportResult with per-request error reporting.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUser, DBDep
from app.models.api_request import ApiRequest
from app.models.collection import Collection
from app.repositories.workspace_repo import WorkspaceRepository
from app.services.postman_parser import parse_collection, ParsedCollection

router = APIRouter(tags=["import"])

_MAX_FILE_BYTES = 10 * 1024 * 1024   # 10 MB


# ── Import result schema (inline — no separate file needed) ───────────────────

def _build_result(
    collection_id: str,
    collection_name: str,
    parsed: ParsedCollection,
    imported: int,
) -> dict:
    return {
        "collection_id":   collection_id,
        "collection_name": collection_name,
        "total_requests":  imported,
        "skipped":         len(parsed.errors),
        "errors":          [{"request": e.request_name, "reason": e.reason} for e in parsed.errors],
        "warnings":        parsed.warnings,
    }


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post(
    "/workspaces/{workspace_id}/import/postman",
    summary="Import a Postman Collection v2.0/v2.1",
    status_code=201,
)
async def import_postman(
    workspace_id: str,
    file: UploadFile,
    current_user: CurrentUser,
    db: DBDep,
) -> JSONResponse:
    """
    Upload a Postman Collection JSON file and create the collection
    with all its requests in the given workspace.

    Accepts: multipart/form-data with a single file field.
    Returns: ImportResult with collection_id, counts, and per-request errors.
    """
    # ── Ownership ─────────────────────────────────────────────────────────────
    ws_repo = WorkspaceRepository(db)
    ws = await ws_repo.get_owned(workspace_id, current_user.id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # ── Read + validate file ──────────────────────────────────────────────────
    if not file.filename or not file.filename.endswith(".json"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File must be a .json file",
        )

    raw = await file.read()
    if len(raw) > _MAX_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the 10 MB import limit ({len(raw) // 1024} KB uploaded)",
        )

    # ── Parse JSON ────────────────────────────────────────────────────────────
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid JSON: {exc}",
        )

    # ── Parse Postman format ──────────────────────────────────────────────────
    try:
        parsed = parse_collection(data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # ── Persist: collection + requests ────────────────────────────────────────
    collection = Collection(
        workspace_id=workspace_id,
        name=parsed.name,
        description=parsed.description,
    )
    db.add(collection)
    await db.flush()   # get collection.id

    imported = 0
    for req in parsed.requests:
        ar = ApiRequest(
            collection_id=collection.id,
            name=req.name,
            method=req.method,
            url=req.url,
            headers=req.headers,
            body=req.body,
            body_type=req.body_type,
            auth_type=req.auth_type,
            auth_config=req.auth_config,
            timeout_ms=30_000,
            order_index=req.order_index,
        )
        db.add(ar)
        imported += 1

    # Commit via the get_db dependency (auto-commits on success)
    await db.flush()

    return JSONResponse(
        status_code=201,
        content=_build_result(collection.id, collection.name, parsed, imported),
    )
