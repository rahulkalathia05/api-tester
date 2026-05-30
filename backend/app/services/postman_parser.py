"""
Postman Collection parser — supports v2.0 and v2.1 formats.

Entry point:  parse_collection(data) → ParsedCollection
              All public functions are pure (no I/O, no DB calls).

Format reference:
  https://schema.getpostman.com/json/collection/v2.1.0/collection.json
  https://schema.getpostman.com/json/collection/v2.0.0/collection.json

Parsing strategy:
  1. Validate the top-level schema identifier.
  2. Extract collection-level metadata and optional auth.
  3. Recursively walk `item` arrays.
     – Items with a nested `item` array are folders → prefix request names.
     – Items with a `request` key are actual requests.
  4. For each request item extract: method, URL, headers, body, auth.
  5. Replace Postman variable syntax  {{VAR}}  with  {{env.VAR}}.

Error handling:
  Every request is parsed independently.  A parse failure for one request
  is recorded as an error and skipped; the others still import.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from typing import Any

# ── Constants ─────────────────────────────────────────────────────────────────

SUPPORTED_SCHEMAS = {
    "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    "https://schema.getpostman.com/json/collection/v2.0.0/collection.json",
    # Some exports omit the full URL — accept short identifiers too
    "v2.1", "v2.0",
}

VALID_METHODS  = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
VALID_BODY_TYPES = {"json", "form", "raw", "none"}


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class ParsedRequest:
    name: str
    method: str
    url: str
    headers: dict[str, str]
    body: str | None
    body_type: str
    auth_type: str
    auth_config: dict[str, str]
    order_index: int


@dataclass
class ParseError:
    request_name: str
    reason: str


@dataclass
class ParsedCollection:
    name: str
    description: str | None
    requests: list[ParsedRequest]
    errors: list[ParseError]
    warnings: list[str]


# ── Variable substitution ─────────────────────────────────────────────────────

_VAR_RE = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")


def _to_env_var(text: str) -> str:
    """Replace Postman {{VAR}} with our {{env.VAR}} syntax."""
    return _VAR_RE.sub(lambda m: f"{{{{env.{m.group(1)}}}}}", text)


# ── URL parser ────────────────────────────────────────────────────────────────

def _parse_url(url: Any) -> str:
    if isinstance(url, str):
        return _to_env_var(url)

    if not isinstance(url, dict):
        return ""

    raw = url.get("raw", "")
    if raw:
        return _to_env_var(raw)

    # Reconstruct from parts
    protocol = url.get("protocol", "https")
    host     = url.get("host", [])
    if isinstance(host, list):
        host = ".".join(host)
    path = url.get("path", [])
    if isinstance(path, list):
        # Filter out empty path segments
        path = "/".join(p for p in path if p)
    query = url.get("query", [])
    qs    = ""
    if query:
        params = [f"{q['key']}={q.get('value', '')}" for q in query
                  if isinstance(q, dict) and not q.get("disabled")]
        qs = "?" + "&".join(params) if params else ""

    reconstructed = f"{protocol}://{host}/{path}{qs}".rstrip("/")
    return _to_env_var(reconstructed)


# ── Header parser ─────────────────────────────────────────────────────────────

def _parse_headers(headers: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    if not isinstance(headers, list):
        return result
    for h in headers:
        if not isinstance(h, dict):
            continue
        if h.get("disabled"):
            continue
        key = h.get("key", "").strip()
        val = h.get("value", "").strip()
        if key:
            result[key] = _to_env_var(val)
    return result


# ── Body parser ───────────────────────────────────────────────────────────────

def _parse_body(body: Any) -> tuple[str | None, str]:
    """Return (body_text, body_type)."""
    if not body or not isinstance(body, dict):
        return None, "none"

    mode = body.get("mode", "none")

    if mode == "raw":
        raw  = body.get("raw", "")
        lang = (body.get("options", {}) or {}).get("raw", {}).get("language", "")
        body_type = "json" if lang.lower() == "json" else "raw"
        return _to_env_var(raw) if raw else None, body_type

    if mode == "urlencoded":
        pairs = body.get("urlencoded", []) or []
        text  = "&".join(
            f"{_to_env_var(p.get('key', ''))}={_to_env_var(p.get('value', ''))}"
            for p in pairs if isinstance(p, dict) and not p.get("disabled")
        )
        return text or None, "form"

    if mode == "formdata":
        return None, "form"

    if mode == "graphql":
        q = body.get("graphql", {}) or {}
        payload = {"query": q.get("query", ""), "variables": q.get("variables", "{}")}
        import json
        return json.dumps(payload, indent=2), "json"

    return None, "none"


# ── Auth parser ───────────────────────────────────────────────────────────────

def _parse_auth(auth: Any) -> tuple[str, dict[str, str]]:
    """Return (auth_type, auth_config)."""
    if not auth or not isinstance(auth, dict):
        return "none", {}

    auth_type = auth.get("type", "none")

    if auth_type == "bearer":
        cfg: dict[str, str] = {}
        for item in (auth.get("bearer") or []):
            if isinstance(item, dict) and item.get("key") == "token":
                cfg["token"] = _to_env_var(item.get("value", ""))
        return "bearer", cfg

    if auth_type == "basic":
        cfg = {}
        for item in (auth.get("basic") or []):
            if not isinstance(item, dict):
                continue
            k, v = item.get("key"), _to_env_var(item.get("value", ""))
            if k == "username": cfg["username"] = v
            if k == "password": cfg["password"] = v
        return "basic", cfg

    if auth_type in ("apikey", "api_key"):
        cfg = {}
        for item in (auth.get("apikey") or auth.get("api_key") or []):
            if not isinstance(item, dict):
                continue
            k, v = item.get("key"), _to_env_var(item.get("value", ""))
            if k == "key":   cfg["header"] = v
            if k == "value": cfg["value"]  = v
        return "api_key", cfg

    return "none", {}


# ── Recursive item walker ─────────────────────────────────────────────────────

def _walk_items(
    items: list[Any],
    parent_name: str,
    order_start: int,
    collection_auth: tuple[str, dict],
) -> tuple[list[ParsedRequest], list[ParseError]]:
    """
    Recursively walk Postman item tree.

    Folders (items with nested `item`) are flattened; the folder name is
    prepended to request names with ' > ' separator.
    """
    requests: list[ParsedRequest] = []
    errors:   list[ParseError]    = []
    order = order_start

    for item in items:
        if not isinstance(item, dict):
            continue

        name = item.get("name", "Unnamed")
        full_name = f"{parent_name} > {name}" if parent_name else name

        # Folder — recurse
        if "item" in item and isinstance(item["item"], list):
            sub_reqs, sub_errs = _walk_items(
                item["item"], full_name, order, collection_auth
            )
            requests.extend(sub_reqs)
            errors.extend(sub_errs)
            order += len(sub_reqs)
            continue

        # Request item
        req_data = item.get("request")
        if not req_data:
            continue

        try:
            if isinstance(req_data, str):
                # Simplified format where request is just the URL string
                method = "GET"
                url    = _to_env_var(req_data)
                headers: dict[str, str] = {}
                body, body_type = None, "none"
                auth_type, auth_config = "none", {}
            else:
                method   = req_data.get("method", "GET").upper()
                if method not in VALID_METHODS:
                    method = "GET"
                url      = _parse_url(req_data.get("url", ""))
                headers  = _parse_headers(req_data.get("header", []))
                body, body_type = _parse_body(req_data.get("body"))

                # Auth: request-level overrides collection-level
                raw_auth = req_data.get("auth")
                if raw_auth and raw_auth.get("type") not in (None, "noauth"):
                    auth_type, auth_config = _parse_auth(raw_auth)
                elif collection_auth[0] != "none":
                    auth_type, auth_config = collection_auth
                else:
                    auth_type, auth_config = "none", {}

            if not url:
                errors.append(ParseError(request_name=full_name, reason="Missing or invalid URL"))
                continue

            requests.append(ParsedRequest(
                name=full_name[:200],
                method=method,
                url=url[:2000],
                headers=headers,
                body=body,
                body_type=body_type,
                auth_type=auth_type,
                auth_config=auth_config,
                order_index=order,
            ))
            order += 1

        except Exception as exc:
            errors.append(ParseError(request_name=full_name, reason=str(exc)))

    return requests, errors


# ── Public entry point ────────────────────────────────────────────────────────

def parse_collection(data: dict) -> ParsedCollection:
    """
    Parse a Postman collection dict into a ParsedCollection.

    Raises ValueError for invalid/unrecognised collection format.
    All per-request errors are collected in ParsedCollection.errors.
    """
    if not isinstance(data, dict):
        raise ValueError("Invalid format — expected a JSON object")

    info = data.get("info")
    if not isinstance(info, dict):
        raise ValueError("Missing 'info' field — is this a Postman collection?")

    schema = info.get("schema", "")
    # Accept if schema URL contains the known identifiers or is empty
    schema_ok = (
        not schema
        or any(s in schema for s in SUPPORTED_SCHEMAS)
        or "getpostman.com" in schema
    )
    if not schema_ok:
        raise ValueError(
            f"Unrecognised schema: {schema!r}. "
            "Only Postman Collection v2.0 and v2.1 are supported."
        )

    name        = info.get("name", "Imported Collection").strip() or "Imported Collection"
    description = info.get("description") or None

    # Collection-level auth (can be overridden per request)
    col_auth = _parse_auth(data.get("auth"))

    items = data.get("item", [])
    if not isinstance(items, list):
        raise ValueError("'item' must be an array")

    if not items:
        return ParsedCollection(
            name=name, description=description,
            requests=[], errors=[],
            warnings=["Collection is empty — no items found"],
        )

    requests, errors = _walk_items(items, "", 0, col_auth)

    warnings: list[str] = []
    if errors:
        warnings.append(
            f"{len(errors)} request(s) could not be parsed and were skipped."
        )

    return ParsedCollection(
        name=name, description=description,
        requests=requests, errors=errors, warnings=warnings,
    )
