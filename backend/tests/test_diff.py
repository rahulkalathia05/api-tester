"""
Diff service tests.

Structure:
  TestDiffEngine   — pure unit tests on the diff helpers (no DB, no HTTP)
  TestDiffEndpoint — POST /results/diff via HTTP
  TestDiffHistory  — GET /requests/{id}/history
  TestDiffAuth     — endpoints require bearer token
  TestDiffOwnership — cross-user isolation
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from app.services.diff_service import (
    _diff_body,
    _diff_headers,
    _diff_schema,
    _diff_status,
    _diff_timing,
    _json_diff,
)

pytestmark = pytest.mark.asyncio


# ── Engine helpers ────────────────────────────────────────────────────────────

def _result(
    response_status=200,
    response_time_ms=100,
    headers=None,
    body=None,
    status="passed",
):
    r = MagicMock()
    r.id = "r1"
    r.status = status
    r.response_status = response_status
    r.response_time_ms = response_time_ms
    r.response_headers = headers if headers is not None else {"content-type": "application/json"}
    r.response_body = body
    r.request_snapshot = {"name": "R", "method": "GET", "url": "https://a.com"}
    r.executed_at = datetime.now(timezone.utc)
    return r


# ── Helpers for HTTP tests ────────────────────────────────────────────────────

async def _register(client, email: str) -> str:
    r = await client.post(
        "/auth/register",
        json={"name": "T", "email": email, "password": "Password1"},
    )
    return r.json()["access_token"]


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_result(client, token: str, mock_body: str = '{"id":1}',
                       mock_status: int = 200) -> str:
    from app.services.runner_service import HttpResult
    h = _h(token)
    ws  = (await client.post("/workspaces", json={"name": "W"}, headers=h)).json()["id"]
    col = (await client.post(f"/workspaces/{ws}/collections",
                             json={"name": "C"}, headers=h)).json()["id"]
    req = (await client.post(f"/collections/{col}/requests",
                             json={"name": "R", "method": "GET",
                                   "url": "https://api.example.com/users"},
                             headers=h)).json()["id"]
    mock_result = HttpResult(
        status_code=mock_status,
        headers={"content-type": "application/json"},
        body=mock_body,
        response_time_ms=50,
        error=None,
    )
    with patch("app.services.runner_service.execute_http", return_value=mock_result):
        r = await client.post(f"/requests/{req}/run", json={}, headers=h)
    return r.json()["id"], req  # (result_id, request_id)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Pure engine tests
# ══════════════════════════════════════════════════════════════════════════════

class TestDiffEngine:

    # ── JSON diff ──────────────────────────────────────────────────────────────

    def test_identical_objects_no_changes(self):
        assert _json_diff({"a": 1}, {"a": 1}) == []

    def test_changed_value(self):
        [c] = _json_diff({"a": 1}, {"a": 2})
        assert c.path == "$.a"
        assert c.from_value == "1"
        assert c.to_value == "2"
        assert c.change_type == "changed"

    def test_added_key(self):
        [c] = _json_diff({}, {"x": "new"})
        assert c.change_type == "added"
        assert c.from_value is None
        assert "new" in c.to_value        # raw string value

    def test_removed_key(self):
        [c] = _json_diff({"x": "old"}, {})
        assert c.change_type == "removed"
        assert "old" in c.from_value      # raw string value
        assert c.to_value is None

    def test_nested_change(self):
        a = {"user": {"name": "Alice", "age": 30}}
        b = {"user": {"name": "Bob",   "age": 30}}
        [c] = _json_diff(a, b)
        assert c.path == "$.user.name"
        assert c.change_type == "changed"

    def test_nested_added_key(self):
        a = {"user": {"name": "Alice"}}
        b = {"user": {"name": "Alice", "email": "a@b.com"}}
        [c] = _json_diff(a, b)
        assert c.path == "$.user.email"
        assert c.change_type == "added"

    def test_array_added_element(self):
        [c] = _json_diff([1, 2], [1, 2, 3])
        assert c.path == "$[2]"
        assert c.change_type == "added"

    def test_array_removed_element(self):
        [c] = _json_diff([1, 2, 3], [1, 2])
        assert c.path == "$[2]"
        assert c.change_type == "removed"

    def test_array_changed_element(self):
        [c] = _json_diff([1, 2], [1, 99])
        assert c.path == "$[1]"
        assert c.change_type == "changed"

    def test_type_change_reported(self):
        [c] = _json_diff({"x": 1}, {"x": "1"})
        # int 1 vs string "1" — not numerically equal so changed
        assert c.change_type == "changed"

    def test_bool_vs_int(self):
        # In JSON, true != 1 as Python values but json.loads might parse differently
        [c] = _json_diff({"active": True}, {"active": False})
        assert c.change_type == "changed"

    def test_null_to_value(self):
        [c] = _json_diff({"x": None}, {"x": "hello"})
        assert c.change_type == "changed"

    def test_empty_object_to_populated(self):
        changes = _json_diff({}, {"a": 1, "b": 2})
        assert len(changes) == 2
        assert all(c.change_type == "added" for c in changes)

    def test_jsonpath_addresses_correct(self):
        a = {"data": {"items": [{"id": 1}]}}
        b = {"data": {"items": [{"id": 2}]}}
        [c] = _json_diff(a, b)
        assert c.path == "$.data.items[0].id"

    # ── Status diff ────────────────────────────────────────────────────────────

    def test_identical_status_no_change(self):
        s = _diff_status(_result(200), _result(200))
        assert not s.has_changes

    def test_changed_status(self):
        s = _diff_status(_result(200), _result(404))
        assert s.has_changes
        assert len(s.changes) == 1
        assert s.changes[0].from_value == "200"
        assert s.changes[0].to_value == "404"

    def test_status_summary_includes_codes(self):
        s = _diff_status(_result(200), _result(500))
        assert "200" in s.summary and "500" in s.summary

    # ── Timing diff ────────────────────────────────────────────────────────────

    def test_identical_timing_no_change(self):
        t = _diff_timing(_result(response_time_ms=100), _result(response_time_ms=100))
        assert not t.has_changes

    def test_slower_timing(self):
        t = _diff_timing(_result(response_time_ms=100), _result(response_time_ms=600))
        assert t.has_changes
        assert "slower" in t.summary

    def test_faster_timing(self):
        t = _diff_timing(_result(response_time_ms=600), _result(response_time_ms=100))
        assert "faster" in t.summary

    # ── Header diff ────────────────────────────────────────────────────────────

    def test_identical_headers_no_change(self):
        h = _diff_headers(
            _result(headers={"content-type": "application/json"}),
            _result(headers={"content-type": "application/json"}),
        )
        assert not h.has_changes

    def test_added_header(self):
        h = _diff_headers(
            _result(headers={}),
            _result(headers={"x-rate-limit": "100"}),
        )
        assert h.has_changes
        assert h.changes[0].change_type == "added"

    def test_removed_header(self):
        h = _diff_headers(
            _result(headers={"x-old": "val"}),
            _result(headers={}),
        )
        assert h.changes[0].change_type == "removed"

    def test_changed_header_value(self):
        h = _diff_headers(
            _result(headers={"content-type": "application/json"}),
            _result(headers={"content-type": "text/plain"}),
        )
        assert h.has_changes
        assert h.changes[0].change_type == "changed"

    def test_header_case_insensitive(self):
        # Both should normalise to lowercase
        h = _diff_headers(
            _result(headers={"Content-Type": "application/json"}),
            _result(headers={"content-type": "application/json"}),
        )
        assert not h.has_changes

    # ── Body diff ──────────────────────────────────────────────────────────────

    def test_identical_body_no_change(self):
        b = _diff_body(
            _result(body='{"id": 1}'),
            _result(body='{"id": 1}'),
        )
        assert not b.has_changes

    def test_changed_field(self):
        b = _diff_body(
            _result(body='{"id": 1, "name": "Alice"}'),
            _result(body='{"id": 1, "name": "Bob"}'),
        )
        assert b.has_changes
        assert any(c.path == "$.name" for c in b.changes)

    def test_added_field(self):
        b = _diff_body(
            _result(body='{"id": 1}'),
            _result(body='{"id": 1, "email": "a@b.com"}'),
        )
        assert b.has_changes
        assert b.changes[0].change_type == "added"

    def test_non_json_body_changed(self):
        b = _diff_body(
            _result(body="old text"),
            _result(body="new text"),
        )
        assert b.has_changes

    def test_empty_bodies_identical(self):
        b = _diff_body(_result(body=None), _result(body=None))
        assert not b.has_changes

    def test_summary_count(self):
        b = _diff_body(
            _result(body='{"a": 1, "b": 2}'),
            _result(body='{"a": 9, "b": 9}'),
        )
        assert "2 field change" in b.summary

    # ── Schema diff ────────────────────────────────────────────────────────────

    def test_identical_schema_no_change(self):
        s = _diff_schema(
            _result(body='{"id": 1, "name": "Alice"}'),
            _result(body='{"id": 2, "name": "Bob"}'),   # values differ but types same
        )
        assert not s.has_changes

    def test_type_change_detected(self):
        s = _diff_schema(
            _result(body='{"id": 1}'),     # id is int
            _result(body='{"id": "abc"}'),  # id is now str
        )
        assert s.has_changes
        assert any(c.path == "$.id" for c in s.changes)

    def test_new_field_detected(self):
        s = _diff_schema(
            _result(body='{"id": 1}'),
            _result(body='{"id": 1, "email": "a@b.com"}'),
        )
        assert s.has_changes
        assert any(c.change_type == "added" for c in s.changes)

    def test_removed_field_detected(self):
        s = _diff_schema(
            _result(body='{"id": 1, "deprecated": true}'),
            _result(body='{"id": 1}'),
        )
        assert any(c.change_type == "removed" for c in s.changes)

    def test_no_json_returns_no_schema(self):
        s = _diff_schema(_result(body=None), _result(body=None))
        assert not s.has_changes


# ══════════════════════════════════════════════════════════════════════════════
# 2. Diff endpoint — POST /results/diff
# ══════════════════════════════════════════════════════════════════════════════

class TestDiffEndpoint:

    async def test_diff_identical_results(self, client):
        token = await _register(client, "di1@test.com")
        rid_a, _ = await _make_result(client, token, '{"id": 1}')
        rid_b, _ = await _make_result(client, token, '{"id": 1}')

        r = await client.post("/results/diff",
                              json={"result_id_a": rid_a, "result_id_b": rid_b},
                              headers=_h(token))
        assert r.status_code == 200
        b = r.json()
        assert b["is_identical"] is True
        assert b["total_changes"] == 0

    async def test_diff_different_status_codes(self, client):
        token = await _register(client, "di2@test.com")
        rid_a, _ = await _make_result(client, token, '{"ok": true}', 200)
        rid_b, _ = await _make_result(client, token, '{"error": "not found"}', 404)

        r = await client.post("/results/diff",
                              json={"result_id_a": rid_a, "result_id_b": rid_b},
                              headers=_h(token))
        b = r.json()
        assert b["is_identical"] is False
        status_sec = next(s for s in b["sections"] if s["section"] == "status")
        assert status_sec["has_changes"] is True
        assert status_sec["changes"][0]["from_value"] == "200"
        assert status_sec["changes"][0]["to_value"] == "404"

    async def test_diff_body_field_changed(self, client):
        token = await _register(client, "di3@test.com")
        rid_a, _ = await _make_result(client, token, '{"id": 1, "name": "Alice"}')
        rid_b, _ = await _make_result(client, token, '{"id": 1, "name": "Bob"}')

        r = await client.post("/results/diff",
                              json={"result_id_a": rid_a, "result_id_b": rid_b},
                              headers=_h(token))
        b = r.json()
        body_sec = next(s for s in b["sections"] if s["section"] == "body")
        assert body_sec["has_changes"] is True
        change = next(c for c in body_sec["changes"] if c["path"] == "$.name")
        assert "Alice" in change["from_value"]
        assert "Bob" in change["to_value"]

    async def test_diff_schema_section_present(self, client):
        token = await _register(client, "di4@test.com")
        rid_a, _ = await _make_result(client, token, '{"id": 1}')
        rid_b, _ = await _make_result(client, token, '{"id": "abc"}')

        r = await client.post("/results/diff",
                              json={"result_id_a": rid_a, "result_id_b": rid_b},
                              headers=_h(token))
        sections = {s["section"] for s in r.json()["sections"]}
        assert {"status", "timing", "headers", "body", "schema"} == sections

    async def test_diff_response_has_snapshots(self, client):
        token = await _register(client, "di5@test.com")
        rid_a, _ = await _make_result(client, token)
        rid_b, _ = await _make_result(client, token)

        r = await client.post("/results/diff",
                              json={"result_id_a": rid_a, "result_id_b": rid_b},
                              headers=_h(token))
        b = r.json()
        assert b["a"]["result_id"] == rid_a
        assert b["b"]["result_id"] == rid_b
        assert "executed_at" in b["a"]
        assert "request_method" in b["a"]

    async def test_diff_same_id_rejected(self, client):
        token = await _register(client, "di6@test.com")
        rid, _ = await _make_result(client, token)
        r = await client.post("/results/diff",
                              json={"result_id_a": rid, "result_id_b": rid},
                              headers=_h(token))
        assert r.status_code == 422

    async def test_diff_unknown_result_returns_404(self, client):
        token = await _register(client, "di7@test.com")
        rid, _ = await _make_result(client, token)
        r = await client.post("/results/diff",
                              json={"result_id_a": rid, "result_id_b": "nonexistent"},
                              headers=_h(token))
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 3. Request history endpoint
# ══════════════════════════════════════════════════════════════════════════════

class TestDiffHistory:

    async def test_history_returns_recent_results(self, client):
        token = await _register(client, "dh1@test.com")
        rid1, req_id = await _make_result(client, token)
        rid2, _      = await _make_result(client, token)   # same request... wait

        # Actually _make_result creates a new request each time.
        # We need to run the same request twice.
        from app.services.runner_service import HttpResult
        h = _h(token)
        ws  = (await client.post("/workspaces", json={"name": "W2"}, headers=h)).json()["id"]
        col = (await client.post(f"/workspaces/{ws}/collections",
                                 json={"name": "C"}, headers=h)).json()["id"]
        req = (await client.post(f"/collections/{col}/requests",
                                 json={"name": "R", "method": "GET",
                                       "url": "https://api.example.com/users"},
                                 headers=h)).json()["id"]
        mock = HttpResult(status_code=200, headers={}, body='{"n":1}',
                          response_time_ms=50, error=None)
        with patch("app.services.runner_service.execute_http", return_value=mock):
            await client.post(f"/requests/{req}/run", json={}, headers=h)
        with patch("app.services.runner_service.execute_http", return_value=mock):
            await client.post(f"/requests/{req}/run", json={}, headers=h)

        r = await client.get(f"/requests/{req}/history", headers=h)
        assert r.status_code == 200
        assert len(r.json()) == 2

    async def test_history_returns_correct_fields(self, client):
        token = await _register(client, "dh2@test.com")
        from app.services.runner_service import HttpResult
        h = _h(token)
        ws  = (await client.post("/workspaces", json={"name": "W"}, headers=h)).json()["id"]
        col = (await client.post(f"/workspaces/{ws}/collections",
                                 json={"name": "C"}, headers=h)).json()["id"]
        req = (await client.post(f"/collections/{col}/requests",
                                 json={"name": "R", "method": "GET",
                                       "url": "https://api.example.com"},
                                 headers=h)).json()["id"]
        mock = HttpResult(status_code=201, headers={}, body='{}',
                          response_time_ms=20, error=None)
        with patch("app.services.runner_service.execute_http", return_value=mock):
            await client.post(f"/requests/{req}/run", json={}, headers=h)

        r = await client.get(f"/requests/{req}/history", headers=h)
        item = r.json()[0]
        assert item["status"] in ("passed", "failed", "error")
        assert item["response_status"] == 201
        assert "executed_at" in item

    async def test_history_empty_for_new_request(self, client):
        token = await _register(client, "dh3@test.com")
        h = _h(token)
        ws  = (await client.post("/workspaces", json={"name": "W"}, headers=h)).json()["id"]
        col = (await client.post(f"/workspaces/{ws}/collections",
                                 json={"name": "C"}, headers=h)).json()["id"]
        req = (await client.post(f"/collections/{col}/requests",
                                 json={"name": "R", "method": "GET",
                                       "url": "https://api.example.com"},
                                 headers=h)).json()["id"]
        r = await client.get(f"/requests/{req}/history", headers=h)
        assert r.json() == []


# ══════════════════════════════════════════════════════════════════════════════
# 4. Auth enforcement
# ══════════════════════════════════════════════════════════════════════════════

class TestDiffAuth:

    async def test_diff_requires_auth(self, client):
        r = await client.post("/results/diff",
                              json={"result_id_a": "a", "result_id_b": "b"})
        assert r.status_code == 403

    async def test_history_requires_auth(self, client):
        r = await client.get("/requests/any-id/history")
        assert r.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# 5. Cross-user ownership
# ══════════════════════════════════════════════════════════════════════════════

class TestDiffOwnership:

    async def test_other_user_cannot_diff(self, client):
        owner = await _register(client, "own_d1@test.com")
        other = await _register(client, "oth_d1@test.com")
        rid_a, _ = await _make_result(client, owner)
        rid_b, _ = await _make_result(client, owner)

        r = await client.post("/results/diff",
                              json={"result_id_a": rid_a, "result_id_b": rid_b},
                              headers=_h(other))
        assert r.status_code == 404

    async def test_cross_user_results_rejected(self, client):
        user1 = await _register(client, "own_d2@test.com")
        user2 = await _register(client, "oth_d2@test.com")
        rid1, _ = await _make_result(client, user1)
        rid2, _ = await _make_result(client, user2)

        # user1 tries to diff their result with user2's result
        r = await client.post("/results/diff",
                              json={"result_id_a": rid1, "result_id_b": rid2},
                              headers=_h(user1))
        assert r.status_code == 404
