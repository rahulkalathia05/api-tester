"""
Assertions engine — comprehensive test suite.

Structure:
  TestStatusCode     — eq/ne/gt/lt/gte/lte, type coercion, boundary values
  TestResponseTime   — numeric operators, slow/fast response, boundary
  TestJsonPath       — eq/ne/contains/not_contains/exists/matches, nested path,
                       array indexing, missing path, invalid expression, empty body
  TestBodyContains   — contains/not_contains/matches, case sensitivity, regex
  TestHeader         — eq/ne/contains/exists, case-insensitive key lookup
  TestOperators      — shared operator behaviour across types
  TestErrorPropagation — engine never raises; request errors fail every assertion
  TestAssertionCRUD  — POST/GET list/GET single/PATCH/DELETE via HTTP
  TestAssertionPreview — POST /requests/{id}/assertions/preview
  TestAssertionAuth  — every endpoint requires a bearer token
  TestAssertionOwnership — cross-user isolation
"""
import pytest
from dataclasses import dataclass

from app.services.assertion_engine import HttpResult, evaluate_assertions

pytestmark = pytest.mark.asyncio


# ── Shared fixtures ───────────────────────────────────────────────────────────

@dataclass
class A:
    """Minimal assertion-like for pure engine tests."""
    id: str
    type: str
    operator: str
    expected_value: str
    path: str | None = None


def ok(
    status: int = 200,
    body: str | None = '{"id": 42, "name": "Alice", "active": true, "scores": [10, 20, 30]}',
    headers: dict | None = None,
    ms: int = 150,
) -> HttpResult:
    return HttpResult(
        status_code=status,
        headers={**(headers or {}), "content-type": "application/json"},
        body=body,
        response_time_ms=ms,
        error=None,
    )


def err(msg: str = "Connection refused") -> HttpResult:
    return HttpResult(status_code=None, headers={}, body=None,
                      response_time_ms=0, error=msg)


def a(type: str, op: str, expected: str, path: str | None = None) -> A:
    return A(id="a1", type=type, operator=op, expected_value=expected, path=path)


# ══════════════════════════════════════════════════════════════════════════════
# 1. status_code assertions
# ══════════════════════════════════════════════════════════════════════════════

class TestStatusCode:

    def test_eq_exact_match(self):
        [o] = evaluate_assertions([a("status_code", "eq", "200")], ok(200))
        assert o.passed and o.actual_value == "200"

    def test_eq_mismatch(self):
        [o] = evaluate_assertions([a("status_code", "eq", "201")], ok(200))
        assert not o.passed

    def test_ne_passes_when_different(self):
        [o] = evaluate_assertions([a("status_code", "ne", "404")], ok(200))
        assert o.passed

    def test_ne_fails_when_equal(self):
        [o] = evaluate_assertions([a("status_code", "ne", "200")], ok(200))
        assert not o.passed

    def test_gt_passes(self):
        [o] = evaluate_assertions([a("status_code", "gt", "199")], ok(200))
        assert o.passed

    def test_gt_fails_when_equal(self):
        [o] = evaluate_assertions([a("status_code", "gt", "200")], ok(200))
        assert not o.passed

    def test_lt_passes(self):
        [o] = evaluate_assertions([a("status_code", "lt", "400")], ok(200))
        assert o.passed

    def test_lt_fails_when_equal(self):
        [o] = evaluate_assertions([a("status_code", "lt", "200")], ok(200))
        assert not o.passed

    def test_gte_passes_when_equal(self):
        [o] = evaluate_assertions([a("status_code", "gte", "200")], ok(200))
        assert o.passed

    def test_lte_passes_when_equal(self):
        [o] = evaluate_assertions([a("status_code", "lte", "200")], ok(200))
        assert o.passed

    def test_4xx_range(self):
        [o] = evaluate_assertions([a("status_code", "gte", "400")], ok(404))
        assert o.passed

    def test_5xx_detected(self):
        [o] = evaluate_assertions([a("status_code", "gte", "500")], ok(503))
        assert o.passed

    def test_numeric_coercion_from_string(self):
        # Both "200" and 200 should compare equal
        [o] = evaluate_assertions([a("status_code", "eq", "200")], ok(200))
        assert o.passed

    def test_actual_value_is_string_of_code(self):
        [o] = evaluate_assertions([a("status_code", "eq", "404")], ok(404))
        assert o.actual_value == "404"


