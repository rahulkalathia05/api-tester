"""
Response diff service — pure functions, no I/O.

DiffService.compare() takes two TestResult ORM objects and returns a
ResultDiff with field-level changes across five sections:

  status   — HTTP status code change
  timing   — response time change and direction
  headers  — added / removed / changed response headers
  body     — deep recursive JSON diff with JSONPath addresses
  schema   — fields that changed type or appeared / disappeared

All sections are produced from the stored snapshots so results remain
accurate even if the original request was later edited.

Body diff algorithm
───────────────────
  dict  → compare key by key; recurse into shared keys
  list  → compare element by element (by index)
  leaf  → changed if values differ, even if types agree

  Depth is capped at MAX_DEPTH to avoid blowing the output on deeply
  nested payloads.  Large arrays are capped at MAX_ARRAY_ITEMS.

Schema diff
───────────
  Extracts {path → python_type_name} from each parsed body, then
  reports keys that appeared, disappeared, or changed type.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Literal

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.test_result import TestResult
from app.models.test_run import TestRun
from app.models.workspace import Workspace

logger = logging.getLogger(__name__)

MAX_DEPTH       = 8    # max recursion depth for body diff
MAX_ARRAY_ITEMS = 20   # max array elements compared


# ── Schemas ───────────────────────────────────────────────────────────────────

ChangeType = Literal["added", "removed", "changed", "unchanged"]


class FieldChange(BaseModel):
    path: str
    from_value: str | None     # None when field was added
    to_value: str | None       # None when field was removed
    change_type: ChangeType


class SectionDiff(BaseModel):
    section: str               # status | timing | headers | body | schema
    label: str                 # human-readable section name
    summary: str               # one-line summary shown in the header
    changes: list[FieldChange]
    has_changes: bool


class ResultSnapshot(BaseModel):
    result_id: str
    executed_at: datetime
    run_status: str
    status_code: int | None
    response_time_ms: int | None
    request_name: str
    request_method: str
    request_url: str


class ResultDiff(BaseModel):
    a: ResultSnapshot
    b: ResultSnapshot
    sections: list[SectionDiff]
    total_changes: int
    is_identical: bool


# ── Pure diff helpers ─────────────────────────────────────────────────────────

def _repr(v: Any, *, max_len: int = 120) -> str:
    s = json.dumps(v, default=str) if not isinstance(v, str) else v
    return s if len(s) <= max_len else s[:max_len] + "…"


def _json_diff(
    a: Any,
    b: Any,
    path: str = "$",
    depth: int = 0,
) -> list[FieldChange]:
    if depth > MAX_DEPTH:
        if a != b:
            return [FieldChange(path=path, from_value=_repr(a),
                                to_value=_repr(b), change_type="changed")]
        return []

    # Both dicts
    if isinstance(a, dict) and isinstance(b, dict):
        changes: list[FieldChange] = []
        for key in sorted(set(a) | set(b)):
            child = f"{path}.{key}"
            if key not in a:
                changes.append(FieldChange(path=child, from_value=None,
                                           to_value=_repr(b[key]), change_type="added"))
            elif key not in b:
                changes.append(FieldChange(path=child, from_value=_repr(a[key]),
                                           to_value=None, change_type="removed"))
            else:
                changes.extend(_json_diff(a[key], b[key], child, depth + 1))
        return changes

    # Both lists
    if isinstance(a, list) and isinstance(b, list):
        changes = []
        limit = max(len(a), len(b))
        if limit > MAX_ARRAY_ITEMS:
            limit = MAX_ARRAY_ITEMS
            logger.debug("Array at %s truncated to %d items for diff", path, limit)
        for i in range(limit):
            child = f"{path}[{i}]"
            if i >= len(a):
                changes.append(FieldChange(path=child, from_value=None,
                                           to_value=_repr(b[i]), change_type="added"))
            elif i >= len(b):
                changes.append(FieldChange(path=child, from_value=_repr(a[i]),
                                           to_value=None, change_type="removed"))
            else:
                changes.extend(_json_diff(a[i], b[i], child, depth + 1))
        return changes

    # Type changed or primitive changed
    if a != b:
        return [FieldChange(path=path, from_value=_repr(a),
                            to_value=_repr(b), change_type="changed")]
    return []


def _parse_body(raw: str | None) -> dict | list | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


def _extract_schema(obj: Any, path: str = "$", depth: int = 0) -> dict[str, str]:
    """Return {path → type_name} for every reachable node."""
    if depth > MAX_DEPTH:
        return {path: type(obj).__name__}

    if isinstance(obj, dict):
        result: dict[str, str] = {}
        for k, v in obj.items():
            child = f"{path}.{k}"
            result[child] = type(v).__name__
            result.update(_extract_schema(v, child, depth + 1))
        return result

    if isinstance(obj, list):
        result = {f"{path}[]": "array"}
        for i, item in enumerate(obj[:MAX_ARRAY_ITEMS]):
            result.update(_extract_schema(item, f"{path}[{i}]", depth + 1))
        return result

    return {path: type(obj).__name__}


# ── Section builders ──────────────────────────────────────────────────────────

def _diff_status(a: TestResult, b: TestResult) -> SectionDiff:
    sa, sb = a.response_status, b.response_status
    if sa == sb:
        summary = f"Status unchanged ({sa})"
        changes = []
    else:
        summary = f"Status changed {sa} → {sb}"
        changes = [FieldChange(path="$.status_code", from_value=str(sa),
                               to_value=str(sb), change_type="changed")]
    return SectionDiff(section="status", label="Status Code",
                       summary=summary, changes=changes,
                       has_changes=bool(changes))


def _diff_timing(a: TestResult, b: TestResult) -> SectionDiff:
    ta, tb = a.response_time_ms, b.response_time_ms
    if ta is None and tb is None:
        return SectionDiff(section="timing", label="Response Time",
                           summary="No timing data", changes=[], has_changes=False)

    if ta == tb:
        summary = f"Timing unchanged ({ta}ms)"
        changes = []
    else:
        delta = (tb or 0) - (ta or 0)
        direction = "slower" if delta > 0 else "faster"
        summary = f"{abs(delta)}ms {direction} ({ta}ms → {tb}ms)"
        changes = [FieldChange(path="$.response_time_ms",
                               from_value=f"{ta}ms" if ta is not None else "—",
                               to_value=f"{tb}ms" if tb is not None else "—",
                               change_type="changed")]
    return SectionDiff(section="timing", label="Response Time",
                       summary=summary, changes=changes,
                       has_changes=bool(changes))


def _diff_headers(a: TestResult, b: TestResult) -> SectionDiff:
    ha = {k.lower(): v for k, v in (a.response_headers or {}).items()}
    hb = {k.lower(): v for k, v in (b.response_headers or {}).items()}

    changes: list[FieldChange] = []
    for key in sorted(set(ha) | set(hb)):
        path = f"$.headers.{key}"
        if key not in ha:
            changes.append(FieldChange(path=path, from_value=None,
                                       to_value=hb[key], change_type="added"))
        elif key not in hb:
            changes.append(FieldChange(path=path, from_value=ha[key],
                                       to_value=None, change_type="removed"))
        elif ha[key] != hb[key]:
            changes.append(FieldChange(path=path, from_value=ha[key],
                                       to_value=hb[key], change_type="changed"))

    n = len(changes)
    summary = "Headers identical" if not changes else (
        f"{n} header change{'s' if n > 1 else ''}"
    )
    return SectionDiff(section="headers", label="Response Headers",
                       summary=summary, changes=changes,
                       has_changes=bool(changes))


def _diff_body(a: TestResult, b: TestResult) -> SectionDiff:
    pa = _parse_body(a.response_body)
    pb = _parse_body(b.response_body)

    # Both non-JSON (or both empty)
    if pa is None and pb is None:
        same = (a.response_body or "") == (b.response_body or "")
        if same:
            return SectionDiff(section="body", label="Response Body",
                               summary="Body identical", changes=[], has_changes=False)
        return SectionDiff(section="body", label="Response Body",
                           summary="Body changed (non-JSON)",
                           changes=[FieldChange(path="$.body",
                                                from_value=_repr(a.response_body or ""),
                                                to_value=_repr(b.response_body or ""),
                                                change_type="changed")],
                           has_changes=True)

    # One is JSON, one isn't
    if (pa is None) != (pb is None):
        return SectionDiff(section="body", label="Response Body",
                           summary="Body format changed (JSON ↔ non-JSON)",
                           changes=[FieldChange(path="$.body",
                                                from_value=_repr(a.response_body or ""),
                                                to_value=_repr(b.response_body or ""),
                                                change_type="changed")],
                           has_changes=True)

    changes = _json_diff(pa, pb)
    n = len(changes)
    summary = "Body identical" if not changes else f"{n} field change{'s' if n > 1 else ''}"
    return SectionDiff(section="body", label="Response Body",
                       summary=summary, changes=changes,
                       has_changes=bool(changes))


def _diff_schema(a: TestResult, b: TestResult) -> SectionDiff:
    pa = _parse_body(a.response_body)
    pb = _parse_body(b.response_body)

    if pa is None and pb is None:
        return SectionDiff(section="schema", label="Schema",
                           summary="No JSON body to compare",
                           changes=[], has_changes=False)

    sa = _extract_schema(pa) if pa is not None else {}
    sb = _extract_schema(pb) if pb is not None else {}

    changes: list[FieldChange] = []
    for path in sorted(set(sa) | set(sb)):
        if path not in sa:
            changes.append(FieldChange(path=path, from_value=None,
                                       to_value=sb[path], change_type="added"))
        elif path not in sb:
            changes.append(FieldChange(path=path, from_value=sa[path],
                                       to_value=None, change_type="removed"))
        elif sa[path] != sb[path]:
            changes.append(FieldChange(path=path, from_value=sa[path],
                                       to_value=sb[path], change_type="changed"))

    n = len(changes)
    summary = "Schema identical" if not changes else (
        f"{n} schema change{'s' if n > 1 else ''}"
    )
    return SectionDiff(section="schema", label="Schema",
                       summary=summary, changes=changes,
                       has_changes=bool(changes))


# ── Service class ─────────────────────────────────────────────────────────────

class DiffService:

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def _load_owned(self, result_id: str, user_id: str) -> TestResult:
        row = await self._db.execute(
            select(TestResult)
            .join(TestRun,   TestRun.id   == TestResult.test_run_id)
            .join(Workspace, Workspace.id == TestRun.workspace_id)
            .where(TestResult.id == result_id, Workspace.user_id == user_id)
        )
        result = row.scalar_one_or_none()
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail=f"Result {result_id!r} not found")
        return result

    async def compare(
        self,
        result_id_a: str,
        result_id_b: str,
        user_id: str,
    ) -> ResultDiff:
        if result_id_a == result_id_b:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="Cannot diff a result against itself")

        a, b = await self._load_owned(result_id_a, user_id), \
               await self._load_owned(result_id_b, user_id)

        def _snap(r: TestResult) -> ResultSnapshot:
            snap = r.request_snapshot or {}
            return ResultSnapshot(
                result_id=r.id,
                executed_at=r.executed_at,
                run_status=r.status,
                status_code=r.response_status,
                response_time_ms=r.response_time_ms,
                request_name=snap.get("name", "—"),
                request_method=snap.get("method", "?"),
                request_url=snap.get("url", "—"),
            )

        sections = [
            _diff_status(a, b),
            _diff_timing(a, b),
            _diff_headers(a, b),
            _diff_body(a, b),
            _diff_schema(a, b),
        ]

        total = sum(len(s.changes) for s in sections)
        return ResultDiff(
            a=_snap(a),
            b=_snap(b),
            sections=sections,
            total_changes=total,
            is_identical=(total == 0),
        )

    async def list_request_history(
        self,
        request_id: str,
        user_id: str,
        limit: int = 10,
    ) -> list[TestResult]:
        """
        Return recent TestResult rows for a given request_id.
        Used by the frontend to let users pick which execution to diff against.
        """
        rows = await self._db.execute(
            select(TestResult)
            .join(TestRun,   TestRun.id   == TestResult.test_run_id)
            .join(Workspace, Workspace.id == TestRun.workspace_id)
            .where(
                TestResult.request_id == request_id,
                Workspace.user_id == user_id,
            )
            .order_by(TestResult.executed_at.desc())
            .limit(limit)
        )
        return list(rows.scalars().all())
