"""
OpenAPI / Swagger import tests.

Structure:
  TestOpenAPIParser     — pure parser unit tests
  TestExampleGenerator  — JSON Schema → example value
  TestRefResolver       — $ref resolution
  TestOpenAPIEndpoint   — POST /workspaces/{id}/import/openapi
  TestSwaggerEndpoint   — Swagger 2.0 variant
  TestOpenAPIAuth       — 403 without token
  TestOpenAPIOwnership  — 404 for other user
"""
import io
import json
import pytest

from app.services.openapi_parser import (
    detect_format,
    parse_openapi,
    _generate_example,
    _resolve_ref,
    _build_base_url,
)

pytestmark = pytest.mark.asyncio

# ── Minimal spec fixtures ──────────────────────────────────────────────────────

def _oas3(title="Test API", paths=None, servers=None, components=None, security=None):
    spec = {
        "openapi": "3.0.0",
        "info": {"title": title, "version": "1.0.0"},
        "paths": paths or {},
    }
    if servers:   spec["servers"]    = servers
    if components: spec["components"] = components
    if security:  spec["security"]   = security
    return spec


def _swagger2(title="Test API", paths=None, host="api.example.com"):
    return {
        "swagger": "2.0",
        "info": {"title": title, "version": "1.0.0"},
        "host": host,
        "basePath": "/v1",
        "schemes": ["https"],
        "paths": paths or {},
    }


def _get_op(summary="List items", tags=None, params=None):
    op = {"summary": summary, "responses": {"200": {"description": "OK"}}}
    if tags:   op["tags"]       = tags
    if params: op["parameters"] = params
    return op


def _post_op(summary="Create", schema=None, tags=None):
    op = {
        "summary": summary,
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": schema or {"type": "object", "properties": {
                        "name": {"type": "string"}
                    }}
                }
            }
        },
        "responses": {"201": {"description": "Created"}},
    }
    if tags: op["tags"] = tags
    return op


# ── HTTP upload helpers ────────────────────────────────────────────────────────

async def _register(client, email: str) -> str:
    r = await client.post("/auth/register",
                          json={"name": "T", "email": email, "password": "Password1"})
    return r.json()["access_token"]


def _h(t: str): return {"Authorization": f"Bearer {t}"}


async def _make_ws(client, token: str) -> str:
    return (await client.post("/workspaces", json={"name": "W"},
                              headers=_h(token))).json()["id"]