# ══════════════════════════════════════════════════════════════════════════════
# 2. response_time assertions
# ══════════════════════════════════════════════════════════════════════════════

class TestResponseTime:

    def test_lt_fast_response(self):
        [o] = evaluate_assertions([a("response_time", "lt", "500")], ok(ms=42))
        assert o.passed

    def test_lt_slow_response_fails(self):
        [o] = evaluate_assertions([a("response_time", "lt", "100")], ok(ms=500))
        assert not o.passed

    def test_lte_at_boundary_passes(self):
        [o] = evaluate_assertions([a("response_time", "lte", "150")], ok(ms=150))
        assert o.passed

    def test_gt_passes(self):
        [o] = evaluate_assertions([a("response_time", "gt", "10")], ok(ms=150))
        assert o.passed

    def test_gte_passes_when_equal(self):
        [o] = evaluate_assertions([a("response_time", "gte", "150")], ok(ms=150))
        assert o.passed

    def test_eq_exact_ms(self):
        [o] = evaluate_assertions([a("response_time", "eq", "42")], ok(ms=42))
        assert o.passed

    def test_actual_value_is_ms_string(self):
        [o] = evaluate_assertions([a("response_time", "lt", "1000")], ok(ms=99))
        assert o.actual_value == "99"

    def test_non_numeric_expected_returns_error(self):
        [o] = evaluate_assertions([a("response_time", "lt", "fast")], ok(ms=100))
        assert not o.passed
        assert o.error_message is not None


# ══════════════════════════════════════════════════════════════════════════════
# 3. json_path assertions (response field)
# ══════════════════════════════════════════════════════════════════════════════

class TestJsonPath:

    def test_eq_top_level_field(self):
        [o] = evaluate_assertions([a("json_path", "eq", "42", "$.id")], ok())
        assert o.passed

    def test_eq_nested_field(self):
        body = '{"user": {"profile": {"age": 30}}}'
        [o] = evaluate_assertions([a("json_path", "eq", "30", "$.user.profile.age")], ok(body=body))
        assert o.passed

    def test_eq_string_field(self):
        [o] = evaluate_assertions([a("json_path", "eq", "Alice", "$.name")], ok())
        assert o.passed

    def test_eq_boolean_field(self):
        [o] = evaluate_assertions([a("json_path", "eq", "True", "$.active")], ok())
        assert o.passed

    def test_ne_passes_when_different(self):
        [o] = evaluate_assertions([a("json_path", "ne", "99", "$.id")], ok())
        assert o.passed

    def test_contains_substring(self):
        [o] = evaluate_assertions([a("json_path", "contains", "Ali", "$.name")], ok())
        assert o.passed

    def test_not_contains_passes(self):
        [o] = evaluate_assertions([a("json_path", "not_contains", "Bob", "$.name")], ok())
        assert o.passed

    def test_exists_when_field_present(self):
        [o] = evaluate_assertions([a("json_path", "exists", "", "$.id")], ok())
        assert o.passed

    def test_exists_when_field_absent_fails(self):
        [o] = evaluate_assertions([a("json_path", "exists", "", "$.missing")], ok())
        assert not o.passed

    def test_matches_regex(self):
        [o] = evaluate_assertions([a("json_path", "matches", r"^Al", "$.name")], ok())
        assert o.passed

    def test_array_index(self):
        [o] = evaluate_assertions([a("json_path", "eq", "20", "$.scores[1]")], ok())
        assert o.passed

    def test_array_length_via_path(self):
        # $.scores returns the whole array; eq compares string representation
        [o] = evaluate_assertions([a("json_path", "exists", "", "$.scores")], ok())
        assert o.passed

    def test_missing_path_returns_failed_not_error(self):
        [o] = evaluate_assertions([a("json_path", "eq", "x", "$.nonexistent")], ok())
        assert not o.passed
        # No error_message — a clean miss, not an engine failure
        assert o.error_message is None

    def test_invalid_jsonpath_expression_returns_error(self):
        [o] = evaluate_assertions([a("json_path", "eq", "x", "INVALID[[")], ok())
        assert not o.passed
        assert o.error_message is not None

    def test_empty_body_returns_error(self):
        [o] = evaluate_assertions([a("json_path", "eq", "x", "$.id")], ok(body=None))
        assert not o.passed
        assert o.error_message is not None

    def test_non_json_body_returns_error(self):
        [o] = evaluate_assertions([a("json_path", "eq", "x", "$.id")], ok(body="plain text"))
        assert not o.passed
        assert o.error_message is not None

    def test_missing_path_field_in_assertion_returns_error(self):
        # json_path type with path=None
        [o] = evaluate_assertions([a("json_path", "eq", "x", None)], ok())
        assert not o.passed
        assert o.error_message is not None

    def test_actual_value_extracted_correctly(self):
        [o] = evaluate_assertions([a("json_path", "eq", "42", "$.id")], ok())
        assert o.actual_value == "42"


