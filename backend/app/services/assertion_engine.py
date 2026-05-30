"""
Assertion engine — pure functions, no I/O.

evaluate_assertions() takes a list of Assertion ORM objects (or dicts with the
same keys) and a completed HttpResult, and returns one AssertionOutcome per
assertion.  It never touches the database or raises HTTP exceptions.

Assertion types:
  status_code    — compare HTTP status code (integer)
  response_time  — compare round-trip time in milliseconds (integer)
  json_path      — extract via JSONPath from body, then compare
  header         — compare a response header value (case-insensitive key)
  body_contains  — check raw body string membership

Operators:
  eq / ne              — equality  (string or numeric depending on context)
  gt / lt / gte / lte  — numeric ordering (both sides cast to float)
  contains             — expected in actual (substring or list element)
  not_contains         — expected not in actual
  exists               — actual value is not None / non-empty
  matches              — re.search(expected, str(actual))
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from app.utils.jsonpath import evaluate as jsonpath_evaluate


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class HttpResult:
    """Captured output from a single HTTP execution."""
    status_code: int | None
    headers: dict[str, str]
    body: str | None
    response_time_ms: int
    error: str | None          # non-None when the request could not be sent


@dataclass
class AssertionOutcome:
    """Result of evaluating one assertion against an HttpResult."""
    assertion_id: str | None
    assertion_snapshot: dict   # copy of {type, operator, expected_value, path}
    passed: bool
    actual_value: str | None
    error_message: str | None


class AssertionLike(Protocol):
    """Structural type — works with ORM Assertion and plain dicts."""
    id: str
    type: str
    operator: str
    expected_value: str
    path: str | None


# ── Public entry point ────────────────────────────────────────────────────────

def evaluate_assertions(
    assertions: list[AssertionLike],
    result: HttpResult,
) -> list[AssertionOutcome]:
    return [_evaluate_one(a, result) for a in assertions]


# ── Internal ──────────────────────────────────────────────────────────────────

def _evaluate_one(assertion: AssertionLike, result: HttpResult) -> AssertionOutcome:
    snapshot = {
        "type": assertion.type,
        "operator": assertion.operator,
        "expected_value": assertion.expected_value,
        "path": assertion.path,
    }

    if result.error:
        return AssertionOutcome(
            assertion_id=assertion.id,
            assertion_snapshot=snapshot,
            passed=False,
            actual_value=None,
            error_message=f"Request failed: {result.error}",
        )

    try:
        actual = _extract(assertion, result)
        passed = _compare(actual, assertion.operator, assertion.expected_value)
        return AssertionOutcome(
            assertion_id=assertion.id,
            assertion_snapshot=snapshot,
            passed=passed,
            actual_value=_to_str(actual),
            error_message=None,
        )
    except Exception as exc:
        return AssertionOutcome(
            assertion_id=assertion.id,
            assertion_snapshot=snapshot,
            passed=False,
            actual_value=None,
            error_message=str(exc),
        )


def _extract(assertion: AssertionLike, result: HttpResult) -> Any:
    """Return the actual value from the response for this assertion type."""
    t = assertion.type

    if t == "status_code":
        return result.status_code

    if t == "response_time":
        return result.response_time_ms

    if t == "json_path":
        if not result.body:
            raise ValueError("Response body is empty — cannot evaluate JSONPath")
        path = assertion.path
        if not path:
            raise ValueError("Assertion type 'json_path' requires a path")
        matches = jsonpath_evaluate(path, result.body)
        if assertion.operator == "exists":
            return matches  # compare the list, not the first element
        return matches[0] if matches else None

    if t == "header":
        key = (assertion.path or "").lower()
        # httpx normalises header names to lowercase
        return result.headers.get(key) or result.headers.get(assertion.path or "")

    if t == "body_contains":
        return result.body or ""

    raise ValueError(f"Unknown assertion type: {t!r}")


def _compare(actual: Any, operator: str, expected: str) -> bool:
    if operator == "exists":
        if isinstance(actual, list):
            return len(actual) > 0
        return actual is not None and actual != ""

    if operator in ("gt", "lt", "gte", "lte"):
        return _numeric_compare(actual, operator, expected)

    if operator in ("eq", "ne"):
        # Try numeric comparison when both sides look like numbers.
        try:
            a = float(str(actual))
            e = float(expected)
            if operator == "eq":
                return a == e
            return a != e
        except (TypeError, ValueError):
            if operator == "eq":
                return str(actual) == expected
            return str(actual) != expected

    if operator == "contains":
        if isinstance(actual, list):
            return expected in [str(v) for v in actual]
        return expected in str(actual)

    if operator == "not_contains":
        if isinstance(actual, list):
            return expected not in [str(v) for v in actual]
        return expected not in str(actual)

    if operator == "matches":
        return bool(re.search(expected, str(actual)))

    raise ValueError(f"Unknown operator: {operator!r}")


def _numeric_compare(actual: Any, operator: str, expected: str) -> bool:
    try:
        a = float(str(actual))
        e = float(expected)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Operator {operator!r} requires numeric values; "
            f"got actual={actual!r}, expected={expected!r}"
        ) from exc

    return {
        "gt":  a > e,
        "lt":  a < e,
        "gte": a >= e,
        "lte": a <= e,
    }[operator]


def _to_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return str(value[0]) if value else None
    return str(value)