async def _upload_openapi(client, token: str, ws_id: str, spec: dict) -> dict:
    content = json.dumps(spec).encode()
    return await client.post(
        f"/workspaces/{ws_id}/import/openapi",
        files={"file": ("api.json", io.BytesIO(content), "application/json")},
        headers=_h(token),
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. Format detection
# ══════════════════════════════════════════════════════════════════════════════

class TestFormatDetection:

    def test_openapi3_detected(self):
        assert detect_format({"openapi": "3.0.0", "paths": {}}) == "openapi3"

    def test_openapi31_detected(self):
        assert detect_format({"openapi": "3.1.0", "paths": {}}) == "openapi3"

    def test_swagger2_detected(self):
        assert detect_format({"swagger": "2.0", "paths": {}}) == "swagger2"

    def test_unknown_returns_none(self):
        assert detect_format({"info": {"title": "X"}}) is None

    def test_postman_returns_none(self):
        assert detect_format({"info": {"schema": "getpostman.com"}, "item": []}) is None

    def test_non_dict_returns_none(self):
        assert detect_format("not a dict") is None  # type: ignore


# ══════════════════════════════════════════════════════════════════════════════
# 2. $ref resolution
# ══════════════════════════════════════════════════════════════════════════════

class TestRefResolver:

    def test_resolves_component_schema(self):
        root = {"components": {"schemas": {"User": {"type": "object"}}}}
        result = _resolve_ref("#/components/schemas/User", root)
        assert result == {"type": "object"}

    def test_resolves_definitions(self):
        root = {"definitions": {"Pet": {"type": "string"}}}
        result = _resolve_ref("#/definitions/Pet", root)
        assert result == {"type": "string"}

    def test_missing_ref_returns_empty(self):
        assert _resolve_ref("#/components/schemas/Missing", {}) == {}

    def test_non_local_ref_returns_empty(self):
        assert _resolve_ref("https://external.com/schema", {}) == {}

    def test_tilde_encoding(self):
        root = {"components": {"schemas": {"my/schema": {"type": "number"}}}}
        result = _resolve_ref("#/components/schemas/my~1schema", root)
        assert result == {"type": "number"}


# ══════════════════════════════════════════════════════════════════════════════
# 3. Example generation
# ══════════════════════════════════════════════════════════════════════════════

class TestExampleGenerator:

    def test_string_type(self):
        assert isinstance(_generate_example({"type": "string"}, {}), str)

    def test_integer_type(self):
        assert isinstance(_generate_example({"type": "integer"}, {}), int)

    def test_number_type(self):
        ex = _generate_example({"type": "number"}, {})
        assert isinstance(ex, (int, float))

    def test_boolean_type(self):
        assert isinstance(_generate_example({"type": "boolean"}, {}), bool)

    def test_object_type(self):
        schema = {"type": "object", "properties": {
            "name":  {"type": "string"},
            "count": {"type": "integer"},
        }}
        ex = _generate_example(schema, {})
        assert isinstance(ex, dict)
        assert "name" in ex
        assert "count" in ex

    def test_array_type(self):
        schema = {"type": "array", "items": {"type": "string"}}
        ex = _generate_example(schema, {})
        assert isinstance(ex, list)
        assert len(ex) == 1

    def test_email_format(self):
        ex = _generate_example({"type": "string", "format": "email"}, {})
        assert "@" in ex

    def test_date_format(self):
        ex = _generate_example({"type": "string", "format": "date"}, {})
        assert "-" in ex   # YYYY-MM-DD

    def test_uuid_format(self):
        ex = _generate_example({"type": "string", "format": "uuid"}, {})
        assert "-" in ex

    def test_explicit_example_used(self):
        schema = {"type": "string", "example": "hello"}
        assert _generate_example(schema, {}) == "hello"

    def test_enum_uses_first_value(self):
        schema = {"type": "string", "enum": ["active", "inactive"]}
        assert _generate_example(schema, {}) == "active"

    def test_ref_resolved_for_example(self):
        root = {"components": {"schemas": {"Name": {"type": "string", "example": "Alice"}}}}
        schema = {"$ref": "#/components/schemas/Name"}
        assert _generate_example(schema, root) == "Alice"

    def test_nested_object(self):
        schema = {
            "type": "object",
            "properties": {
                "user": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}}
                }
            }
        }
        ex = _generate_example(schema, {})
        assert isinstance(ex["user"], dict)
        assert "id" in ex["user"]

    def test_allOf_uses_first_subschema(self):
        schema = {
            "allOf": [
                {"type": "object", "properties": {"x": {"type": "integer"}}}
            ]
        }
        ex = _generate_example(schema, {})
        assert isinstance(ex, dict)


# ══════════════════════════════════════════════════════════════════════════════
# 4. Base URL extraction
# ══════════════════════════════════════════════════════════════════════════════

class TestBaseUrlExtraction:

    def test_oas3_server_url(self):
        spec = _oas3(servers=[{"url": "https://api.example.com/v2"}])
        url = _build_base_url(spec, "openapi3")
        assert url == "https://api.example.com/v2"

    def test_oas3_server_with_variable(self):
        spec = _oas3(servers=[{"url": "https://{tenant}.api.com"}])
        url = _build_base_url(spec, "openapi3")
        assert "{{env.tenant}}" in url

    def test_swagger2_url(self):
        spec = _swagger2()
        url = _build_base_url(spec, "swagger2")
        assert "api.example.com" in url
        assert "/v1" in url

    def test_oas3_no_servers(self):
        spec = _oas3()
        url = _build_base_url(spec, "openapi3")
        assert url == ""


# ══════════════════════════════════════════════════════════════════════════════
# 5. OpenAPI 3 parser
# ══════════════════════════════════════════════════════════════════════════════