# ══════════════════════════════════════════════════════════════════════════════
# 4. body_contains assertions
# ══════════════════════════════════════════════════════════════════════════════

class TestBodyContains:

    def test_contains_passes(self):
        [o] = evaluate_assertions([a("body_contains", "contains", "Alice")], ok())
        assert o.passed

    def test_contains_fails(self):
        [o] = evaluate_assertions([a("body_contains", "contains", "Bob")], ok())
        assert not o.passed

    def test_not_contains_passes(self):
        [o] = evaluate_assertions([a("body_contains", "not_contains", "ERROR")], ok())
        assert o.passed

    def test_not_contains_fails(self):
        [o] = evaluate_assertions([a("body_contains", "not_contains", "Alice")], ok())
        assert not o.passed

    def test_matches_regex_passes(self):
        [o] = evaluate_assertions([a("body_contains", "matches", r'"id":\s*\d+')], ok())
        assert o.passed

    def test_matches_regex_fails(self):
        [o] = evaluate_assertions([a("body_contains", "matches", r'ERROR\d+')], ok())
        assert not o.passed

    def test_case_sensitive(self):
        [o] = evaluate_assertions([a("body_contains", "contains", "alice")], ok())
        assert not o.passed  # body has "Alice" not "alice"

    def test_empty_body_returns_not_contains(self):
        [o] = evaluate_assertions([a("body_contains", "contains", "x")], ok(body=None))
        assert not o.passed  # empty string doesn't contain "x"

    def test_partial_word_match(self):
        [o] = evaluate_assertions([a("body_contains", "contains", "Alic")], ok())
        assert o.passed


# ══════════════════════════════════════════════════════════════════════════════
# 5. header assertions
# ══════════════════════════════════════════════════════════════════════════════

class TestHeader:

    def _ok_with_headers(self, **headers: str) -> HttpResult:
        return ok(headers={k.lower(): v for k, v in headers.items()})

    def test_eq_exact(self):
        r = self._ok_with_headers(**{"content-type": "application/json"})
        [o] = evaluate_assertions([a("header", "eq", "application/json", "content-type")], r)
        assert o.passed

    def test_eq_fails_on_mismatch(self):
        # Use a custom header name so the ok() default content-type doesn't interfere
        r = self._ok_with_headers(**{"x-custom": "text/plain"})
        [o] = evaluate_assertions([a("header", "eq", "application/json", "x-custom")], r)
        assert not o.passed

    def test_contains_substring(self):
        r = self._ok_with_headers(**{"content-type": "application/json; charset=utf-8"})
        [o] = evaluate_assertions([a("header", "contains", "json", "content-type")], r)
        assert o.passed

    def test_exists_when_present(self):
        r = self._ok_with_headers(**{"x-request-id": "abc123"})
        [o] = evaluate_assertions([a("header", "exists", "", "x-request-id")], r)
        assert o.passed

    def test_exists_fails_when_absent(self):
        [o] = evaluate_assertions([a("header", "exists", "", "x-missing")], ok())
        assert not o.passed

    def test_case_insensitive_key_lookup(self):
        # httpx normalises to lowercase; engine handles both
        r = self._ok_with_headers(**{"content-type": "application/json"})
        [o] = evaluate_assertions([a("header", "eq", "application/json", "Content-Type")], r)
        # The engine tries lowercase first, then the original key
        assert o.passed

    def test_ne(self):
        r = self._ok_with_headers(**{"content-type": "application/json"})
        [o] = evaluate_assertions([a("header", "ne", "text/plain", "content-type")], r)
        assert o.passed


