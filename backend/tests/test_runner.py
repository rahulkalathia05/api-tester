"""
API Runner tests.

Structure:
  TestAssertionEngine  — pure unit tests (no DB, no HTTP, no mocks needed)
  TestSingleRun        — POST /requests/{id}/run with mocked httpx
  TestRunHistory       — GET /workspaces/{id}/runs, /runs/{id}, /results/{id}
  TestCollectionRun    — POST /collections/{id}/run (creates pending run)
  TestRunnerOwnership  — cross-user isolation
  TestRunnerAuth       — endpoints require bearer token
"""
import pytest
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.assertion_engine import (
    AssertionOutcome,
    HttpResult,
    evaluate_assertions,
)

pytestmark = pytest.mark.asyncio


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _register(client, email: str, password: str = "Password1") -> str:
    res = await client.post(
        "/auth/register",
        json={"name": "Test", "email": email, "password": password},
    )
    assert res.status_code == 201
    return res.json()["access_token"]


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_workspace(client, token: str) -> str:
    r = await client.post("/workspaces", json={"name": "WS"}, headers=_h(token))
    assert r.status_code == 201
    return r.json()["id"]


async def _make_collection(client, token: str, ws_id: str) -> str:
    r = await client.post(
        f"/workspaces/{ws_id}/collections",
        json={"name": "Col"},
        headers=_h(token),
    )
    assert r.status_code == 201
    return r.json()["id"]


async def _make_request(client, token: str, col_id: str, **kwargs) -> str:
    payload = {
        "name": "GET test",
        "method": "GET",
        "url": "https://httpbin.org/get",
        **kwargs,
    }
    r = await client.post(
        f"/collections/{col_id}/requests",
        json=payload,
        headers=_h(token),
    )
    assert r.status_code == 201
    return r.json()["id"]


async def _add_assertion(client, token: str, req_id: str, **kwargs) -> str:
    payload = {
        "type": "status_code",
        "operator": "eq",
        "expected_value": "200",
        **kwargs,
    }
    r = await client.post(
        f"/requests/{req_id}/assertions",
        json=payload,
        headers=_h(token),
    )
    assert r.status_code == 201
    return r.json()["id"]


def _mock_http_200(body: str = '{"ok": true}') -> MagicMock:
    """Return a mock that makes execute_http return a 200 response."""
    mock_result = HttpResult(
        status_code=200,
        headers={"content-type": "application/json"},
        body=body,
        response_time_ms=42,
        error=None,
    )
    return mock_result


# ══════════════════════════════════════════════════════════════════════════════
# 1. Assertion engine — pure unit tests
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class FakeAssertion:
    id: str
    type: str
    operator: str
    expected_value: str
    path: str | None = None


def _ok() -> HttpResult:
    return HttpResult(
        status_code=200,
        headers={"content-type": "application/json", "x-request-id": "abc"},
        body='{"user": {"id": 42, "name": "Alice"}, "active": true}',
        response_time_ms=150,
        error=None,
    )