class TestOpenAPIParser:

    def test_empty_paths(self):
        result = parse_openapi(_oas3())
        assert result.name == "Test API"
        assert result.requests == []

    def test_single_get(self):
        spec = _oas3(paths={"/users": {"get": _get_op("List users")}})
        result = parse_openapi(spec)
        assert len(result.requests) == 1
        r = result.requests[0]
        assert r.method == "GET"
        assert r.url.endswith("/users")

    def test_multiple_methods_on_same_path(self):
        spec = _oas3(paths={
            "/pets": {
                "get":  _get_op("List"),
                "post": _post_op("Create"),
            }
        })
        result = parse_openapi(spec)
        methods = {r.method for r in result.requests}
        assert methods == {"GET", "POST"}

    def test_tag_prefix_applied(self):
        spec = _oas3(paths={
            "/users": {"get": _get_op("List", tags=["users"])}
        })
        result = parse_openapi(spec)
        assert result.requests[0].name.startswith("users")

    def test_no_tag_no_prefix(self):
        spec = _oas3(paths={
            "/health": {"get": _get_op("Health check")}
        })
        result = parse_openapi(spec)
        assert ">" not in result.requests[0].name

    def test_path_param_converted(self):
        spec = _oas3(paths={"/users/{userId}": {"get": _get_op()}})
        result = parse_openapi(spec)
        assert "{{env.userId}}" in result.requests[0].url

    def test_json_body_example_generated(self):
        schema = {"type": "object", "properties": {
            "name":  {"type": "string", "example": "Alice"},
            "email": {"type": "string", "format": "email"},
        }}
        spec = _oas3(paths={"/users": {"post": _post_op(schema=schema)}})
        result = parse_openapi(spec)
        assert result.requests[0].body is not None
        body = json.loads(result.requests[0].body)
        assert "name" in body or "email" in body

    def test_content_type_header_added_for_json_body(self):
        spec = _oas3(paths={"/items": {"post": _post_op()}})
        result = parse_openapi(spec)
        headers = result.requests[0].headers
        assert headers.get("Content-Type") == "application/json"

    def test_header_param_extracted(self):
        spec = _oas3(paths={"/items": {"get": _get_op(params=[
            {"in": "header", "name": "X-Trace-ID", "schema": {"type": "string"}}
        ])}})
        result = parse_openapi(spec)
        assert "X-Trace-ID" in result.requests[0].headers

    def test_bearer_security_scheme(self):
        components = {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer"}
            }
        }
        op = {**_get_op(), "security": [{"bearerAuth": []}]}
        spec = _oas3(paths={"/protected": {"get": op}}, components=components)
        result = parse_openapi(spec)
        r = result.requests[0]
        assert r.auth_type == "bearer"
        assert "bearerAuth" in r.auth_config.get("token", "")

    def test_apikey_security_scheme(self):
        components = {
            "securitySchemes": {
                "apiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
            }
        }
        op = {**_get_op(), "security": [{"apiKey": []}]}
        spec = _oas3(paths={"/data": {"get": op}}, components=components)
        result = parse_openapi(spec)
        r = result.requests[0]
        assert r.auth_type == "api_key"
        assert r.auth_config.get("header") == "X-API-Key"

    def test_ref_in_request_body_resolved(self):
        components = {
            "schemas": {
                "CreateUser": {"type": "object", "properties": {
                    "username": {"type": "string", "example": "alice"}
                }}
            }
        }
        op = {
            "summary": "Create",
            "requestBody": {
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CreateUser"}}}
            },
            "responses": {"201": {"description": "OK"}},
        }
        spec = _oas3(paths={"/users": {"post": op}}, components=components)
        result = parse_openapi(spec)
        assert result.requests[0].body is not None
        body = json.loads(result.requests[0].body)
        assert body.get("username") == "alice"

    def test_deprecated_operation_skipped(self):
        op = {**_get_op(), "deprecated": True}
        spec = _oas3(paths={"/old": {"get": op}})
        result = parse_openapi(spec)
        assert len(result.requests) == 0
        assert len(result.warnings) >= 1

    def test_ordered_by_path_then_method(self):
        spec = _oas3(paths={
            "/z": {"get": _get_op()},
            "/a": {"get": _get_op()},
        })
        result = parse_openapi(spec)
        # Both parsed, order_index set sequentially
        assert result.requests[0].order_index == 0
        assert result.requests[1].order_index == 1

    def test_collection_title_from_info(self):
        spec = _oas3(title="My Petstore")
        result = parse_openapi(spec)
        assert result.name == "My Petstore"


# ══════════════════════════════════════════════════════════════════════════════
# 6. Swagger 2.0 parser
# ══════════════════════════════════════════════════════════════════════════════

class TestSwaggerParser:

    def test_swagger2_parsed(self):
        spec = _swagger2(paths={"/pets": {"get": _get_op()}})
        result = parse_openapi(spec)
        assert len(result.requests) == 1

    def test_swagger2_url_built(self):
        spec = _swagger2(paths={"/pets": {"get": _get_op()}})
        result = parse_openapi(spec)
        assert "api.example.com" in result.requests[0].url

    def test_swagger2_body_parameter(self):
        op = {
            "summary": "Create",
            "parameters": [{
                "in": "body",
                "name": "body",
                "schema": {"type": "object", "properties": {
                    "name": {"type": "string", "example": "Rex"}
                }}
            }],
            "responses": {"201": {"description": "Created"}},
        }
        spec = _swagger2(paths={"/pets": {"post": op}})
        result = parse_openapi(spec)
        r = result.requests[0]
        assert r.body is not None
        body = json.loads(r.body)
        assert body.get("name") == "Rex"

    def test_invalid_format_raises(self):
        import pytest
        with pytest.raises(ValueError):
            parse_openapi({"info": {"title": "X"}, "paths": {}})