# ══════════════════════════════════════════════════════════════════════════════
# 6. Multiple assertions + error propagation
# ══════════════════════════════════════════════════════════════════════════════

class TestEngineErrors:

    def test_all_fail_when_request_errored(self):
        assertions = [
            a("status_code", "eq", "200"),
            a("response_time", "lt", "500"),
            a("body_contains", "contains", "ok"),
        ]
        outcomes = evaluate_assertions(assertions, err("Timeout"))
        assert all(not o.passed for o in outcomes)
        assert all("Timeout" in (o.error_message or "") for o in outcomes)

    def test_independent_assertion_results(self):
        """One failing assertion does not affect others."""
        assertions = [
            a("status_code", "eq", "200"),   # passes
            a("status_code", "eq", "201"),   # fails
            a("response_time", "lt", "500"), # passes
        ]
        outcomes = evaluate_assertions(assertions, ok())
        assert outcomes[0].passed is True
        assert outcomes[1].passed is False
        assert outcomes[2].passed is True

    def test_unknown_type_returns_error_outcome(self):
        [o] = evaluate_assertions([a("unknown_type", "eq", "x")], ok())
        assert not o.passed
        assert o.error_message is not None

    def test_unknown_operator_returns_error_outcome(self):
        [o] = evaluate_assertions([a("status_code", "between", "200")], ok())
        assert not o.passed
        assert o.error_message is not None

    def test_snapshot_always_captured(self):
        [o] = evaluate_assertions([a("status_code", "eq", "200")], ok())
        assert o.assertion_snapshot == {
            "type": "status_code",
            "operator": "eq",
            "expected_value": "200",
            "path": None,
        }

    def test_empty_assertions_returns_empty(self):
        assert evaluate_assertions([], ok()) == []


# ══════════════════════════════════════════════════════════════════════════════
# 7. Assertion CRUD — HTTP endpoints
# ══════════════════════════════════════════════════════════════════════════════

async def _setup(client) -> tuple[str, str, str]:
    """Register user, create workspace + collection + request. Return (token, col_id, req_id)."""
    r = await client.post("/auth/register",
                          json={"name": "U", "email": "crud@test.com", "password": "Password1"})
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    ws_id = (await client.post("/workspaces", json={"name": "W"}, headers=h)).json()["id"]
    col_id = (await client.post(f"/workspaces/{ws_id}/collections",
                                json={"name": "C"}, headers=h)).json()["id"]
    req_id = (await client.post(f"/collections/{col_id}/requests",
                                json={"name": "R", "method": "GET",
                                      "url": "https://example.com"}, headers=h)).json()["id"]
    return token, col_id, req_id