class TestAssertionEngine:

    # ── status_code ────────────────────────────────────────────────────────────

    def test_status_code_eq_passes(self):
        a = FakeAssertion("1", "status_code", "eq", "200")
        [out] = evaluate_assertions([a], _ok())
        assert out.passed is True
        assert out.actual_value == "200"

    def test_status_code_eq_fails(self):
        a = FakeAssertion("1", "status_code", "eq", "404")
        [out] = evaluate_assertions([a], _ok())
        assert out.passed is False

    def test_status_code_ne(self):
        a = FakeAssertion("1", "status_code", "ne", "500")
        [out] = evaluate_assertions([a], _ok())
        assert out.passed is True

    def test_status_code_gte(self):
        a = FakeAssertion("1", "status_code", "gte", "200")
        [out] = evaluate_assertions([a], _ok())
        assert out.passed is True

    def test_status_code_lt_fails_when_equal(self):
        a = FakeAssertion("1", "status_code", "lt", "200")
        [out] = evaluate_assertions([a], _ok())
        assert out.passed is False

    # ── response_time ──────────────────────────────────────────────────────────

    def test_response_time_lt_passes(self):
        a = FakeAssertion("1", "response_time", "lt", "500")
        [out] = evaluate_assertions([a], _ok())
        assert out.passed is True

    def test_response_time_lt_fails_when_slow(self):
        slow = HttpResult(status_code=200, headers={}, body=None,
                          response_time_ms=600, error=None)
        a = FakeAssertion("1", "response_time", "lt", "500")
        [out] = evaluate_assertions([a], slow)
        assert out.passed is False

    def test_response_time_lte_passes_when_equal(self):
        a = FakeAssertion("1", "response_time", "lte", "150")
        [out] = evaluate_assertions([a], _ok())
        assert out.passed is True

    # ── json_path ──────────────────────────────────────────────────────────────

    def test_json_path_eq_passes(self):
        a = FakeAssertion("1", "json_path", "eq", "42", path="$.user.id")
        [out] = evaluate_assertions([a], _ok())
        assert out.passed is True
        assert out.actual_value == "42"

    def test_json_path_eq_fails(self):
        a = FakeAssertion("1", "json_path", "eq", "99", path="$.user.id")
        [out] = evaluate_assertions([a], _ok())
        assert out.passed is False

    def test_json_path_contains(self):
        a = FakeAssertion("1", "json_path", "contains", "Ali", path="$.user.name")
        [out] = evaluate_assertions([a], _ok())
        assert out.passed is True

    def test_json_path_exists_when_present(self):
        a = FakeAssertion("1", "json_path", "exists", "", path="$.user.id")
        [out] = evaluate_assertions([a], _ok())
        assert out.passed is True

    def test_json_path_exists_when_absent(self):
        a = FakeAssertion("1", "json_path", "exists", "", path="$.missing")
        [out] = evaluate_assertions([a], _ok())
        assert out.passed is False

    def test_json_path_missing_returns_failed_not_error(self):
        a = FakeAssertion("1", "json_path", "eq", "x", path="$.nonexistent")
        [out] = evaluate_assertions([a], _ok())
        assert out.passed is False
        assert out.error_message is None   # None extracted, comparison fails cleanly

    def test_json_path_invalid_path_returns_error(self):
        a = FakeAssertion("1", "json_path", "eq", "x", path="INVALID[[")
        [out] = evaluate_assertions([a], _ok())
        assert out.passed is False
        assert out.error_message is not None

    def test_json_path_empty_body_returns_error(self):
        no_body = HttpResult(status_code=200, headers={}, body=None,
                             response_time_ms=10, error=None)
        a = FakeAssertion("1", "json_path", "eq", "x", path="$.id")
        [out] = evaluate_assertions([a], no_body)
        assert out.passed is False
        assert out.error_message is not None

    # ── header ─────────────────────────────────────────────────────────────────

    def test_header_eq_passes(self):
        a = FakeAssertion("1", "header", "eq", "application/json",
                          path="content-type")
        [out] = evaluate_assertions([a], _ok())
        assert out.passed is True

    def test_header_contains(self):
        a = FakeAssertion("1", "header", "contains", "json", path="content-type")
        [out] = evaluate_assertions([a], _ok())
        assert out.passed is True

    def test_header_exists(self):
        a = FakeAssertion("1", "header", "exists", "", path="x-request-id")
        [out] = evaluate_assertions([a], _ok())
        assert out.passed is True

    def test_header_missing_exists_fails(self):
        a = FakeAssertion("1", "header", "exists", "", path="x-missing")
        [out] = evaluate_assertions([a], _ok())
        assert out.passed is False

    # ── body_contains ──────────────────────────────────────────────────────────

    def test_body_contains_passes(self):
        a = FakeAssertion("1", "body_contains", "contains", "Alice")
        [out] = evaluate_assertions([a], _ok())
        assert out.passed is True

    def test_body_not_contains_passes(self):
        a = FakeAssertion("1", "body_contains", "not_contains", "Bob")
        [out] = evaluate_assertions([a], _ok())
        assert out.passed is True

    def test_body_contains_fails(self):
        a = FakeAssertion("1", "body_contains", "contains", "ERROR")
        [out] = evaluate_assertions([a], _ok())
        assert out.passed is False

    def test_body_matches_regex(self):
        a = FakeAssertion("1", "body_contains", "matches", r'"id":\s*\d+')
        [out] = evaluate_assertions([a], _ok())
        assert out.passed is True

    # ── Error state ────────────────────────────────────────────────────────────

    def test_all_assertions_fail_when_request_errored(self):
        errored = HttpResult(status_code=None, headers={}, body=None,
                             response_time_ms=0, error="Connection refused")
        assertions = [
            FakeAssertion("1", "status_code", "eq", "200"),
            FakeAssertion("2", "response_time", "lt", "500"),
        ]
        outcomes = evaluate_assertions(assertions, errored)
        assert all(not o.passed for o in outcomes)
        assert all("Connection refused" in (o.error_message or "") for o in outcomes)

    # ── Snapshot ───────────────────────────────────────────────────────────────

    def test_assertion_snapshot_captured(self):
        a = FakeAssertion("1", "status_code", "eq", "200")
        [out] = evaluate_assertions([a], _ok())
        snap = out.assertion_snapshot
        assert snap["type"] == "status_code"
        assert snap["operator"] == "eq"
        assert snap["expected_value"] == "200"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Single-request run (mocked httpx)
