"""
Scheduled test execution tests.

Structure:
  TestCronUtils         — validate_cron, next_after, cron_description
  TestScheduleCRUD      — list, create, get, update, delete
  TestSchedulePresets   — GET /schedules/presets
  TestActivation        — activate/deactivate and next_run_at behaviour
  TestScheduleHistory   — history returns scheduled-trigger runs
  TestScheduleFiring    — fire_due_schedules creates runs + updates timestamps
  TestValidation        — invalid cron rejected, empty patch rejected
  TestScheduleAuth      — all endpoints require bearer
  TestScheduleOwnership — cross-user isolation
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis as fakeredis

from app.utils.cron import cron_description, next_after, validate_cron

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


async def _make_collection(client, token: str) -> tuple[str, str]:
    h = _h(token)
    ws  = (await client.post("/workspaces", json={"name": "W"}, headers=h)).json()["id"]
    col = (await client.post(f"/workspaces/{ws}/collections",
                             json={"name": "C"}, headers=h)).json()["id"]
    return ws, col


async def _make_schedule(client, token: str, col_id: str,
                          cron: str = "0 9 * * *") -> str:
    r = await client.post(
        f"/collections/{col_id}/schedules",
        json={"cron_expression": cron},
        headers=_h(token),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ══════════════════════════════════════════════════════════════════════════════
# 1. Cron utilities (pure functions)
# ══════════════════════════════════════════════════════════════════════════════

class TestCronUtils:

    def test_valid_expressions(self):
        valid = ["0 * * * *", "*/15 * * * *", "0 9 * * 1",
                 "0 0 1 * *", "30 18 * * 5"]
        for expr in valid:
            assert validate_cron(expr), f"{expr!r} should be valid"

    def test_invalid_expressions(self):
        invalid = ["not-a-cron", "0 0 0", "61 * * * *", "0 25 * * *", ""]
        for expr in invalid:
            assert not validate_cron(expr), f"{expr!r} should be invalid"

    def test_next_after_is_in_the_future(self):
        now  = datetime.now(timezone.utc)
        nxt  = next_after("0 * * * *", now)
        assert nxt > now

    def test_next_after_is_timezone_aware(self):
        nxt = next_after("0 9 * * *", datetime.now(timezone.utc))
        assert nxt.tzinfo is not None

    def test_next_after_hourly(self):
        base = datetime(2025, 1, 1, 8, 30, 0, tzinfo=timezone.utc)
        nxt  = next_after("0 * * * *", base)
        assert nxt.hour == 9
        assert nxt.minute == 0

    def test_next_after_daily(self):
        base = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        nxt  = next_after("0 9 * * *", base)
        assert nxt.day == 2    # already past 9am today → next day
        assert nxt.hour == 9

    def test_cron_description_known_pattern(self):
        assert cron_description("0 * * * *") == "Every hour"
        assert cron_description("0 9 * * *") == "Daily at 09:00 UTC"
        assert cron_description("0 9 * * 1") == "Every Monday at 09:00 UTC"

    def test_cron_description_unknown_falls_back(self):
        expr = "15 14 * * 3"
        assert cron_description(expr) == expr


# ══════════════════════════════════════════════════════════════════════════════
# 2. Schedule CRUD
# ══════════════════════════════════════════════════════════════════════════════

class TestScheduleCRUD:

    async def test_create_returns_201(self, client):
        token    = await _register(client, "sc1@test.com")
        _, col   = await _make_collection(client, token)
        r = await client.post(
            f"/collections/{col}/schedules",
            json={"cron_expression": "0 9 * * *"},
            headers=_h(token),
        )
        assert r.status_code == 201
        b = r.json()
        assert b["cron_expression"] == "0 9 * * *"
        assert b["is_active"] is True
        assert b["next_run_at"] is not None
        assert "cron_description" in b

    async def test_create_inactive_has_no_next_run(self, client):
        token  = await _register(client, "sc2@test.com")
        _, col = await _make_collection(client, token)
        r = await client.post(
            f"/collections/{col}/schedules",
            json={"cron_expression": "0 9 * * *", "is_active": False},
            headers=_h(token),
        )
        assert r.status_code == 201
        assert r.json()["next_run_at"] is None

    async def test_list_schedules(self, client):
        token  = await _register(client, "sc3@test.com")
        _, col = await _make_collection(client, token)
        await _make_schedule(client, token, col, "0 * * * *")
        await _make_schedule(client, token, col, "0 9 * * *")
        r = await client.get(f"/collections/{col}/schedules", headers=_h(token))
        assert r.status_code == 200
        assert len(r.json()) == 2

    async def test_get_schedule(self, client):
        token   = await _register(client, "sc4@test.com")
        _, col  = await _make_collection(client, token)
        sid     = await _make_schedule(client, token, col)
        r = await client.get(f"/schedules/{sid}", headers=_h(token))
        assert r.status_code == 200
        assert r.json()["id"] == sid

    async def test_update_cron_expression(self, client):
        token   = await _register(client, "sc5@test.com")
        _, col  = await _make_collection(client, token)
        sid     = await _make_schedule(client, token, col, "0 9 * * *")
        r = await client.patch(
            f"/schedules/{sid}",
            json={"cron_expression": "0 18 * * *"},
            headers=_h(token),
        )
        assert r.status_code == 200
        assert r.json()["cron_expression"] == "0 18 * * *"

    async def test_update_recomputes_next_run(self, client):
        token   = await _register(client, "sc6@test.com")
        _, col  = await _make_collection(client, token)
        sid     = await _make_schedule(client, token, col, "0 9 * * *")
        before  = (await client.get(f"/schedules/{sid}", headers=_h(token))).json()["next_run_at"]
        r = await client.patch(
            f"/schedules/{sid}",
            json={"cron_expression": "0 22 * * *"},
            headers=_h(token),
        )
        after = r.json()["next_run_at"]
        assert after != before   # different schedule → different next run time

    async def test_delete_schedule(self, client):
        token   = await _register(client, "sc7@test.com")
        _, col  = await _make_collection(client, token)
        sid     = await _make_schedule(client, token, col)
        r = await client.delete(f"/schedules/{sid}", headers=_h(token))
        assert r.status_code == 204
        r = await client.get(f"/schedules/{sid}", headers=_h(token))
        assert r.status_code == 404

    async def test_empty_patch_rejected(self, client):
        token   = await _register(client, "sc8@test.com")
        _, col  = await _make_collection(client, token)
        sid     = await _make_schedule(client, token, col)
        r = await client.patch(f"/schedules/{sid}", json={}, headers=_h(token))
        assert r.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# 3. Presets
# ══════════════════════════════════════════════════════════════════════════════

class TestSchedulePresets:

    async def test_presets_returned(self, client):
        r = await client.get("/schedules/presets")
        assert r.status_code == 200
        presets = r.json()
        assert len(presets) >= 4

    async def test_presets_have_required_fields(self, client):
        r = await client.get("/schedules/presets")
        for p in r.json():
            assert "label" in p
            assert "cron" in p
            assert "description" in p

    async def test_hourly_preset_present(self, client):
        r = await client.get("/schedules/presets")
        crons = {p["cron"] for p in r.json()}
        assert "0 * * * *" in crons

    async def test_daily_preset_present(self, client):
        r = await client.get("/schedules/presets")
        crons = {p["cron"] for p in r.json()}
        assert "0 9 * * *" in crons

    async def test_weekly_preset_present(self, client):
        r = await client.get("/schedules/presets")
        crons = {p["cron"] for p in r.json()}
        assert "0 9 * * 1" in crons

    async def test_presets_no_auth_required(self, client):
        r = await client.get("/schedules/presets")
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 4. Activation
# ══════════════════════════════════════════════════════════════════════════════

class TestActivation:

    async def test_deactivate_clears_next_run(self, client):
        token   = await _register(client, "ac1@test.com")
        _, col  = await _make_collection(client, token)
        sid     = await _make_schedule(client, token, col)
        r = await client.post(f"/schedules/{sid}/deactivate", headers=_h(token))
        assert r.status_code == 200
        assert r.json()["is_active"] is False
        assert r.json()["next_run_at"] is None

    async def test_activate_sets_next_run(self, client):
        token   = await _register(client, "ac2@test.com")
        _, col  = await _make_collection(client, token)
        sid     = await _make_schedule(client, token, col)
        await client.post(f"/schedules/{sid}/deactivate", headers=_h(token))
        r = await client.post(f"/schedules/{sid}/activate", headers=_h(token))
        assert r.status_code == 200
        assert r.json()["is_active"] is True
        assert r.json()["next_run_at"] is not None

    async def test_activate_next_run_is_in_future(self, client):
        token   = await _register(client, "ac3@test.com")
        _, col  = await _make_collection(client, token)
        sid     = await _make_schedule(client, token, col)
        await client.post(f"/schedules/{sid}/deactivate", headers=_h(token))
        r = await client.post(f"/schedules/{sid}/activate", headers=_h(token))
        nxt = datetime.fromisoformat(r.json()["next_run_at"].replace("Z", "+00:00"))
        assert nxt > datetime.now(timezone.utc)

    async def test_update_is_active_false_clears_next_run(self, client):
        token   = await _register(client, "ac4@test.com")
        _, col  = await _make_collection(client, token)
        sid     = await _make_schedule(client, token, col)
        r = await client.patch(
            f"/schedules/{sid}",
            json={"is_active": False},
            headers=_h(token),
        )
        assert r.json()["next_run_at"] is None


# ══════════════════════════════════════════════════════════════════════════════
# 5. Execution history
# ══════════════════════════════════════════════════════════════════════════════

class TestScheduleHistory:

    async def test_history_empty_initially(self, client):
        token   = await _register(client, "hi1@test.com")
        _, col  = await _make_collection(client, token)
        sid     = await _make_schedule(client, token, col)
        r = await client.get(f"/schedules/{sid}/history", headers=_h(token))
        assert r.status_code == 200
        assert r.json() == []

    async def test_history_has_correct_fields(self, client):
        from app.services.runner_service import HttpResult
        token   = await _register(client, "hi2@test.com")
        _, col  = await _make_collection(client, token)
        # Add a request so the collection run can execute
        req = (await client.post(f"/collections/{col}/requests",
                                 json={"name": "R", "method": "GET",
                                       "url": "https://api.example.com"},
                                 headers=_h(token))).json()["id"]
        sid = await _make_schedule(client, token, col)

        # Simulate a scheduled run by manually creating one
        mock_http = HttpResult(status_code=200, headers={}, body='{}',
                               response_time_ms=50, error=None)
        with patch("app.services.runner_service.execute_http", return_value=mock_http):
            run_r = await client.post(f"/collections/{col}/run", json={}, headers=_h(token))

        r = await client.get(f"/schedules/{sid}/history", headers=_h(token))
        # Manual runs don't appear in scheduled history
        assert r.json() == []   # trigger_type='manual' filtered out


# ══════════════════════════════════════════════════════════════════════════════
# 6. Schedule firing (mocked DB session — scheduler uses AsyncSessionLocal)
# ══════════════════════════════════════════════════════════════════════════════

class TestScheduleFiring:

    async def test_fire_due_creates_run_and_updates_timestamps(self):
        from app.worker.scheduler import fire_due_schedules

        redis = fakeredis.FakeRedis(decode_responses=True)

        now = datetime.now(timezone.utc)
        sched = MagicMock()
        sched.id             = "sched-1"
        sched.collection_id  = "col-1"
        sched.environment_id = None
        sched.cron_expression = "0 * * * *"
        sched.last_run_at    = None
        sched.next_run_at    = now - timedelta(minutes=5)   # overdue

        run = MagicMock()
        run.id = "run-1"

        mock_session = AsyncMock()
        mock_session.add    = MagicMock()
        mock_session.flush  = AsyncMock()
        mock_session.commit = AsyncMock()

        # repo.find_due() returns the due schedule with workspace_id
        mock_repo = AsyncMock()
        mock_repo.find_due = AsyncMock(return_value=[(sched, "ws-1")])

        with patch("app.worker.scheduler.ScheduleRepository", return_value=mock_repo), \
             patch("app.worker.scheduler.TestRun", return_value=run):
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_cm.__aexit__  = AsyncMock(return_value=False)
            with patch("app.worker.scheduler.AsyncSessionLocal", return_value=mock_cm):
                fired = await fire_due_schedules(redis)

        assert fired == 1
        assert sched.last_run_at == sched.last_run_at   # was set
        # next_run_at should have been recomputed
        assert sched.next_run_at > now
        # run should have been enqueued
        from app.worker.queue import queue_length
        assert await queue_length(redis) == 1
        await redis.aclose()

    async def test_no_due_schedules_fires_zero(self):
        from app.worker.scheduler import fire_due_schedules
        redis = fakeredis.FakeRedis(decode_responses=True)

        mock_repo = AsyncMock()
        mock_repo.find_due = AsyncMock(return_value=[])

        mock_session = AsyncMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__  = AsyncMock(return_value=False)

        with patch("app.worker.scheduler.ScheduleRepository", return_value=mock_repo), \
             patch("app.worker.scheduler.AsyncSessionLocal", return_value=mock_cm):
            fired = await fire_due_schedules(redis)

        assert fired == 0
        await redis.aclose()

    async def test_schedule_loop_stops_on_shutdown(self):
        from app.worker.scheduler import schedule_loop
        redis    = fakeredis.FakeRedis(decode_responses=True)
        shutdown = __import__("asyncio").Event()
        shutdown.set()

        await __import__("asyncio").wait_for(
            schedule_loop(redis, shutdown), timeout=3.0
        )
        await redis.aclose()


# ══════════════════════════════════════════════════════════════════════════════
# 7. Validation
# ══════════════════════════════════════════════════════════════════════════════

class TestValidation:

    async def test_invalid_cron_rejected(self, client):
        token  = await _register(client, "vl1@test.com")
        _, col = await _make_collection(client, token)
        r = await client.post(
            f"/collections/{col}/schedules",
            json={"cron_expression": "not-a-cron"},
            headers=_h(token),
        )
        assert r.status_code == 422

    async def test_5_field_cron_required(self, client):
        token  = await _register(client, "vl2@test.com")
        _, col = await _make_collection(client, token)
        r = await client.post(
            f"/collections/{col}/schedules",
            json={"cron_expression": "0 * * *"},   # only 4 fields
            headers=_h(token),
        )
        assert r.status_code == 422

    async def test_too_frequent_minute_interval_accepted(self, client):
        """Every-minute runs are valid cron — no lower-bound restriction."""
        token  = await _register(client, "vl3@test.com")
        _, col = await _make_collection(client, token)
        r = await client.post(
            f"/collections/{col}/schedules",
            json={"cron_expression": "* * * * *"},
            headers=_h(token),
        )
        assert r.status_code == 201

    async def test_unknown_collection_returns_404(self, client):
        token = await _register(client, "vl4@test.com")
        r = await client.post(
            "/collections/nonexistent/schedules",
            json={"cron_expression": "0 9 * * *"},
            headers=_h(token),
        )
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 8. Auth enforcement
# ══════════════════════════════════════════════════════════════════════════════

class TestScheduleAuth:

    async def test_list_requires_auth(self, client):
        r = await client.get("/collections/any/schedules")
        assert r.status_code == 403

    async def test_create_requires_auth(self, client):
        r = await client.post("/collections/any/schedules",
                              json={"cron_expression": "0 9 * * *"})
        assert r.status_code == 403

    async def test_get_requires_auth(self, client):
        r = await client.get("/schedules/any-id")
        assert r.status_code == 403

    async def test_activate_requires_auth(self, client):
        r = await client.post("/schedules/any-id/activate")
        assert r.status_code == 403

    async def test_history_requires_auth(self, client):
        r = await client.get("/schedules/any-id/history")
        assert r.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# 9. Ownership
# ══════════════════════════════════════════════════════════════════════════════

class TestScheduleOwnership:

    async def _setup_two_users(self, client):
        owner = await _register(client, "own_sc1@test.com")
        other = await _register(client, "oth_sc1@test.com")
        _, col = await _make_collection(client, owner)
        sid = await _make_schedule(client, owner, col)
        return owner, other, col, sid

    async def test_other_user_cannot_list_schedules(self, client):
        owner, other, col, _ = await self._setup_two_users(client)
        r = await client.get(f"/collections/{col}/schedules", headers=_h(other))
        assert r.status_code == 404

    async def test_other_user_cannot_get_schedule(self, client):
        _, other, _, sid = await self._setup_two_users(client)
        r = await client.get(f"/schedules/{sid}", headers=_h(other))
        assert r.status_code == 404

    async def test_other_user_cannot_update_schedule(self, client):
        _, other, _, sid = await self._setup_two_users(client)
        r = await client.patch(f"/schedules/{sid}",
                               json={"cron_expression": "0 0 * * *"},
                               headers=_h(other))
        assert r.status_code == 404

    async def test_other_user_cannot_delete_schedule(self, client):
        _, other, _, sid = await self._setup_two_users(client)
        r = await client.delete(f"/schedules/{sid}", headers=_h(other))
        assert r.status_code == 404