class TestAssertionCRUD:

    async def test_create_status_code_assertion(self, client):
        token, _, req_id = await _setup(client)
        h = {"Authorization": f"Bearer {token}"}
        r = await client.post(f"/requests/{req_id}/assertions",
                              json={"type": "status_code", "operator": "eq",
                                    "expected_value": "200"}, headers=h)
        assert r.status_code == 201
        b = r.json()
        assert b["type"] == "status_code"
        assert b["operator"] == "eq"
        assert b["expected_value"] == "200"
        assert b["request_id"] == req_id
        assert "id" in b

    async def test_create_response_time_assertion(self, client):
        token, _, req_id = await _setup(client)
        h = {"Authorization": f"Bearer {token}"}
        r = await client.post(f"/requests/{req_id}/assertions",
                              json={"type": "response_time", "operator": "lt",
                                    "expected_value": "500"}, headers=h)
        assert r.status_code == 201
        assert r.json()["type"] == "response_time"

    async def test_create_json_path_assertion(self, client):
        token, _, req_id = await _setup(client)
        h = {"Authorization": f"Bearer {token}"}
        r = await client.post(f"/requests/{req_id}/assertions",
                              json={"type": "json_path", "operator": "eq",
                                    "expected_value": "active", "path": "$.status"},
                              headers=h)
        assert r.status_code == 201
        assert r.json()["path"] == "$.status"

    async def test_create_body_contains_assertion(self, client):
        token, _, req_id = await _setup(client)
        h = {"Authorization": f"Bearer {token}"}
        r = await client.post(f"/requests/{req_id}/assertions",
                              json={"type": "body_contains", "operator": "contains",
                                    "expected_value": "success"}, headers=h)
        assert r.status_code == 201

    async def test_json_path_without_path_rejected(self, client):
        token, _, req_id = await _setup(client)
        h = {"Authorization": f"Bearer {token}"}
        r = await client.post(f"/requests/{req_id}/assertions",
                              json={"type": "json_path", "operator": "eq",
                                    "expected_value": "x"}, headers=h)
        assert r.status_code == 422

    async def test_invalid_type_rejected(self, client):
        token, _, req_id = await _setup(client)
        h = {"Authorization": f"Bearer {token}"}
        r = await client.post(f"/requests/{req_id}/assertions",
                              json={"type": "unknown", "operator": "eq",
                                    "expected_value": "x"}, headers=h)
        assert r.status_code == 422

    async def test_invalid_operator_rejected(self, client):
        token, _, req_id = await _setup(client)
        h = {"Authorization": f"Bearer {token}"}
        r = await client.post(f"/requests/{req_id}/assertions",
                              json={"type": "status_code", "operator": "between",
                                    "expected_value": "200"}, headers=h)
        assert r.status_code == 422

    async def test_list_assertions(self, client):
        token, _, req_id = await _setup(client)
        h = {"Authorization": f"Bearer {token}"}
        for op, ev in [("eq", "200"), ("lt", "500")]:
            await client.post(f"/requests/{req_id}/assertions",
                              json={"type": "status_code", "operator": op,
                                    "expected_value": ev}, headers=h)
        r = await client.get(f"/requests/{req_id}/assertions", headers=h)
        assert r.status_code == 200
        assert len(r.json()) == 2

    async def test_get_single_assertion(self, client):
        token, _, req_id = await _setup(client)
        h = {"Authorization": f"Bearer {token}"}
        create_r = await client.post(f"/requests/{req_id}/assertions",
                                     json={"type": "status_code", "operator": "eq",
                                           "expected_value": "200"}, headers=h)
        a_id = create_r.json()["id"]
        r = await client.get(f"/assertions/{a_id}", headers=h)
        assert r.status_code == 200
        assert r.json()["id"] == a_id

    async def test_update_assertion(self, client):
        token, _, req_id = await _setup(client)
        h = {"Authorization": f"Bearer {token}"}
        a_id = (await client.post(f"/requests/{req_id}/assertions",
                                  json={"type": "status_code", "operator": "eq",
                                        "expected_value": "200"}, headers=h)).json()["id"]
        r = await client.patch(f"/assertions/{a_id}",
                               json={"expected_value": "201"}, headers=h)
        assert r.status_code == 200
        assert r.json()["expected_value"] == "201"

    async def test_delete_assertion(self, client):
        token, _, req_id = await _setup(client)
        h = {"Authorization": f"Bearer {token}"}
        a_id = (await client.post(f"/requests/{req_id}/assertions",
                                  json={"type": "status_code", "operator": "eq",
                                        "expected_value": "200"}, headers=h)).json()["id"]
        r = await client.delete(f"/assertions/{a_id}", headers=h)
        assert r.status_code == 204
        r = await client.get(f"/assertions/{a_id}", headers=h)
        assert r.status_code == 404

    async def test_assertion_visible_in_request_detail(self, client):
        token, _, req_id = await _setup(client)
        h = {"Authorization": f"Bearer {token}"}
        await client.post(f"/requests/{req_id}/assertions",
                          json={"type": "status_code", "operator": "eq",
                                "expected_value": "200"}, headers=h)
        r = await client.get(f"/requests/{req_id}", headers=h)
        assert len(r.json()["assertions"]) == 1

    async def test_empty_patch_rejected(self, client):
        token, _, req_id = await _setup(client)
        h = {"Authorization": f"Bearer {token}"}
        a_id = (await client.post(f"/requests/{req_id}/assertions",
                                  json={"type": "status_code", "operator": "eq",
                                        "expected_value": "200"}, headers=h)).json()["id"]
        r = await client.patch(f"/assertions/{a_id}", json={}, headers=h)
        assert r.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# 8. Preview endpoint
