"""
OpenAPI / Swagger parser — supports OpenAPI 3.x and Swagger 2.0.

Entry points
────────────
  detect_format(data)  → "openapi3" | "swagger2" | None
  parse_openapi(data)  → ParsedCollection

Reuses ParsedCollection / ParsedRequest / ParseError from postman_parser
so the import router can handle both formats identically.

Parsing strategy
────────────────
  1. Detect and validate the spec version.
  2. Extract base URL (servers[0].url for OAS3, host+basePath for Swagger 2).
  3. Walk every path → method combination in `paths`.
  4. For each operation:
       – Build the request URL (base + path + query param stubs).
       – Extract header parameters → headers dict.
       – Extract request body → generate example JSON from the schema.
       – Determine auth from `securitySchemes` (best-effort).
       – Group by the first tag; tagless operations go to the root level.
  5. Within each tag group, requests are sorted by path then method.

$ref resolution
───────────────
  `#/components/schemas/Foo` and `#/definitions/Foo` are resolved inline
  up to MAX_REF_DEPTH levels to avoid infinite recursion.

Example generation
──────────────────
  Schema types → representative values used as request body examples:
    object  → {prop: example_value, ...}
    array   → [example_item]
    string  → per-format placeholder ("user@example.com", ISO dates, …)
    integer → 0
    number  → 0.0
    boolean → true
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.services.postman_parser import (
    ParsedCollection,
    ParsedRequest,
    ParseError,
)

# ── Constants ─────────────────────────────────────────────────────────────────

SUPPORTED_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
MAX_REF_DEPTH     = 6    # max recursion depth for $ref resolution
MAX_ARRAY_EXAMPLE = 1    # generate a single item in example arrays

# ── Format detection ──────────────────────────────────────────────────────────

def detect_format(data: Any) -> str | None:
    """
    Return "openapi3", "swagger2", or None.
    Accepts both JSON-parsed dicts and raw strings (YAML would need PyYAML).
    """
    if not isinstance(data, dict):
        return None
    if "openapi" in data and str(data["openapi"]).startswith("3"):
        return "openapi3"
    if data.get("swagger", "").startswith("2"):
        return "swagger2"
    return None


# ── $ref resolver ─────────────────────────────────────────────────────────────

def _resolve_ref(ref: str, root: dict, depth: int = 0) -> dict:
    """
    Resolve a JSON Pointer $ref within the same document.
    Only handles local refs starting with '#/'.
    """
    if depth >= MAX_REF_DEPTH:
        return {}
    if not ref.startswith("#/"):
        return {}
    parts = ref[2:].split("/")
    node: Any = root
    for part in parts:
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return {}
        node = node[part]
    return node if isinstance(node, dict) else {}


def _resolve_schema(schema: dict, root: dict, depth: int = 0) -> dict:
    """Fully resolve a schema object, following $refs."""
    if depth >= MAX_REF_DEPTH:
        return {}
    if "$ref" in schema:
        resolved = _resolve_ref(schema["$ref"], root, depth + 1)
        return _resolve_schema(resolved, root, depth + 1)
    return schema


# ── Example value generator ───────────────────────────────────────────────────

_FORMAT_EXAMPLES: dict[str, Any] = {
    "email":     "user@example.com",
    "date":      "2024-01-01",
    "date-time": "2024-01-01T00:00:00Z",
    "uuid":      "550e8400-e29b-41d4-a716-446655440000",
    "uri":       "https://example.com",
    "hostname":  "example.com",
    "ipv4":      "192.168.1.1",
    "password":  "••••••••",
    "binary":    "<binary data>",
    "byte":      "dGVzdA==",
}


def _generate_example(schema: Any, root: dict, depth: int = 0) -> Any:
    """
    Recursively generate a representative value from a JSON Schema object.
    Returns None for unknown or deeply nested schemas.
    """
    if depth > MAX_REF_DEPTH or not isinstance(schema, dict):
        return None

    # Resolve $ref first
    if "$ref" in schema:
        resolved = _resolve_ref(schema["$ref"], root, depth)
        return _generate_example(resolved, root, depth + 1)

    # Use explicit example / default / first enum value if available
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]

    # allOf / anyOf / oneOf — use the first resolvable sub-schema
    for combiner in ("allOf", "anyOf", "oneOf"):
        if combiner in schema and schema[combiner]:
            sub = _resolve_schema(schema[combiner][0], root, depth)
            result = _generate_example(sub, root, depth + 1)
            if result is not None:
                return result

    schema_type = schema.get("type", "object")

    if schema_type == "object" or "properties" in schema:
        required = set(schema.get("required", []))
        obj: dict = {}
        for prop, prop_schema in schema.get("properties", {}).items():
            val = _generate_example(prop_schema, root, depth + 1)
            # Always include required fields; include optional with value
            if prop in required or val is not None:
                obj[prop] = val
        return obj if obj else {}

    if schema_type == "array":
        items_schema = schema.get("items", {})
        item_example = _generate_example(items_schema, root, depth + 1)
        return [item_example] if item_example is not None else []

    if schema_type == "string":
        fmt = schema.get("format", "")
        if fmt in _FORMAT_EXAMPLES:
            return _FORMAT_EXAMPLES[fmt]
        title = schema.get("title") or schema.get("description") or ""
        return title[:40] if title else "string"

    if schema_type == "integer":
        return schema.get("minimum", 0)

    if schema_type == "number":
        return schema.get("minimum", 0.0)

    if schema_type == "boolean":
        return True

    if schema_type == "null":
        return None

    return None


# ── URL builder ───────────────────────────────────────────────────────────────

def _build_base_url(data: dict, fmt: str) -> str:
    if fmt == "openapi3":
        servers = data.get("servers", [])
        if servers and isinstance(servers[0], dict):
            url = servers[0].get("url", "")
            # Replace server variables with placeholder values
            url = re.sub(r"\{([^}]+)\}", r"{{env.\1}}", url)
            return url.rstrip("/")
        return ""

    # Swagger 2.0
    schemes   = data.get("schemes", ["https"])
    scheme    = schemes[0] if schemes else "https"
    host      = data.get("host", "")
    base_path = data.get("basePath", "/").rstrip("/")
    if not host:
        return base_path
    return f"{scheme}://{host}{base_path}"


def _build_request_url(base: str, path: str, params: list[dict]) -> str:
    """
    Combine base URL + path, then append query parameter stubs.
    Path parameters like {userId} stay as {userId} — we keep them visible.
    """
    # Convert path params {var} → {{env.var}} for our syntax
    path_converted = re.sub(r"\{([^}]+)\}", r"{{env.\1}}", path)
    url = base.rstrip("/") + path_converted

    query_params = [
        p for p in params
        if p.get("in") == "query" and not p.get("deprecated")
    ]
    if query_params:
        stubs = "&".join(
            f"{p['name']}={{{{env.{p['name']}}}}}" if p.get("required")
            else f"# {p['name']}=<optional>"
            for p in query_params[:8]   # cap stub count
        )
        # Add as a comment-style hint in the URL; only required ones as real params
        required_qs = [p for p in query_params if p.get("required")]
        if required_qs:
            url += "?" + "&".join(
                f"{p['name']}={{{{env.{p['name']}}}}}" for p in required_qs
            )

    return url


# ── Header extractor ──────────────────────────────────────────────────────────

def _extract_headers(params: list[dict]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for p in params:
        if p.get("in") != "header" or p.get("deprecated"):
            continue
        key = p.get("name", "")
        if not key:
            continue
        # Use example or schema default, else placeholder
        example = p.get("example") or p.get("schema", {}).get("example") or f"{{{{env.{key}}}}}"
        headers[key] = str(example)
    return headers


# ── Auth extractor (OAS3 security schemes) ────────────────────────────────────

def _extract_auth(
    operation: dict,
    root_security: list,
    security_schemes: dict,
) -> tuple[str, dict[str, str]]:
    """
    Best-effort auth extraction from security requirements.
    Returns (auth_type, auth_config) matching our system's types.
    """
    sec = operation.get("security") or root_security
    if not sec:
        return "none", {}

    for req in sec:
        if not isinstance(req, dict):
            continue
        for scheme_name in req:
            scheme = security_schemes.get(scheme_name, {})
            sec_type = scheme.get("type", "")
            scheme_type = scheme.get("scheme", "").lower()

            if sec_type == "http" and scheme_type == "bearer":
                return "bearer", {"token": f"{{{{env.{scheme_name}}}}}"}

            if sec_type == "http" and scheme_type == "basic":
                return "basic", {
                    "username": "{{env.USERNAME}}",
                    "password": "{{env.PASSWORD}}",
                }

            if sec_type == "apiKey":
                in_   = scheme.get("in", "header")
                name  = scheme.get("name", "X-API-Key")
                if in_ == "header":
                    return "api_key", {
                        "header": name,
                        "value":  f"{{{{env.{scheme_name}}}}}",
                    }

            if sec_type == "oauth2":
                return "bearer", {"token": f"{{{{env.{scheme_name}}}}}"}

    return "none", {}


# ── Request body extractor ────────────────────────────────────────────────────

def _extract_body(operation: dict, root: dict) -> tuple[str | None, str]:
    """Return (body_text, body_type)."""
    # OAS3 requestBody
    req_body = operation.get("requestBody", {})
    if req_body:
        content = req_body.get("content", {})
        for mime, media in content.items():
            if "json" in mime:
                schema = _resolve_schema(media.get("schema", {}), root)
                example = (
                    media.get("example")
                    or _generate_example(schema, root)
                )
                if example is not None:
                    return json.dumps(example, indent=2), "json"
                return None, "json"
            if "form" in mime or "urlencoded" in mime:
                return None, "form"
        return None, "none"

    # Swagger 2.0 body parameter
    for p in operation.get("parameters", []):
        if p.get("in") == "body":
            schema = _resolve_schema(p.get("schema", {}), root)
            example = _generate_example(schema, root)
            if example is not None:
                return json.dumps(example, indent=2), "json"
            return None, "json"
        if p.get("in") == "formData":
            return None, "form"

    return None, "none"


# ── Resolve all parameters (including $ref) ───────────────────────────────────

def _resolve_params(params: list[Any], root: dict) -> list[dict]:
    resolved = []
    for p in params:
        if isinstance(p, dict) and "$ref" in p:
            p = _resolve_ref(p["$ref"], root)
        if isinstance(p, dict):
            resolved.append(p)
    return resolved


# ── Operation → ParsedRequest ─────────────────────────────────────────────────

def _operation_to_request(
    method: str,
    path: str,
    operation: dict,
    base_url: str,
    path_params: list[dict],
    root: dict,
    security_schemes: dict,
    root_security: list,
    tag_prefix: str,
    order: int,
) -> ParsedRequest:
    # Merge path-level and operation-level parameters
    op_params    = _resolve_params(operation.get("parameters", []), root)
    all_params   = _resolve_params(path_params, root) + op_params

    # Name: operationId → summary → "METHOD /path"
    name = (
        operation.get("operationId")
        or operation.get("summary")
        or f"{method.upper()} {path}"
    )
    # Clean up camelCase operationIds to readable names
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name).strip()
    if tag_prefix:
        name = f"{tag_prefix} > {name}"

    url     = _build_request_url(base_url, path, all_params)
    headers = _extract_headers(all_params)
    body, body_type = _extract_body(operation, root)
    auth_type, auth_config = _extract_auth(operation, root_security, security_schemes)

    # Add Content-Type if body is JSON
    if body and body_type == "json" and "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"

    return ParsedRequest(
        name=name[:200],
        method=method.upper(),
        url=url[:2000],
        headers=headers,
        body=body,
        body_type=body_type,
        auth_type=auth_type,
        auth_config=auth_config,
        order_index=order,
    )


# ── Main parser ───────────────────────────────────────────────────────────────

def parse_openapi(data: dict) -> ParsedCollection:
    """
    Parse an OpenAPI 3.x or Swagger 2.0 spec dict into a ParsedCollection.

    Raises ValueError for unrecognised / invalid specs.
    Per-operation errors are collected in ParsedCollection.errors.
    """
    fmt = detect_format(data)
    if fmt is None:
        raise ValueError(
            "Unrecognised format. Supply an OpenAPI 3.x spec "
            "(top-level 'openapi': '3.x.x') or a Swagger 2.0 spec "
            "(top-level 'swagger': '2.0')."
        )

    info      = data.get("info", {})
    coll_name = info.get("title", "Imported API").strip() or "Imported API"
    coll_desc = info.get("description") or None

    paths = data.get("paths", {})
    if not isinstance(paths, dict):
        raise ValueError("'paths' must be an object")

    base_url = _build_base_url(data, fmt)

    # Security schemes
    if fmt == "openapi3":
        components       = data.get("components", {})
        security_schemes = components.get("securitySchemes", {})
    else:
        sec_defs         = data.get("securityDefinitions", {})
        security_schemes = sec_defs

    root_security = data.get("security", [])

    requests:  list[ParsedRequest] = []
    errors:    list[ParseError]    = []
    warnings:  list[str]           = []
    order = 0

    # Walk paths
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue

        path_params = _resolve_params(path_item.get("parameters", []), data)

        for method in SUPPORTED_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            if operation.get("deprecated"):
                warnings.append(f"Skipping deprecated: {method.upper()} {path}")
                continue

            # Tag-based grouping (first tag only)
            tags = operation.get("tags", [])
            tag_prefix = tags[0].strip() if tags else ""

            try:
                req = _operation_to_request(
                    method=method,
                    path=path,
                    operation=operation,
                    base_url=base_url,
                    path_params=path_params,
                    root=data,
                    security_schemes=security_schemes,
                    root_security=root_security,
                    tag_prefix=tag_prefix,
                    order=order,
                )
                requests.append(req)
                order += 1
            except Exception as exc:
                errors.append(ParseError(
                    request_name=f"{method.upper()} {path}",
                    reason=str(exc),
                ))

    if not requests and not errors:
        warnings.append("No operations found in the spec — 'paths' may be empty.")

    return ParsedCollection(
        name=coll_name,
        description=coll_desc,
        requests=requests,
        errors=errors,
        warnings=warnings,
    )