# ══════════════════════════════════════════════════════════════════════════════
# 7. HTTP endpoint — OpenAPI import
# ══════════════════════════════════════════════════════════════════════════════

class TestOpenAPIEndpoint:

    async def test_import_creates_collection(self, client):
        token = await _register(client, "oai1@test.com")
        ws    = await _make_ws(client, token)
        spec  = _oas3("My API", paths={
            "/users": {"get": _get_op("List users")},
            "/items": {"post": _post_op("Create item")},
        })
        r = await _upload_openapi(client, token, ws, spec)
        assert r.status_code == 201
        b = r.json()
        assert b["collection_name"] == "My API"
        assert b["total_requests"] == 2
        assert b["skipped"] == 0

    async def test_requests_have_correct_methods(self, client):
        token = await _register(client, "oai2@test.com")
        ws    = await _make_ws(client, token)
        spec  = _oas3(paths={
            "/pets": {"get": _get_op(), "post": _post_op(), "delete": {"responses": {"204": {"description": "OK"}}}}
        })
        r = await _upload_openapi(client, token, ws, spec)
        assert r.status_code == 201
        assert r.json()["total_requests"] == 3

    async def test_server_url_used_in_request(self, client):
        token = await _register(client, "oai3@test.com")
        ws    = await _make_ws(client, token)
        spec  = _oas3(
            paths={"/users": {"get": _get_op()}},
            servers=[{"url": "https://api.myapp.com/v2"}],
        )
        r = await _upload_openapi(client, token, ws, spec)
        col_id = r.json()["collection_id"]
        reqs = (await client.get(f"/collections/{col_id}/requests", headers=_h(token))).json()
        assert "api.myapp.com" in reqs[0]["url"]

    async def test_path_params_converted_to_env_vars(self, client):
        token = await _register(client, "oai4@test.com")
        ws    = await _make_ws(client, token)
        spec  = _oas3(paths={"/users/{userId}/posts/{postId}": {"get": _get_op()}})
        r = await _upload_openapi(client, token, ws, spec)
        col_id = r.json()["collection_id"]
        reqs = (await client.get(f"/collections/{col_id}/requests", headers=_h(token))).json()
        assert "{{env.userId}}" in reqs[0]["url"]
        assert "{{env.postId}}" in reqs[0]["url"]

    async def test_wrong_format_rejected(self, client):
        token = await _register(client, "oai5@test.com")
        ws    = await _make_ws(client, token)
        postman_col = {"info": {"name": "T", "schema": "getpostman.com"}, "item": []}
        r = await _upload_openapi(client, token, ws, postman_col)
        assert r.status_code == 422

    async def test_invalid_json_rejected(self, client):
        token = await _register(client, "oai6@test.com")
        ws    = await _make_ws(client, token)
        r = await client.post(
            f"/workspaces/{ws}/import/openapi",
            files={"file": ("api.json", b"not json", "application/json")},
            headers=_h(token),
        )
        assert r.status_code == 422

    async def test_swagger2_imported_via_openapi_endpoint(self, client):
        token = await _register(client, "oai7@test.com")
        ws    = await _make_ws(client, token)
        spec  = _swagger2("Petstore", {"/pets": {"get": _get_op()}})
        r = await _upload_openapi(client, token, ws, spec)
        assert r.status_code == 201
        assert r.json()["total_requests"] == 1

    async def test_wrong_extension_rejected(self, client):
        token = await _register(client, "oai8@test.com")
        ws    = await _make_ws(client, token)
        spec  = _oas3(paths={"/x": {"get": _get_op()}})
        content = json.dumps(spec).encode()
        r = await client.post(
            f"/workspaces/{ws}/import/openapi",
            files={"file": ("api.xml", io.BytesIO(content), "text/xml")},
            headers=_h(token),
        )
        assert r.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# 8. Auth + Ownership
# ══════════════════════════════════════════════════════════════════════════════

class TestOpenAPIAuth:

    async def test_requires_bearer(self, client):
        spec = _oas3(paths={"/x": {"get": _get_op()}})
        content = json.dumps(spec).encode()
        r = await client.post(
            "/workspaces/any/import/openapi",
            files={"file": ("api.json", io.BytesIO(content), "application/json")},
        )
        assert r.status_code == 403


class TestOpenAPIOwnership:

    async def test_other_user_cannot_import(self, client):
        owner = await _register(client, "own_oa1@test.com")
        other = await _register(client, "oth_oa1@test.com")
        ws    = await _make_ws(client, owner)
        spec  = _oas3(paths={"/x": {"get": _get_op()}})
        r = await _upload_openapi(client, other, ws, spec)
        assert r.status_code == 404