# ══════════════════════════════════════════════════════════════════════════════

class TestSingleRun:

    @patch("app.services.runner_service.execute_http")
    async def test_run_returns_result(self, mock_exec, client):
        mock_exec.return_value = _mock_http_200()

        token = await _register(client, "sr1@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        req_id = await _make_request(client, token, col_id)

        res = await client.post(
            f"/requests/{req_id}/run",
            json={},
            headers=_h(token),
        )
        assert res.status_code == 201
        body = res.json()
        assert body["status"] == "passed"
        assert body["response_status"] == 200
        assert body["response_time_ms"] == 42
        assert body["response_body"] == '{"ok": true}'

    @patch("app.services.runner_service.execute_http")
    async def test_run_captures_headers(self, mock_exec, client):
        mock_exec.return_value = HttpResult(
            status_code=201,
            headers={"content-type": "application/json", "location": "/users/1"},
            body='{"id": 1}',
            response_time_ms=30,
            error=None,
        )
        token = await _register(client, "sr2@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        req_id = await _make_request(client, token, col_id, method="POST",
                                      body='{}', body_type="json")

        res = await client.post(f"/requests/{req_id}/run", json={}, headers=_h(token))
        body = res.json()
        assert body["response_status"] == 201
        assert "content-type" in body["response_headers"]

    @patch("app.services.runner_service.execute_http")
    async def test_run_evaluates_passing_assertion(self, mock_exec, client):
        mock_exec.return_value = _mock_http_200()

        token = await _register(client, "sr3@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        req_id = await _make_request(client, token, col_id)
        await _add_assertion(client, token, req_id,
                             type="status_code", operator="eq", expected_value="200")

        res = await client.post(f"/requests/{req_id}/run", json={}, headers=_h(token))
        body = res.json()
        assert body["status"] == "passed"
        assert len(body["assertion_results"]) == 1
        assert body["assertion_results"][0]["passed"] is True

    @patch("app.services.runner_service.execute_http")
    async def test_run_evaluates_failing_assertion(self, mock_exec, client):
        mock_exec.return_value = _mock_http_200()  # returns 200

        token = await _register(client, "sr4@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        req_id = await _make_request(client, token, col_id)
        await _add_assertion(client, token, req_id,
                             type="status_code", operator="eq", expected_value="201")

        res = await client.post(f"/requests/{req_id}/run", json={}, headers=_h(token))
        body = res.json()
        assert body["status"] == "failed"
        assert body["assertion_results"][0]["passed"] is False
        assert body["assertion_results"][0]["actual_value"] == "200"

    @patch("app.services.runner_service.execute_http")
    async def test_run_stores_result_in_db(self, mock_exec, client):
        mock_exec.return_value = _mock_http_200()

        token = await _register(client, "sr5@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        req_id = await _make_request(client, token, col_id)

        run_res = await client.post(
            f"/requests/{req_id}/run", json={}, headers=_h(token)
        )
        result_id = run_res.json()["id"]
        run_id = run_res.json()["test_run_id"]

        # Fetch via GET /results/{id}
        res = await client.get(f"/results/{result_id}", headers=_h(token))
        assert res.status_code == 200
        assert res.json()["id"] == result_id

        # Fetch via GET /runs/{id}
        res = await client.get(f"/runs/{run_id}", headers=_h(token))
        assert res.status_code == 200
        run = res.json()
        assert run["total"] == 1
        assert run["passed"] == 1
        assert len(run["results"]) == 1

    @patch("app.services.runner_service.execute_http")
    async def test_run_error_on_connection_failure(self, mock_exec, client):
        mock_exec.return_value = HttpResult(
            status_code=None, headers={}, body=None,
            response_time_ms=100, error="Connection refused",
        )
        token = await _register(client, "sr6@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        req_id = await _make_request(client, token, col_id)

        res = await client.post(f"/requests/{req_id}/run", json={}, headers=_h(token))
        body = res.json()
        assert body["status"] == "error"
        assert body["error_message"] == "Connection refused"
        assert body["response_status"] is None

    @patch("app.services.runner_service.execute_http")
    async def test_run_request_snapshot_stored(self, mock_exec, client):
        mock_exec.return_value = _mock_http_200()

        token = await _register(client, "sr7@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        req_id = await _make_request(client, token, col_id,
                                     url="https://api.example.com/users")

        res = await client.post(f"/requests/{req_id}/run", json={}, headers=_h(token))
        snap = res.json()["request_snapshot"]
        assert snap["url"] == "https://api.example.com/users"
        assert snap["method"] == "GET"


# ══════════════════════════════════════════════════════════════════════════════
# 3. Run history
# ══════════════════════════════════════════════════════════════════════════════

class TestRunHistory:

    @patch("app.services.runner_service.execute_http")
    async def test_list_runs_returns_history(self, mock_exec, client):
        mock_exec.return_value = _mock_http_200()

        token = await _register(client, "rh1@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        req_id = await _make_request(client, token, col_id)

        # Execute twice
        for _ in range(2):
            await client.post(f"/requests/{req_id}/run", json={}, headers=_h(token))

        res = await client.get(f"/workspaces/{ws_id}/runs", headers=_h(token))
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 2

    @patch("app.services.runner_service.execute_http")
    async def test_get_run_detail(self, mock_exec, client):
        mock_exec.return_value = _mock_http_200()

        token = await _register(client, "rh2@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)
        req_id = await _make_request(client, token, col_id)
        await _add_assertion(client, token, req_id)

        run_res = await client.post(f"/requests/{req_id}/run", json={}, headers=_h(token))
        run_id = run_res.json()["test_run_id"]

        res = await client.get(f"/runs/{run_id}", headers=_h(token))
        assert res.status_code == 200
        run = res.json()
        assert run["status"] in ("passed", "failed", "error")
        assert len(run["results"]) == 1
        assert len(run["results"][0]["assertion_results"]) == 1

    async def test_get_run_not_found(self, client):
        token = await _register(client, "rh3@test.com")
        res = await client.get("/runs/nonexistent-id", headers=_h(token))
        assert res.status_code == 404

    async def test_get_result_not_found(self, client):
        token = await _register(client, "rh4@test.com")
        res = await client.get("/results/nonexistent-id", headers=_h(token))
        assert res.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 4. Collection run (async)
# ══════════════════════════════════════════════════════════════════════════════

class TestCollectionRun:

    async def test_collection_run_returns_202_pending(self, client):
        token = await _register(client, "cr1@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)

        res = await client.post(
            f"/collections/{col_id}/run",
            json={},
            headers=_h(token),
        )
        assert res.status_code == 202
        body = res.json()
        assert body["status"] == "pending"
        assert body["collection_id"] == col_id
        assert "id" in body

    async def test_collection_run_404_unknown_collection(self, client):
        token = await _register(client, "cr2@test.com")
        res = await client.post(
            "/collections/nonexistent/run",
            json={},
            headers=_h(token),
        )
        assert res.status_code == 404

    async def test_collection_run_appears_in_history(self, client):
        token = await _register(client, "cr3@test.com")
        ws_id = await _make_workspace(client, token)
        col_id = await _make_collection(client, token, ws_id)

        await client.post(f"/collections/{col_id}/run", json={}, headers=_h(token))

        res = await client.get(f"/workspaces/{ws_id}/runs", headers=_h(token))
        body = res.json()
        assert body["total"] == 1
        assert body["items"][0]["status"] == "pending"

    async def test_collection_run_filter_by_collection(self, client):
        token = await _register(client, "cr4@test.com")
        ws_id = await _make_workspace(client, token)
        col_a = await _make_collection(client, token, ws_id)
        col_b = await _make_collection(client, token, ws_id)

        await client.post(f"/collections/{col_a}/run", json={}, headers=_h(token))
        await client.post(f"/collections/{col_b}/run", json={}, headers=_h(token))

        res = await client.get(
            f"/workspaces/{ws_id}/runs?collection_id={col_a}",
            headers=_h(token),
        )
        body = res.json()
        assert body["total"] == 1
        assert body["items"][0]["collection_id"] == col_a


# ══════════════════════════════════════════════════════════════════════════════
# 5. Auth enforcement
# ══════════════════════════════════════════════════════════════════════════════

class TestRunnerAuth:

    async def test_single_run_requires_auth(self, client):
        res = await client.post("/requests/any-id/run", json={})
        assert res.status_code == 403

    async def test_collection_run_requires_auth(self, client):
        res = await client.post("/collections/any-id/run", json={})
        assert res.status_code == 403

    async def test_list_runs_requires_auth(self, client):
        res = await client.get("/workspaces/any-id/runs")
        assert res.status_code == 403

    async def test_get_run_requires_auth(self, client):
        res = await client.get("/runs/any-id")
        assert res.status_code == 403

    async def test_get_result_requires_auth(self, client):
        res = await client.get("/results/any-id")
        assert res.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# 6. Cross-user ownership
# ══════════════════════════════════════════════════════════════════════════════

class TestRunnerOwnership:

    @patch("app.services.runner_service.execute_http")
    async def test_user_cannot_see_other_users_run(self, mock_exec, client):
        mock_exec.return_value = _mock_http_200()

        owner = await _register(client, "own_r1@test.com")
        other = await _register(client, "oth_r1@test.com")

        ws_id  = await _make_workspace(client, owner)
        col_id = await _make_collection(client, owner, ws_id)
        req_id = await _make_request(client, owner, col_id)
        run_res = await client.post(
            f"/requests/{req_id}/run", json={}, headers=_h(owner)
        )
        run_id    = run_res.json()["test_run_id"]
        result_id = run_res.json()["id"]

        # Other user cannot access owner's run or result
        assert (await client.get(f"/runs/{run_id}",     headers=_h(other))).status_code == 404
        assert (await client.get(f"/results/{result_id}", headers=_h(other))).status_code == 404

    @patch("app.services.runner_service.execute_http")
    async def test_user_cannot_run_other_users_request(self, mock_exec, client):
        mock_exec.return_value = _mock_http_200()

        owner = await _register(client, "own_r2@test.com")
        other = await _register(client, "oth_r2@test.com")

        ws_id  = await _make_workspace(client, owner)
        col_id = await _make_collection(client, owner, ws_id)
        req_id = await _make_request(client, owner, col_id)

        res = await client.post(
            f"/requests/{req_id}/run", json={}, headers=_h(other)
        )
        assert res.status_code == 404
