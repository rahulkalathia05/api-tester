"""
JSONPath evaluation used by the assertion engine.

Wraps jsonpath-ng so the rest of the codebase has a single import point
and a consistent return type.
"""
from __future__ import annotations

import json
from typing import Any

from jsonpath_ng import parse as _parse
from jsonpath_ng.exceptions import JsonPathParserError


def evaluate(path: str, data: str | dict | list) -> list[Any]:
    """
    Evaluate a JSONPath expression against JSON data.

    Args:
        path: JSONPath expression, e.g. "$.data[0].id"
        data: raw JSON string or already-parsed object

    Returns:
        List of matching values (empty if no match).

    Raises:
        ValueError: if the path expression is invalid.
        json.JSONDecodeError: if data is a string that is not valid JSON.
    """
    if isinstance(data, str):
        data = json.loads(data)

    try:
        expr = _parse(path)
    except JsonPathParserError as exc:
        raise ValueError(f"Invalid JSONPath expression {path!r}: {exc}") from exc

    return [match.value for match in expr.find(data)]


def first(path: str, data: str | dict | list, default: Any = None) -> Any:
    """Return the first match or default."""
    matches = evaluate(path, data)
    return matches[0] if matches else default
