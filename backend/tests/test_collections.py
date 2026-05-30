"""
Collection, API Request, and Assertion management tests.

Coverage:
  Collections  — CRUD, pagination, name filter, ownership
  Requests     — CRUD, order_index, field validation, ownership
  Assertions   — CRUD, json_path path validation, ownership
  Auth         — every endpoint requires a valid Bearer token
  Cross-user   — one user cannot access another's data
"""
import pytest

pytestmark = pytest.mark.asyncio


# ── Fixtures / helpers ────────────────────────────────────────────────────────

async def _register_and_login(client, email: str, password: str = "Password1") -> str:
    """Return access token for a freshly created user."""
    res = await client.post(
        "/auth/register",
        json={"name": "Test", "email": email, "password": password},
    )
    assert res.status_code == 201
    return res.json()["access_token"]


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_workspace(client, token: str, name: str = "WS") -> str:
    res = await client.post("/workspaces", json={"name": name}, headers=_h(token))
    assert res.status_code == 201
    return res.json()["id"]


async def _make_collection(client, token: str, workspace_id: str, name: str = "Col") -> str:
    res = await client.post(
        f"/workspaces/{workspace_id}/collections",
        json={"name": name},
        headers=_h(token),
    )
    assert res.status_code == 201
    return res.json()["id"]


async def _make_request(client, token: str, collection_id: str, **kwargs) -> str:
    payload = {
        "name": "GET Users",
        "method": "GET",
        "url": "https://api.example.com/users",
        **kwargs,
    }
    res = await client.post(
        f"/collections/{collection_id}/requests",
        json=payload,
        headers=_h(token),
    )
    assert res.status_code == 201
    return res.json()["id"]


async def _make_assertion(client, token: str, request_id: str) -> str:
    res = await client.post(
        f"/requests/{request_id}/assertions",
        json={"type": "status_code", "operator": "eq", "expected_value": "200"},
        headers=_h(token),
    )
    assert res.status_code == 201
    return res.json()["id"]


# ══════════════════════════════════════════════════════════════════════════════
# Collections
# ══════════════════════════════════════════════════════════════════════════════

