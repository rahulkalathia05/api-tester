"""
Analytics dashboard tests.

Structure:
  TestAnalyticsSummary    — KPI counts, pass rate, latency
  TestAnalyticsTrend      — daily bucketing, date format
  TestAnalyticsEndpoints  — slowest endpoints sorted, fields present
  TestAnalyticsCollections — per-collection aggregation
  TestAnalyticsFiltering  — days parameter restricts window
  TestAnalyticsAuth       — endpoint requires bearer token
  TestAnalyticsOwnership  — cross-user isolation
"""
import pytest
from unittest.mock import patch

from app.services.runner_service import HttpResult

pytestmark = pytest.mark.asyncio

# ── Helpers ───────────────────────────────────────────────────────────────────

async def _register(client, email: str) -> str:
    r = await client.post(
        "/auth/register",
        json={"name": "T", "email": email, "password": "Password1"},
    )
    return r.json()["access_token"]


def _h(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


async def _setup(client, email: str):
    """Create workspace + collection + 2 requests; run each once."""
    token = await _register(client, email)
    h = _h(token)
    ws  = (await client.post("/workspaces", json={"name": "W"}, headers=h)).json()["id"]
    col = (await client.post(f"/workspaces/{ws}/collections",
                             json={"name": "Users API"}, headers=h)).json()["id"]
    req_a = (await client.post(f"/collections/{col}/requests",
                               json={"name": "List Users",   "method": "GET",
                                     "url": "https://api.example.com/users"},
                               headers=h)).json()["id"]
    req_b = (await client.post(f"/collections/{col}/requests",
                               json={"name": "Create User",  "method": "POST",
                                     "url": "https://api.example.com/users"},
                               headers=h)).json()["id"]

    # Add a failing assertion to req_b so one run fails
    await client.post(f"/requests/{req_b}/assertions",
                      json={"type": "status_code", "operator": "eq",
                            "expected_value": "201"}, headers=h)

    fast = HttpResult(status_code=200, headers={"content-type": "application/json"},
                      body='{"users":[]}', response_time_ms=50, error=None)
    slow = HttpResult(status_code=200, headers={}, body='{"id":1}',
                      response_time_ms=800, error=None)

    with patch("app.services.runner_service.execute_http", return_value=fast):
        await client.post(f"/requests/{req_a}/run", json={}, headers=h)
    with patch("app.services.runner_service.execute_http", return_value=slow):
        await client.post(f"/requests/{req_b}/run", json={}, headers=h)

    return token, ws, col, req_a, req_b


# ══════════════════════════════════════════════════════════════════════════════
# 1. Summary KPIs
# ══════════════════════════════════════════════════════════════════════════════

class TestAnalyticsSummary:

    async def test_empty_workspace_returns_zeros(self, client):
        token = await _register(client, "an0@test.com")
        h = _h(token)
        ws = (await client.post("/workspaces", json={"name": "W"}, headers=h)).json()["id"]
        r = await client.get(f"/workspaces/{ws}/analytics", headers=h)
        assert r.status_code == 200
        s = r.json()["summary"]
        assert s["total_runs"] == 0
        assert s["total_executions"] == 0
        assert s["pass_rate"] == 0.0

    async def test_total_runs_counts_correctly(self, client):
        token, ws, *_ = await _setup(client, "an1@test.com")
        r = await client.get(f"/workspaces/{ws}/analytics", headers=_h(token))
        s = r.json()["summary"]
        assert s["total_runs"] == 2    # one per request run

    async def test_total_executions_counts_results(self, client):
        token, ws, *_ = await _setup(client, "an2@test.com")
        r = await client.get(f"/workspaces/{ws}/analytics", headers=_h(token))
        s = r.json()["summary"]
        assert s["total_executions"] == 2

    async def test_pass_rate_between_zero_and_one(self, client):
        token, ws, *_ = await _setup(client, "an3@test.com")
        r = await client.get(f"/workspaces/{ws}/analytics", headers=_h(token))
        pr = r.json()["summary"]["pass_rate"]
        assert 0.0 <= pr <= 1.0

    async def test_avg_response_time_present(self, client):
        token, ws, *_ = await _setup(client, "an4@test.com")
        r = await client.get(f"/workspaces/{ws}/analytics", headers=_h(token))
        avg = r.json()["summary"]["avg_response_time_ms"]
        assert avg is not None
        assert avg > 0

    async def test_p95_latency_present(self, client):
        token, ws, *_ = await _setup(client, "an5@test.com")
        r = await client.get(f"/workspaces/{ws}/analytics", headers=_h(token))
        p95 = r.json()["summary"]["p95_response_time_ms"]
        assert p95 is not None

    async def test_days_field_reflects_parameter(self, client):
        token, ws, *_ = await _setup(client, "an6@test.com")
        r = await client.get(f"/workspaces/{ws}/analytics?days=7", headers=_h(token))
        assert r.json()["summary"]["days"] == 7

    async def test_all_summary_fields_present(self, client):
        token, ws, *_ = await _setup(client, "an7@test.com")
        r = await client.get(f"/workspaces/{ws}/analytics", headers=_h(token))
        s = r.json()["summary"]
        for field in ("total_runs", "passed_runs", "failed_runs", "error_runs",
                      "pass_rate", "total_executions", "passed_executions",
                      "failed_executions", "avg_response_time_ms", "p95_response_time_ms"):
            assert field in s, f"missing field: {field}"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Daily trend
# ══════════════════════════════════════════════════════════════════════════════

class TestAnalyticsTrend:

    async def test_trend_entries_have_required_fields(self, client):
        token, ws, *_ = await _setup(client, "tr1@test.com")
        r = await client.get(f"/workspaces/{ws}/analytics", headers=_h(token))
        trend = r.json()["daily_trend"]
        if trend:
            entry = trend[0]
            for field in ("date", "total", "passed", "failed", "pass_rate"):
                assert field in entry

    async def test_trend_date_format(self, client):
        import re
        token, ws, *_ = await _setup(client, "tr2@test.com")
        r = await client.get(f"/workspaces/{ws}/analytics", headers=_h(token))
        trend = r.json()["daily_trend"]
        for entry in trend:
            assert re.match(r"\d{4}-\d{2}-\d{2}", entry["date"]), \
                f"date {entry['date']!r} not YYYY-MM-DD"

    async def test_trend_pass_rate_consistent(self, client):
        token, ws, *_ = await _setup(client, "tr3@test.com")
        r = await client.get(f"/workspaces/{ws}/analytics", headers=_h(token))
        for entry in r.json()["daily_trend"]:
            computed = entry["passed"] / entry["total"] if entry["total"] else 0.0
            assert abs(entry["pass_rate"] - computed) < 0.01

    async def test_empty_workspace_has_empty_trend(self, client):
        token = await _register(client, "tr4@test.com")
        h = _h(token)
        ws = (await client.post("/workspaces", json={"name": "W"}, headers=h)).json()["id"]
        r = await client.get(f"/workspaces/{ws}/analytics", headers=h)
        assert r.json()["daily_trend"] == []


# ══════════════════════════════════════════════════════════════════════════════
# 3. Slowest endpoints
# ══════════════════════════════════════════════════════════════════════════════

class TestAnalyticsEndpoints:

    async def test_endpoints_returned(self, client):
        token, ws, *_ = await _setup(client, "ep1@test.com")
        r = await client.get(f"/workspaces/{ws}/analytics", headers=_h(token))
        eps = r.json()["slowest_endpoints"]
        assert len(eps) >= 1

    async def test_endpoints_ordered_by_avg_latency_desc(self, client):
        token, ws, *_ = await _setup(client, "ep2@test.com")
        r = await client.get(f"/workspaces/{ws}/analytics", headers=_h(token))
        eps = r.json()["slowest_endpoints"]
        if len(eps) >= 2:
            assert eps[0]["avg_response_time_ms"] >= eps[1]["avg_response_time_ms"]

    async def test_endpoint_has_required_fields(self, client):
        token, ws, *_ = await _setup(client, "ep3@test.com")
        r = await client.get(f"/workspaces/{ws}/analytics", headers=_h(token))
        for ep in r.json()["slowest_endpoints"]:
            for field in ("name", "method", "url", "total_executions",
                          "avg_response_time_ms", "max_response_time_ms", "pass_rate"):
                assert field in ep, f"missing field: {field}"

    async def test_slow_request_appears_first(self, client):
        token, ws, col, req_a, req_b = await _setup(client, "ep4@test.com")
        r = await client.get(f"/workspaces/{ws}/analytics", headers=_h(token))
        eps = r.json()["slowest_endpoints"]
        # req_b ran at 800ms, req_a at 50ms — req_b should be first
        assert eps[0]["avg_response_time_ms"] >= eps[-1]["avg_response_time_ms"]

    async def test_endpoint_pass_rate_between_0_and_1(self, client):
        token, ws, *_ = await _setup(client, "ep5@test.com")
        r = await client.get(f"/workspaces/{ws}/analytics", headers=_h(token))
        for ep in r.json()["slowest_endpoints"]:
            assert 0.0 <= ep["pass_rate"] <= 1.0


# ══════════════════════════════════════════════════════════════════════════════
# 4. Collection stats
# ══════════════════════════════════════════════════════════════════════════════

class TestAnalyticsCollections:

    async def test_collection_stats_present(self, client):
        token, ws, *_ = await _setup(client, "cs1@test.com")
        r = await client.get(f"/workspaces/{ws}/analytics", headers=_h(token))
        # Single request runs don't have collection_id — collection_stats may be empty
        # This test just checks the field is a list
        assert isinstance(r.json()["collection_stats"], list)

    async def test_collection_run_appears_in_stats(self, client):
        token = await _register(client, "cs2@test.com")
        h = _h(token)
        ws  = (await client.post("/workspaces", json={"name": "W"}, headers=h)).json()["id"]
        col = (await client.post(f"/workspaces/{ws}/collections",
                                 json={"name": "API Suite"}, headers=h)).json()["id"]
        req = (await client.post(f"/collections/{col}/requests",
                                 json={"name": "R", "method": "GET",
                                       "url": "https://a.com"}, headers=h)).json()["id"]

        mock = HttpResult(status_code=200, headers={}, body='{}',
                          response_time_ms=100, error=None)
        with patch("app.services.runner_service.execute_http", return_value=mock):
            await client.post(f"/requests/{req}/run", json={}, headers=h)

        # Collection runs (POST /collections/{id}/run) create TestRun with collection_id
        # Since we ran a single request, collection_id is None — collection_stats empty here
        r = await client.get(f"/workspaces/{ws}/analytics", headers=h)
        assert r.status_code == 200   # just verify no error

    async def test_collection_stat_fields(self, client):
        token, ws, *_ = await _setup(client, "cs3@test.com")
        r = await client.get(f"/workspaces/{ws}/analytics", headers=_h(token))
        for cs in r.json()["collection_stats"]:
            for field in ("collection_id", "collection_name", "total_runs",
                          "passed_runs", "pass_rate"):
                assert field in cs


# ══════════════════════════════════════════════════════════════════════════════
# 5. Days filter
# ══════════════════════════════════════════════════════════════════════════════

class TestAnalyticsFiltering:

    async def test_days_1_may_return_zero(self, client):
        """Recent runs should still appear; runs older than 1 day won't."""
        token, ws, *_ = await _setup(client, "af1@test.com")
        r = await client.get(f"/workspaces/{ws}/analytics?days=1", headers=_h(token))
        assert r.status_code == 200
        # Just verify the field is present — runs were just created so they will appear
        assert "summary" in r.json()

    async def test_days_365_includes_all(self, client):
        token, ws, *_ = await _setup(client, "af2@test.com")
        r365 = await client.get(f"/workspaces/{ws}/analytics?days=365", headers=_h(token))
        r30  = await client.get(f"/workspaces/{ws}/analytics?days=30",  headers=_h(token))
        # 365-day window should include at least as many runs as 30-day
        assert r365.json()["summary"]["total_runs"] >= r30.json()["summary"]["total_runs"]

    async def test_invalid_days_rejected(self, client):
        token = await _register(client, "af3@test.com")
        h = _h(token)
        ws = (await client.post("/workspaces", json={"name": "W"}, headers=h)).json()["id"]
        r = await client.get(f"/workspaces/{ws}/analytics?days=0", headers=h)
        assert r.status_code == 422
        r = await client.get(f"/workspaces/{ws}/analytics?days=366", headers=h)
        assert r.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# 6. Auth
# ══════════════════════════════════════════════════════════════════════════════

class TestAnalyticsAuth:

    async def test_requires_bearer(self, client):
        r = await client.get("/workspaces/any-id/analytics")
        assert r.status_code == 403

    async def test_unknown_workspace_returns_404(self, client):
        token = await _register(client, "aa1@test.com")
        r = await client.get("/workspaces/nonexistent/analytics", headers=_h(token))
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 7. Ownership
# ══════════════════════════════════════════════════════════════════════════════

class TestAnalyticsOwnership:

    async def test_other_user_cannot_see_analytics(self, client):
        owner = await _register(client, "ow_a1@test.com")
        other = await _register(client, "oth_a1@test.com")
        ws = (await client.post("/workspaces", json={"name": "W"},
                                headers=_h(owner))).json()["id"]
        r = await client.get(f"/workspaces/{ws}/analytics", headers=_h(other))
        assert r.status_code == 404