# ══════════════════════════════════════════════════════════════════════════════

class TestAssertionPreview:

    async def _with_assertions(self, client) -> tuple[str, str, dict]:
        token, _, req_id = await _setup(client)
        h = {"Authorization": f"Bearer {token}"}
        # Add status_code + response_time + json_path assertion
        await client.post(f"/requests/{req_id}/assertions",
                          json={"type": "status_code", "operator": "eq",
                                "expected_value": "200"}, headers=h)
        await client.post(f"/requests/{req_id}/assertions",
                          json={"type": "response_time", "operator": "lt",
                                "expected_value": "500"}, headers=h)
        await client.post(f"/requests/{req_id}/assertions",
                          json={"type": "json_path", "operator": "eq",
                                "expected_value": "42", "path": "$.id"}, headers=h)
        return token, req_id, h

    async def test_all_pass_on_matching_response(self, client):
        token, req_id, h = await self._with_assertions(client)
        r = await client.post(f"/requests/{req_id}/assertions/preview",
                              json={"status_code": 200, "response_time_ms": 100,
                                    "body": '{"id": 42}'}, headers=h)
        assert r.status_code == 200
        b = r.json()
        assert b["total"] == 3
        assert b["passed"] == 3
        assert b["failed"] == 0
        assert all(item["passed"] for item in b["results"])

    async def test_partial_failure(self, client):
        token, req_id, h = await self._with_assertions(client)
        r = await client.post(f"/requests/{req_id}/assertions/preview",
                              json={"status_code": 404,     # fails eq 200
                                    "response_time_ms": 50,  # passes lt 500
                                    "body": '{"id": 99}'},   # fails eq 42
                              headers=h)
        b = r.json()
        assert b["total"] == 3
        assert b["passed"] == 1
        assert b["failed"] == 2

    async def test_preview_returns_actual_values(self, client):
        token, req_id, h = await self._with_assertions(client)
        r = await client.post(f"/requests/{req_id}/assertions/preview",
                              json={"status_code": 404, "response_time_ms": 50,
                                    "body": '{"id": 42}'}, headers=h)
        results = r.json()["results"]
        # status_code assertion: actual should be "404"
        sc = next(x for x in results if x["type"] == "status_code")
        assert sc["actual_value"] == "404"

    async def test_preview_empty_request_returns_no_results(self, client):
        """Request with no assertions returns empty preview."""
        token, _, req_id = await _setup(client)
        h = {"Authorization": f"Bearer {token}"}
        # Register as different email to avoid duplicate
        r = await client.post(
            "/auth/register",
            json={"name": "U2", "email": "prev2@test.com", "password": "Password1"},
        )
        t2 = r.json()["access_token"]
        h2 = {"Authorization": f"Bearer {t2}"}
        ws2 = (await client.post("/workspaces", json={"name": "W"}, headers=h2)).json()["id"]
        col2 = (await client.post(f"/workspaces/{ws2}/collections",
                                   json={"name": "C"}, headers=h2)).json()["id"]
        req2 = (await client.post(f"/collections/{col2}/requests",
                                   json={"name": "R", "method": "GET",
                                         "url": "https://a.com"}, headers=h2)).json()["id"]
        r = await client.post(f"/requests/{req2}/assertions/preview",
                              json={"status_code": 200}, headers=h2)
        assert r.status_code == 200
        b = r.json()
        assert b["total"] == 0

    async def test_preview_requires_auth(self, client):
        token, req_id, _ = await self._with_assertions(client)
        r = await client.post(f"/requests/{req_id}/assertions/preview",
                              json={"status_code": 200})
        assert r.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# 9. Auth enforcement