class TestCollectionCRUD:

    async def test_create_returns_201_with_fields(self, client):
        token = await _register_and_login(client, "cc1@test.com")
        ws_id = await _make_workspace(client, token)

        res = await client.post(
            f"/workspaces/{ws_id}/collections",
            json={"name": "My API", "description": "For testing"},
            headers=_h(token),
        )
        assert res.status_code == 201
        body = res.json()
        assert body["name"] == "My API"
        assert body["description"] == "For testing"
        assert body["workspace_id"] == ws_id
        assert body["request_count"] == 0
        assert "id" in body and "created_at" in body and "updated_at" in body

    async def test_create_without_description(self, client):
        token = await _register_and_login(client, "cc2@test.com")
        ws_id = await _make_workspace(client, token)
        res = await client.post(
            f"/workspaces/{ws_id}/collections",
            json={"name": "No Desc"},
            headers=_h(token),
        )
        assert res.status_code == 201
        assert res.json()["description"] is None

    async def test_list_empty(self, client):
        token = await _register_and_login(client, "cl1@test.com")
        ws_id = await _make_workspace(client, token)
        res = await client.get(f"/workspaces/{ws_id}/collections", headers=_h(token))
        assert res.status_code == 200
        body = res.json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["page"] == 1

    async def test_list_returns_created_collections(self, client):
        token = await _register_and_login(client, "cl2@test.com")
        ws_id = await _make_workspace(client, token)
        await _make_collection(client, token, ws_id, "Alpha")
        await _make_collection(client, token, ws_id, "Beta")

        res = await client.get(f"/workspaces/{ws_id}/collections", headers=_h(token))
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 2
        names = {c["name"] for c in body["items"]}
        assert names == {"Alpha", "Beta"}

    async def test_get_collection_includes_request_list(self, client):
        token = await _register_and_login(client, "cg1@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        await _make_request(client, token, col_id, name="Req A")
        await _make_request(client, token, col_id, name="Req B")

        res = await client.get(f"/collections/{col_id}", headers=_h(token))
        assert res.status_code == 200
        body = res.json()
        assert body["request_count"] == 2
        assert len(body["requests"]) == 2

    async def test_update_name_and_description(self, client):
        token = await _register_and_login(client, "cu1@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id, "Old Name")

        res = await client.patch(
            f"/collections/{col_id}",
            json={"name": "New Name", "description": "Updated desc"},
            headers=_h(token),
        )
        assert res.status_code == 200
        body = res.json()
        assert body["name"] == "New Name"
        assert body["description"] == "Updated desc"

    async def test_update_only_name(self, client):
        token = await _register_and_login(client, "cu2@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)

        res = await client.patch(
            f"/collections/{col_id}",
            json={"name": "Renamed"},
            headers=_h(token),
        )
        assert res.status_code == 200
        assert res.json()["name"] == "Renamed"

    async def test_delete_removes_collection(self, client):
        token = await _register_and_login(client, "cd1@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)

        res = await client.delete(f"/collections/{col_id}", headers=_h(token))
        assert res.status_code == 204

        res = await client.get(f"/collections/{col_id}", headers=_h(token))
        assert res.status_code == 404

    async def test_delete_cascades_to_requests(self, client):
        token = await _register_and_login(client, "cd2@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        req_id = await _make_request(client, token, col_id)

        await client.delete(f"/collections/{col_id}", headers=_h(token))

        res = await client.get(f"/requests/{req_id}", headers=_h(token))
        assert res.status_code == 404


class TestCollectionValidation:

    async def test_blank_name_rejected(self, client):
        token = await _register_and_login(client, "cv1@test.com")
        ws_id = await _make_workspace(client, token)
        res = await client.post(
            f"/workspaces/{ws_id}/collections",
            json={"name": "   "},
            headers=_h(token),
        )
        assert res.status_code == 422

    async def test_missing_name_rejected(self, client):
        token = await _register_and_login(client, "cv2@test.com")
        ws_id = await _make_workspace(client, token)
        res = await client.post(
            f"/workspaces/{ws_id}/collections",
            json={},
            headers=_h(token),
        )
        assert res.status_code == 422

    async def test_empty_patch_rejected(self, client):
        token = await _register_and_login(client, "cv3@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        res = await client.patch(f"/collections/{col_id}", json={}, headers=_h(token))
        assert res.status_code == 422


class TestCollectionPagination:

    async def test_pagination_page_and_size(self, client):
        token = await _register_and_login(client, "cp1@test.com")
        ws_id = await _make_workspace(client, token)
        for i in range(5):
            await _make_collection(client, token, ws_id, f"Col {i}")

        res = await client.get(
            f"/workspaces/{ws_id}/collections?page=1&page_size=2",
            headers=_h(token),
        )
        body = res.json()
        assert body["total"] == 5
        assert len(body["items"]) == 2
        assert body["pages"] == 3

    async def test_pagination_page_2(self, client):
        token = await _register_and_login(client, "cp2@test.com")
        ws_id = await _make_workspace(client, token)
        for i in range(5):
            await _make_collection(client, token, ws_id, f"Item {i}")

        res = await client.get(
            f"/workspaces/{ws_id}/collections?page=2&page_size=2",
            headers=_h(token),
        )
        body = res.json()
        assert len(body["items"]) == 2
        assert body["page"] == 2

    async def test_pagination_last_page_partial(self, client):
        token = await _register_and_login(client, "cp3@test.com")
        ws_id = await _make_workspace(client, token)
        for i in range(5):
            await _make_collection(client, token, ws_id, f"P {i}")

        res = await client.get(
            f"/workspaces/{ws_id}/collections?page=3&page_size=2",
            headers=_h(token),
        )
        body = res.json()
        assert len(body["items"]) == 1


class TestCollectionFiltering:

    async def test_name_filter_matches_substring(self, client):
        token = await _register_and_login(client, "cf1@test.com")
        ws_id = await _make_workspace(client, token)
        await _make_collection(client, token, ws_id, "Auth APIs")
        await _make_collection(client, token, ws_id, "Payment APIs")
        await _make_collection(client, token, ws_id, "Admin Panel")

        res = await client.get(
            f"/workspaces/{ws_id}/collections?name=APIs",
            headers=_h(token),
        )
        body = res.json()
        assert body["total"] == 2
        assert all("APIs" in c["name"] for c in body["items"])

    async def test_name_filter_case_insensitive(self, client):
        token = await _register_and_login(client, "cf2@test.com")
        ws_id = await _make_workspace(client, token)
        await _make_collection(client, token, ws_id, "User Service")

        res = await client.get(
            f"/workspaces/{ws_id}/collections?name=user",
            headers=_h(token),
        )
        assert res.json()["total"] == 1

    async def test_name_filter_no_match_returns_empty(self, client):
        token = await _register_and_login(client, "cf3@test.com")
        ws_id = await _make_workspace(client, token)
        await _make_collection(client, token, ws_id, "Something")

        res = await client.get(
            f"/workspaces/{ws_id}/collections?name=xyz",
            headers=_h(token),
        )
        assert res.json()["total"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# Requests
# ══════════════════════════════════════════════════════════════════════════════

class TestRequestCRUD:

    async def test_create_request_defaults(self, client):
        token = await _register_and_login(client, "rc1@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)

        res = await client.post(
            f"/collections/{col_id}/requests",
            json={"name": "List Users", "method": "GET", "url": "https://api.example.com/users"},
            headers=_h(token),
        )
        assert res.status_code == 201
        body = res.json()
        assert body["name"] == "List Users"
        assert body["method"] == "GET"
        assert body["url"] == "https://api.example.com/users"
        assert body["body_type"] == "none"
        assert body["auth_type"] == "none"
        assert body["timeout_ms"] == 30_000
        assert body["headers"] == {}
        assert body["assertions"] == []

    async def test_create_request_with_all_fields(self, client):
        token = await _register_and_login(client, "rc2@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)

        payload = {
            "name": "Create User",
            "method": "POST",
            "url": "https://api.example.com/users",
            "headers": {"X-Custom": "value"},
            "body": '{"name": "Alice"}',
            "body_type": "json",
            "auth_type": "bearer",
            "auth_config": {"token": "{{env.TOKEN}}"},
            "timeout_ms": 10_000,
        }
        res = await client.post(
            f"/collections/{col_id}/requests",
            json=payload,
            headers=_h(token),
        )
        assert res.status_code == 201
        body = res.json()
        assert body["method"] == "POST"
        assert body["headers"] == {"X-Custom": "value"}
        assert body["body"] == '{"name": "Alice"}'
        assert body["auth_type"] == "bearer"

    async def test_list_requests_ordered_by_order_index(self, client):
        token = await _register_and_login(client, "rl1@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)

        # Create three requests — order_index auto-assigned as 1, 2, 3
        await _make_request(client, token, col_id, name="First")
        await _make_request(client, token, col_id, name="Second")
        await _make_request(client, token, col_id, name="Third")

        res = await client.get(f"/collections/{col_id}/requests", headers=_h(token))
        assert res.status_code == 200
        names = [r["name"] for r in res.json()]
        assert names == ["First", "Second", "Third"]

    async def test_get_request_returns_detail(self, client):
        token = await _register_and_login(client, "rg1@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        req_id = await _make_request(client, token, col_id)

        res = await client.get(f"/requests/{req_id}", headers=_h(token))
        assert res.status_code == 200
        body = res.json()
        assert "assertions" in body
        assert "headers" in body
        assert "auth_config" in body

    async def test_update_method_and_url(self, client):
        token = await _register_and_login(client, "ru1@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        req_id = await _make_request(client, token, col_id)

        res = await client.patch(
            f"/requests/{req_id}",
            json={"method": "POST", "url": "https://api.example.com/create"},
            headers=_h(token),
        )
        assert res.status_code == 200
        body = res.json()
        assert body["method"] == "POST"
        assert body["url"] == "https://api.example.com/create"

    async def test_update_headers_replaces_headers(self, client):
        token = await _register_and_login(client, "ru2@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        req_id = await _make_request(client, token, col_id)

        res = await client.patch(
            f"/requests/{req_id}",
            json={"headers": {"Accept": "application/json"}},
            headers=_h(token),
        )
        assert res.status_code == 200
        assert res.json()["headers"] == {"Accept": "application/json"}

    async def test_delete_request(self, client):
        token = await _register_and_login(client, "rd1@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        req_id = await _make_request(client, token, col_id)

        res = await client.delete(f"/requests/{req_id}", headers=_h(token))
        assert res.status_code == 204

        res = await client.get(f"/requests/{req_id}", headers=_h(token))
        assert res.status_code == 404

    async def test_order_index_auto_increments(self, client):
        token = await _register_and_login(client, "ro1@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)

        r1 = (await client.post(
            f"/collections/{col_id}/requests",
            json={"name": "R1", "method": "GET", "url": "https://a.com"},
            headers=_h(token),
        )).json()
        r2 = (await client.post(
            f"/collections/{col_id}/requests",
            json={"name": "R2", "method": "GET", "url": "https://b.com"},
            headers=_h(token),
        )).json()
        assert r2["order_index"] > r1["order_index"]


class TestRequestValidation:

    async def test_blank_name_rejected(self, client):
        token = await _register_and_login(client, "rv1@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        res = await client.post(
            f"/collections/{col_id}/requests",
            json={"name": "  ", "method": "GET", "url": "https://api.com"},
            headers=_h(token),
        )
        assert res.status_code == 422

    async def test_invalid_method_rejected(self, client):
        token = await _register_and_login(client, "rv2@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        res = await client.post(
            f"/collections/{col_id}/requests",
            json={"name": "Bad", "method": "FETCH", "url": "https://api.com"},
            headers=_h(token),
        )
        assert res.status_code == 422

    async def test_timeout_too_short_rejected(self, client):
        token = await _register_and_login(client, "rv3@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        res = await client.post(
            f"/collections/{col_id}/requests",
            json={"name": "T", "method": "GET", "url": "https://a.com", "timeout_ms": 50},
            headers=_h(token),
        )
        assert res.status_code == 422

    async def test_empty_patch_rejected(self, client):
        token = await _register_and_login(client, "rv4@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        req_id = await _make_request(client, token, col_id)
        res = await client.patch(f"/requests/{req_id}", json={}, headers=_h(token))
        assert res.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# Assertions
# ══════════════════════════════════════════════════════════════════════════════

class TestAssertionCRUD:

    async def test_create_status_code_assertion(self, client):
        token = await _register_and_login(client, "ac1@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        req_id = await _make_request(client, token, col_id)

        res = await client.post(
            f"/requests/{req_id}/assertions",
            json={"type": "status_code", "operator": "eq", "expected_value": "200"},
            headers=_h(token),
        )
        assert res.status_code == 201
        body = res.json()
        assert body["type"] == "status_code"
        assert body["operator"] == "eq"
        assert body["expected_value"] == "200"
        assert body["request_id"] == req_id

    async def test_create_json_path_assertion(self, client):
        token = await _register_and_login(client, "ac2@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        req_id = await _make_request(client, token, col_id)

        res = await client.post(
            f"/requests/{req_id}/assertions",
            json={
                "type": "json_path",
                "operator": "eq",
                "expected_value": "active",
                "path": "$.status",
            },
            headers=_h(token),
        )
        assert res.status_code == 201
        assert res.json()["path"] == "$.status"

    async def test_json_path_without_path_field_rejected(self, client):
        token = await _register_and_login(client, "ac3@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        req_id = await _make_request(client, token, col_id)

        res = await client.post(
            f"/requests/{req_id}/assertions",
            json={"type": "json_path", "operator": "eq", "expected_value": "x"},
            headers=_h(token),
        )
        assert res.status_code == 422

    async def test_assertion_visible_in_request_detail(self, client):
        token = await _register_and_login(client, "ac4@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        req_id = await _make_request(client, token, col_id)
        await _make_assertion(client, token, req_id)

        res = await client.get(f"/requests/{req_id}", headers=_h(token))
        assert len(res.json()["assertions"]) == 1

    async def test_update_assertion(self, client):
        token = await _register_and_login(client, "au1@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        req_id = await _make_request(client, token, col_id)
        a_id = await _make_assertion(client, token, req_id)

        res = await client.patch(
            f"/assertions/{a_id}",
            json={"expected_value": "201"},
            headers=_h(token),
        )
        assert res.status_code == 200
        assert res.json()["expected_value"] == "201"

    async def test_delete_assertion(self, client):
        token = await _register_and_login(client, "ad1@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        req_id = await _make_request(client, token, col_id)
        a_id = await _make_assertion(client, token, req_id)

        res = await client.delete(f"/assertions/{a_id}", headers=_h(token))
        assert res.status_code == 204

        res = await client.get(f"/requests/{req_id}", headers=_h(token))
        assert res.json()["assertions"] == []


# ══════════════════════════════════════════════════════════════════════════════
# Auth enforcement
# ══════════════════════════════════════════════════════════════════════════════

class TestAuthRequired:

    async def _setup(self, client):
        token = await _register_and_login(client, "ar@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        req_id = await _make_request(client, token, col_id)
        a_id = await _make_assertion(client, token, req_id)
        return ws_id, col_id, req_id, a_id

    async def test_list_collections_no_auth(self, client):
        ws_id, *_ = await self._setup(client)
        assert (await client.get(f"/workspaces/{ws_id}/collections")).status_code == 403

    async def test_create_collection_no_auth(self, client):
        ws_id, *_ = await self._setup(client)
        res = await client.post(f"/workspaces/{ws_id}/collections", json={"name": "X"})
        assert res.status_code == 403

    async def test_get_collection_no_auth(self, client):
        _, col_id, *_ = await self._setup(client)
        assert (await client.get(f"/collections/{col_id}")).status_code == 403

    async def test_update_collection_no_auth(self, client):
        _, col_id, *_ = await self._setup(client)
        assert (await client.patch(f"/collections/{col_id}", json={"name": "Y"})).status_code == 403

    async def test_delete_collection_no_auth(self, client):
        _, col_id, *_ = await self._setup(client)
        assert (await client.delete(f"/collections/{col_id}")).status_code == 403

    async def test_create_request_no_auth(self, client):
        _, col_id, *_ = await self._setup(client)
        res = await client.post(
            f"/collections/{col_id}/requests",
            json={"name": "X", "method": "GET", "url": "https://a.com"},
        )
        assert res.status_code == 403

    async def test_get_request_no_auth(self, client):
        _, _, req_id, _ = await self._setup(client)
        assert (await client.get(f"/requests/{req_id}")).status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# Cross-user ownership isolation
# ══════════════════════════════════════════════════════════════════════════════

class TestOwnership:

    async def test_user_cannot_list_other_user_collections(self, client):
        owner = await _register_and_login(client, "own1@test.com")
        other = await _register_and_login(client, "oth1@test.com")
        ws_id = await _make_workspace(client, owner)
        await _make_collection(client, owner, ws_id)

        res = await client.get(f"/workspaces/{ws_id}/collections", headers=_h(other))
        assert res.status_code == 404   # workspace not visible to other user

    async def test_user_cannot_get_other_user_collection(self, client):
        owner = await _register_and_login(client, "own2@test.com")
        other = await _register_and_login(client, "oth2@test.com")
        ws_id = await _make_workspace(client, owner)
        col_id = await _make_collection(client, owner, ws_id)

        res = await client.get(f"/collections/{col_id}", headers=_h(other))
        assert res.status_code == 404

    async def test_user_cannot_update_other_user_collection(self, client):
        owner = await _register_and_login(client, "own3@test.com")
        other = await _register_and_login(client, "oth3@test.com")
        ws_id = await _make_workspace(client, owner)
        col_id = await _make_collection(client, owner, ws_id)

        res = await client.patch(
            f"/collections/{col_id}",
            json={"name": "Hijacked"},
            headers=_h(other),
        )
        assert res.status_code == 404

    async def test_user_cannot_delete_other_user_collection(self, client):
        owner = await _register_and_login(client, "own4@test.com")
        other = await _register_and_login(client, "oth4@test.com")
        ws_id = await _make_workspace(client, owner)
        col_id = await _make_collection(client, owner, ws_id)

        res = await client.delete(f"/collections/{col_id}", headers=_h(other))
        assert res.status_code == 404

    async def test_user_cannot_get_other_user_request(self, client):
        owner = await _register_and_login(client, "own5@test.com")
        other = await _register_and_login(client, "oth5@test.com")
        ws_id = await _make_workspace(client, owner)
        col_id = await _make_collection(client, owner, ws_id)
        req_id = await _make_request(client, owner, col_id)

        res = await client.get(f"/requests/{req_id}", headers=_h(other))
        assert res.status_code == 404

    async def test_user_cannot_add_request_to_other_user_collection(self, client):
        owner = await _register_and_login(client, "own6@test.com")
        other = await _register_and_login(client, "oth6@test.com")
        ws_id = await _make_workspace(client, owner)
        col_id = await _make_collection(client, owner, ws_id)

        res = await client.post(
            f"/collections/{col_id}/requests",
            json={"name": "Inject", "method": "GET", "url": "https://evil.com"},
            headers=_h(other),
        )
        assert res.status_code == 404
