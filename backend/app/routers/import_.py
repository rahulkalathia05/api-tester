"""
Import endpoints.

POST /workspaces/{workspace_id}/import/postman
  – Accepts a Postman Collection JSON file (multipart).
  – Supports v2.0 and v2.1 format.

POST /workspaces/{workspace_id}/import/openapi
  – Accepts an OpenAPI 3.x or Swagger 2.0 JSON file (multipart).
  – Also accepts .yaml / .yml files when PyYAML is installed.

Both endpoints return ImportResult with per-request error reporting.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse

from app.dependencies import CurrentUser, DBDep
from app.models.api_request import ApiRequest
from app.models.collection import Collection
from app.repositories.workspace_repo import WorkspaceRepository
from app.services.openapi_parser import detect_format, parse_openapi
from app.services.postman_parser import parse_collection, ParsedCollection

router = APIRouter(tags=["import"])

_MAX_FILE_BYTES = 10 * 1024 * 1024   # 10 MB


# ── Shared helpers ────────────────────────────────────────────────────────────

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


async def _read_and_parse_json(file: UploadFile) -> dict:
    """Read the upload, validate size, parse JSON (or YAML if available)."""
    raw = await file.read()
    if len(raw) > _MAX_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the 10 MB limit ({len(raw) // 1024} KB uploaded)",
        )

    fname = file.filename or ""
    if fname.endswith((".yaml", ".yml")):
        try:
            import yaml
            return yaml.safe_load(raw)
        except ImportError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="YAML import requires PyYAML. Upload a .json file instead, "
                       "or convert your spec with: python -c \"import yaml,json,sys; "
                       "print(json.dumps(yaml.safe_load(sys.stdin)))\"",
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Invalid YAML: {exc}")

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid JSON: {exc}")


async def _persist_parsed(
    db,
    workspace_id: str,
    parsed: ParsedCollection,
) -> str:
    """Create Collection + ApiRequest rows; return collection.id."""
    collection = Collection(
        workspace_id=workspace_id,
        name=parsed.name,
        description=parsed.description,
    )
    db.add(collection)
    await db.flush()

    for req in parsed.requests:
        db.add(ApiRequest(
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
        ))

    await db.flush()
    return collection.id


# ── Postman endpoint ──────────────────────────────────────────────────────────

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
    ws = await WorkspaceRepository(db).get_owned(workspace_id, current_user.id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")

    if not (file.filename or "").endswith(".json"):
        raise HTTPException(status_code=422, detail="File must be a .json file")

    data = await _read_and_parse_json(file)

    try:
        parsed = parse_collection(data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    col_id = await _persist_parsed(db, workspace_id, parsed)
    return JSONResponse(
        status_code=201,
        content=_build_result(col_id, parsed.name, parsed, len(parsed.requests)),
    )


# ── OpenAPI endpoint ──────────────────────────────────────────────────────────

@router.post(
    "/workspaces/{workspace_id}/import/openapi",
    summary="Import an OpenAPI 3.x or Swagger 2.0 spec",
    status_code=201,
    description=(
        "Accepts JSON (.json) or YAML (.yaml/.yml — requires PyYAML) files. "
        "Parses all paths/operations, generates example request bodies from "
        "JSON Schema, converts path/server variables to {{env.VAR}}, and "
        "groups requests by OpenAPI tags."
    ),
)
async def import_openapi(
    workspace_id: str,
    file: UploadFile,
    current_user: CurrentUser,
    db: DBDep,
) -> JSONResponse:
    ws = await WorkspaceRepository(db).get_owned(workspace_id, current_user.id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")

    fname = file.filename or ""
    allowed = (".json", ".yaml", ".yml")
    if not any(fname.endswith(ext) for ext in allowed):
        raise HTTPException(
            status_code=422,
            detail="File must be a .json, .yaml, or .yml file",
        )

    data = await _read_and_parse_json(file)

    # Validate it looks like OpenAPI / Swagger
    fmt = detect_format(data)
    if fmt is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "File does not appear to be an OpenAPI 3.x or Swagger 2.0 spec. "
                "Make sure it has a top-level 'openapi' or 'swagger' key."
            ),
        )

    try:
        parsed = parse_openapi(data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    col_id = await _persist_parsed(db, workspace_id, parsed)
    return JSONResponse(
        status_code=201,
        content=_build_result(col_id, parsed.name, parsed, len(parsed.requests)),
    )