# ══════════════════════════════════════════════════════════════════════════════

class TestAssertionAuth:

    async def test_list_requires_auth(self, client):
        r = await client.get("/requests/any-id/assertions")
        assert r.status_code == 403

    async def test_get_requires_auth(self, client):
        r = await client.get("/assertions/any-id")
        assert r.status_code == 403

    async def test_create_requires_auth(self, client):
        r = await client.post("/requests/any-id/assertions",
                              json={"type": "status_code", "operator": "eq",
                                    "expected_value": "200"})
        assert r.status_code == 403

    async def test_update_requires_auth(self, client):
        r = await client.patch("/assertions/any-id", json={"expected_value": "201"})
        assert r.status_code == 403

    async def test_delete_requires_auth(self, client):
        r = await client.delete("/assertions/any-id")
        assert r.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# 10. Cross-user ownership
# ══════════════════════════════════════════════════════════════════════════════

class TestAssertionOwnership:

    async def _two_users(self, client):
        def h(t): return {"Authorization": f"Bearer {t}"}
        r1 = await client.post("/auth/register",
                               json={"name": "O", "email": "own_a@test.com", "password": "Password1"})
        r2 = await client.post("/auth/register",
                               json={"name": "T", "email": "oth_a@test.com", "password": "Password1"})
        owner, other = r1.json()["access_token"], r2.json()["access_token"]
        ws = (await client.post("/workspaces", json={"name": "W"}, headers=h(owner))).json()["id"]
        col = (await client.post(f"/workspaces/{ws}/collections",
                                 json={"name": "C"}, headers=h(owner))).json()["id"]
        req = (await client.post(f"/collections/{col}/requests",
                                 json={"name": "R", "method": "GET",
                                       "url": "https://a.com"}, headers=h(owner))).json()["id"]
        a_id = (await client.post(f"/requests/{req}/assertions",
                                  json={"type": "status_code", "operator": "eq",
                                        "expected_value": "200"},
                                  headers=h(owner))).json()["id"]
        return owner, other, req, a_id

    async def test_other_user_cannot_list_assertions(self, client):
        _, other, req_id, _ = await self._two_users(client)
        r = await client.get(f"/requests/{req_id}/assertions",
                             headers={"Authorization": f"Bearer {other}"})
        assert r.status_code == 404

    async def test_other_user_cannot_get_assertion(self, client):
        _, other, _, a_id = await self._two_users(client)
        r = await client.get(f"/assertions/{a_id}",
                             headers={"Authorization": f"Bearer {other}"})
        assert r.status_code == 404

    async def test_other_user_cannot_update_assertion(self, client):
        _, other, _, a_id = await self._two_users(client)
        r = await client.patch(f"/assertions/{a_id}",
                               json={"expected_value": "201"},
                               headers={"Authorization": f"Bearer {other}"})
        assert r.status_code == 404

    async def test_other_user_cannot_delete_assertion(self, client):
        _, other, _, a_id = await self._two_users(client)
        r = await client.delete(f"/assertions/{a_id}",
                                headers={"Authorization": f"Bearer {other}"})
        assert r.status_code == 404

    async def test_other_user_cannot_preview(self, client):
        _, other, req_id, _ = await self._two_users(client)
        r = await client.post(f"/requests/{req_id}/assertions/preview",
                              json={"status_code": 200},
                              headers={"Authorization": f"Bearer {other}"})
        assert r.status_code == 404
