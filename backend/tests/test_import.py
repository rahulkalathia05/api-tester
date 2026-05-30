"""
Postman Collection Import tests.

Structure:
  TestPostmanParser   — pure parser unit tests (no DB, no HTTP)
  TestImportEndpoint  — POST /workspaces/{id}/import/postman
  TestImportAuth      — endpoint requires bearer token
  TestImportOwnership — cross-user isolation
"""
import json
import io
import pytest

from app.services.postman_parser import parse_collection, _parse_url, _to_env_var

pytestmark = pytest.mark.asyncio

# ── Fixtures — minimal valid Postman collections ──────────────────────────────

def _col(name="Test", items=None):
    return {
        "info": {
            "name": name,
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": items or [],
    }

def _req_item(name="GET Users", method="GET", url="https://api.example.com/users",
              headers=None, body=None, auth=None):
    item = {
        "name": name,
        "request": {
            "method": method,
            "header": headers or [],
            "url": {"raw": url},
        }
    }
    if body: item["request"]["body"] = body
    if auth: item["request"]["auth"] = auth
    return item


# ── HTTP helpers ──────────────────────────────────────────────────────────────

async def _register(client, email: str) -> str:
    r = await client.post("/auth/register",
                          json={"name": "T", "email": email, "password": "Password1"})
    return r.json()["access_token"]


def _h(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


async def _upload(client, token: str, ws_id: str, data: dict, filename="col.json") -> dict:
    content = json.dumps(data).encode()
    return await client.post(
        f"/workspaces/{ws_id}/import/postman",
        files={"file": (filename, io.BytesIO(content), "application/json")},
        headers=_h(token),
    )


async def _make_workspace(client, token: str) -> str:
    return (await client.post("/workspaces", json={"name": "W"},
                              headers=_h(token))).json()["id"]


# ══════════════════════════════════════════════════════════════════════════════
# 1. Parser — pure unit tests
# ══════════════════════════════════════════════════════════════════════════════

class TestPostmanParser:

    # ── Variable substitution ──────────────────────────────────────────────────

    def test_var_replacement(self):
        assert _to_env_var("{{baseUrl}}/users") == "{{env.baseUrl}}/users"

    def test_var_replacement_multiple(self):
        result = _to_env_var("{{host}}/{{version}}/users")
        assert result == "{{env.host}}/{{env.version}}/users"

    def test_var_no_replacement_needed(self):
        assert _to_env_var("https://api.example.com") == "https://api.example.com"

    # ── URL parsing ────────────────────────────────────────────────────────────

    def test_url_string(self):
        assert _parse_url("https://api.example.com/users") == "https://api.example.com/users"

    def test_url_raw_field(self):
        assert _parse_url({"raw": "https://api.example.com/users"}) == "https://api.example.com/users"

    def test_url_parts_reconstruction(self):
        url = _parse_url({
            "protocol": "https",
            "host": ["api", "example", "com"],
            "path": ["v1", "users"],
        })
        assert "api.example.com" in url
        assert "v1" in url
        assert "users" in url

    def test_url_with_variable(self):
        url = _parse_url({"raw": "{{baseUrl}}/users"})
        assert url == "{{env.baseUrl}}/users"

    # ── Collection parse ───────────────────────────────────────────────────────

    def test_empty_collection(self):
        result = parse_collection(_col())
        assert result.name == "Test"
        assert result.requests == []
        assert len(result.warnings) >= 1

    def test_simple_get_request(self):
        col = _col(items=[_req_item()])
        result = parse_collection(col)
        assert len(result.requests) == 1
        r = result.requests[0]
        assert r.method == "GET"
        assert r.name == "GET Users"
        assert "api.example.com" in r.url

    def test_multiple_requests_ordered(self):
        col = _col(items=[
            _req_item("R1"), _req_item("R2"), _req_item("R3")
        ])
        result = parse_collection(col)
        assert len(result.requests) == 3
        assert [r.order_index for r in result.requests] == [0, 1, 2]

    def test_folder_flattened_with_prefix(self):
        col = _col(items=[{
            "name": "Auth",
            "item": [_req_item("Login"), _req_item("Logout")],
        }])
        result = parse_collection(col)
        assert len(result.requests) == 2
        assert result.requests[0].name == "Auth > Login"
        assert result.requests[1].name == "Auth > Logout"

    def test_nested_folder(self):
        col = _col(items=[{
            "name": "API",
            "item": [{
                "name": "Users",
                "item": [_req_item("List")],
            }],
        }])
        result = parse_collection(col)
        assert result.requests[0].name == "API > Users > List"

    def test_headers_parsed(self):
        headers = [
            {"key": "Content-Type", "value": "application/json"},
            {"key": "Accept",       "value": "application/json", "disabled": False},
            {"key": "X-Hidden",     "value": "secret",           "disabled": True},
        ]
        col = _col(items=[_req_item(headers=headers)])
        result = parse_collection(col)
        assert result.requests[0].headers["Content-Type"] == "application/json"
        assert result.requests[0].headers["Accept"] == "application/json"
        assert "X-Hidden" not in result.requests[0].headers

    def test_json_body_parsed(self):
        body = {"mode": "raw", "raw": '{"key": "value"}',
                "options": {"raw": {"language": "json"}}}
        col = _col(items=[_req_item(method="POST", body=body)])
        result = parse_collection(col)
        r = result.requests[0]
        assert r.body == '{"key": "value"}'
        assert r.body_type == "json"

    def test_raw_body_non_json(self):
        body = {"mode": "raw", "raw": "plain text", "options": {"raw": {"language": "text"}}}
        col = _col(items=[_req_item(body=body)])
        result = parse_collection(col)
        assert result.requests[0].body_type == "raw"

    def test_urlencoded_body(self):
        body = {"mode": "urlencoded", "urlencoded": [
            {"key": "username", "value": "alice"},
            {"key": "password", "value": "secret"},
        ]}
        col = _col(items=[_req_item(body=body)])
        result = parse_collection(col)
        r = result.requests[0]
        assert r.body_type == "form"
        assert "username=alice" in r.body

    def test_bearer_auth(self):
        auth = {"type": "bearer", "bearer": [{"key": "token", "value": "my-token"}]}
        col = _col(items=[_req_item(auth=auth)])
        result = parse_collection(col)
        r = result.requests[0]
        assert r.auth_type == "bearer"
        assert r.auth_config["token"] == "my-token"

    def test_basic_auth(self):
        auth = {"type": "basic", "basic": [
            {"key": "username", "value": "user"},
            {"key": "password", "value": "pass"},
        ]}
        col = _col(items=[_req_item(auth=auth)])
        result = parse_collection(col)
        r = result.requests[0]
        assert r.auth_type == "basic"
        assert r.auth_config["username"] == "user"
        assert r.auth_config["password"] == "pass"

    def test_api_key_auth(self):
        auth = {"type": "apikey", "apikey": [
            {"key": "key",   "value": "X-API-Key"},
            {"key": "value", "value": "sk-secret"},
        ]}
        col = _col(items=[_req_item(auth=auth)])
        result = parse_collection(col)
        r = result.requests[0]
        assert r.auth_type == "api_key"
        assert r.auth_config["header"] == "X-API-Key"
        assert r.auth_config["value"] == "sk-secret"

    def test_collection_level_auth_used_when_no_request_auth(self):
        col = {
            "info": {"name": "T", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
            "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "col-token"}]},
            "item": [_req_item()],
        }
        result = parse_collection(col)
        assert result.requests[0].auth_type == "bearer"
        assert result.requests[0].auth_config["token"] == "col-token"

    def test_request_auth_overrides_collection_auth(self):
        col = {
            "info": {"name": "T", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
            "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "col-token"}]},
            "item": [_req_item(auth={"type": "bearer", "bearer": [{"key": "token", "value": "req-token"}]})],
        }
        result = parse_collection(col)
        assert result.requests[0].auth_config["token"] == "req-token"

    def test_invalid_method_defaults_to_get(self):
        col = _col(items=[_req_item(method="INVALID")])
        result = parse_collection(col)
        assert result.requests[0].method == "GET"

    def test_missing_url_records_error(self):
        col = _col(items=[{"name": "Bad", "request": {"method": "GET"}}])
        result = parse_collection(col)
        assert len(result.requests) == 0
        assert len(result.errors) == 1
        assert result.errors[0].request_name == "Bad"

    def test_env_var_in_url_converted(self):
        col = _col(items=[_req_item(url="{{baseUrl}}/v1/users")])
        result = parse_collection(col)
        assert result.requests[0].url == "{{env.baseUrl}}/v1/users"

    def test_env_var_in_header_value_converted(self):
        headers = [{"key": "Authorization", "value": "Bearer {{authToken}}"}]
        col = _col(items=[_req_item(headers=headers)])
        result = parse_collection(col)
        assert result.requests[0].headers["Authorization"] == "Bearer {{env.authToken}}"

    def test_invalid_schema_raises(self):
        data = {"info": {"name": "T", "schema": "some-other-tool://schema"}, "item": []}
        import pytest
        with pytest.raises(ValueError, match="Unrecognised schema"):
            parse_collection(data)

    def test_missing_info_raises(self):
        with pytest.raises(ValueError):
            parse_collection({"item": []})

    def test_v20_schema_accepted(self):
        data = {"info": {"name": "T", "schema": "https://schema.getpostman.com/json/collection/v2.0.0/collection.json"}, "item": []}
        result = parse_collection(data)
        assert result.name == "T"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Import endpoint
# ══════════════════════════════════════════════════════════════════════════════

class TestImportEndpoint:

    async def test_import_simple_collection(self, client):
        token = await _register(client, "imp1@test.com")
        ws    = await _make_workspace(client, token)
        col   = _col("My APIs", [_req_item(), _req_item("POST Create", "POST", "https://api.example.com/users")])
        r = await _upload(client, token, ws, col)
        assert r.status_code == 201
        b = r.json()
        assert b["collection_name"] == "My APIs"
        assert b["total_requests"] == 2
        assert b["skipped"] == 0
        assert "collection_id" in b

    async def test_imported_collection_visible_in_workspace(self, client):
        token = await _register(client, "imp2@test.com")
        ws    = await _make_workspace(client, token)
        col   = _col("Imported", [_req_item()])
        r = await _upload(client, token, ws, col)
        col_id = r.json()["collection_id"]
        assert col_id  # collection_id returned
        # Verify requests are visible
        reqs = (await client.get(f"/collections/{col_id}/requests", headers=_h(token))).json()
        assert len(reqs) == 1  # list of ApiRequestOut

    async def test_requests_created_with_correct_data(self, client):
        token = await _register(client, "imp3@test.com")
        ws    = await _make_workspace(client, token)
        col   = _col("API", [_req_item(
            "Get Posts", "GET", "https://jsonplaceholder.typicode.com/posts",
            headers=[{"key": "Accept", "value": "application/json"}],
        )])
        r = await _upload(client, token, ws, col)
        col_id = r.json()["collection_id"]

        # GET /collections/{id}/requests returns list[ApiRequestOut]
        reqs = (await client.get(f"/collections/{col_id}/requests", headers=_h(token))).json()
        assert len(reqs) == 1
        req = reqs[0]
        assert req["method"] == "GET"
        assert "jsonplaceholder" in req["url"]

    async def test_partial_import_with_errors(self, client):
        token = await _register(client, "imp4@test.com")
        ws    = await _make_workspace(client, token)
        col   = _col("Mixed", [
            _req_item("Good One"),
            {"name": "Bad One", "request": {"method": "GET"}},  # no URL
        ])
        r = await _upload(client, token, ws, col)
        assert r.status_code == 201
        b = r.json()
        assert b["total_requests"] == 1
        assert b["skipped"] == 1
        assert len(b["errors"]) == 1

    async def test_non_json_file_rejected(self, client):
        token = await _register(client, "imp5@test.com")
        ws    = await _make_workspace(client, token)
        r = await client.post(
            f"/workspaces/{ws}/import/postman",
            files={"file": ("collection.xml", b"<xml/>", "text/xml")},
            headers=_h(token),
        )
        assert r.status_code == 422

    async def test_invalid_json_rejected(self, client):
        token = await _register(client, "imp6@test.com")
        ws    = await _make_workspace(client, token)
        r = await client.post(
            f"/workspaces/{ws}/import/postman",
            files={"file": ("col.json", b"not json", "application/json")},
            headers=_h(token),
        )
        assert r.status_code == 422

    async def test_wrong_schema_rejected(self, client):
        token = await _register(client, "imp7@test.com")
        ws    = await _make_workspace(client, token)
        bad   = {"info": {"name": "T", "schema": "other://tool"}, "item": []}
        r = await _upload(client, token, ws, bad)
        assert r.status_code == 422

    async def test_postman_v20_accepted(self, client):
        token = await _register(client, "imp8@test.com")
        ws    = await _make_workspace(client, token)
        col   = {
            "info": {"name": "V2", "schema": "https://schema.getpostman.com/json/collection/v2.0.0/collection.json"},
            "item": [_req_item()],
        }
        r = await _upload(client, token, ws, col)
        assert r.status_code == 201

    async def test_folder_requests_imported(self, client):
        token = await _register(client, "imp9@test.com")
        ws    = await _make_workspace(client, token)
        col   = _col("With Folders", [{
            "name": "Auth",
            "item": [_req_item("Login"), _req_item("Logout")],
        }])
        r = await _upload(client, token, ws, col)
        assert r.json()["total_requests"] == 2

    async def test_env_vars_converted_in_url(self, client):
        token = await _register(client, "imp10@test.com")
        ws    = await _make_workspace(client, token)
        col   = _col("Vars", [_req_item(url="{{baseUrl}}/users")])
        r = await _upload(client, token, ws, col)
        col_id = r.json()["collection_id"]
        reqs = (await client.get(f"/collections/{col_id}/requests", headers=_h(token))).json()
        assert "{{env.baseUrl}}" in reqs[0]["url"]


# ══════════════════════════════════════════════════════════════════════════════
# 3. Auth
# ══════════════════════════════════════════════════════════════════════════════

class TestImportAuth:

    async def test_requires_bearer(self, client):
        col = _col(items=[_req_item()])
        r = await client.post(
            "/workspaces/any-id/import/postman",
            files={"file": ("col.json", json.dumps(col).encode(), "application/json")},
        )
        assert r.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# 4. Ownership
# ══════════════════════════════════════════════════════════════════════════════

class TestImportOwnership:

    async def test_other_user_cannot_import(self, client):
        owner = await _register(client, "own_i1@test.com")
        other = await _register(client, "oth_i1@test.com")
        ws    = await _make_workspace(client, owner)
        col   = _col(items=[_req_item()])
        r = await _upload(client, other, ws, col)
        assert r.status_code == 404
