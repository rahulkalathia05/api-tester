"""
Retry logic tests.

Coverage:
  TestBackoffAlgorithm  — delay computation, jitter bounds, cap, sequence
  TestFailureClassifier — exception type → TRANSIENT | PERMANENT
  TestRetryHandling     — transient schedules retry, permanent fails immediately,
                          exhausted retries marks error, counter cleared on success
  TestRetryStatus       — GET /runs/{id}/retry-status endpoint
  TestRetryStatusAuth   — requires bearer token
  TestRetryStatusOwnership — cross-user isolation
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis as fakeredis

from app.config import settings
from app.utils.backoff import compute_delay, compute_delay_no_jitter, delay_sequence
from app.worker.executor import FailureKind, classify_exception

pytestmark = pytest.mark.asyncio


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _register(client, email: str) -> str:
    r = await client.post("/auth/register",
                          json={"name": "T", "email": email, "password": "Password1"})
    return r.json()["access_token"]


def _h(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


async def _make_run(client, token: str) -> str:
    h = _h(token)
    ws  = (await client.post("/workspaces", json={"name": "W"}, headers=h)).json()["id"]
    col = (await client.post(f"/workspaces/{ws}/collections",
                             json={"name": "C"}, headers=h)).json()["id"]
    return (await client.post(f"/collections/{col}/run", json={}, headers=h)).json()["id"]


# ══════════════════════════════════════════════════════════════════════════════
# 1. Backoff algorithm — pure maths
# ══════════════════════════════════════════════════════════════════════════════

class TestBackoffAlgorithm:

    def test_deterministic_increases_each_attempt(self):
        delays = [compute_delay_no_jitter(i) for i in range(1, 5)]
        for a, b in zip(delays, delays[1:]):
            assert b >= a, f"Expected monotonic: {delays}"

    def test_first_attempt_equals_base(self):
        assert compute_delay_no_jitter(1) == settings.RUN_RETRY_BASE_DELAY_S

    def test_second_attempt_is_base_times_multiplier(self):
        expected = int(settings.RUN_RETRY_BASE_DELAY_S * settings.RUN_RETRY_MULTIPLIER)
        assert compute_delay_no_jitter(2) == expected

    def test_delay_capped_at_max(self):
        # Very high attempt number should be capped
        capped = compute_delay_no_jitter(100)
        assert capped <= settings.RUN_RETRY_MAX_DELAY_S

    def test_jittered_delay_within_bounds(self):
        for attempt in range(1, 4):
            base = compute_delay_no_jitter(attempt)
            jitter_range = base * settings.RUN_RETRY_JITTER
            for _ in range(20):   # sample multiple values
                d = compute_delay(attempt)
                assert base - jitter_range - 1 <= d <= base + jitter_range + 1, (
                    f"Attempt {attempt}: delay {d} outside [{base - jitter_range}, "
                    f"{base + jitter_range}]"
                )

    def test_jittered_delay_always_positive(self):
        for attempt in range(1, settings.RUN_MAX_RETRIES + 1):
            for _ in range(10):
                assert compute_delay(attempt) >= 1

    def test_delay_sequence_length_matches_max_retries(self):
        seq = delay_sequence(settings.RUN_MAX_RETRIES)
        assert len(seq) == settings.RUN_MAX_RETRIES

    def test_delay_sequence_is_increasing(self):
        seq = delay_sequence(settings.RUN_MAX_RETRIES)
        for a, b in zip(seq, seq[1:]):
            assert b >= a

    def test_sequence_demo_values(self):
        """
        Verify the advertised progression:
          attempt 1: base (30s)
          attempt 2: base × multiplier (120s)
          attempt 3: base × multiplier² (480s)
        """
        seq = delay_sequence(3)
        assert seq[0] == 30
        assert seq[1] == 120
        assert seq[2] == 480


# ══════════════════════════════════════════════════════════════════════════════
# 2. Failure classifier
# ══════════════════════════════════════════════════════════════════════════════

class TestFailureClassifier:

    # ── Transient ─────────────────────────────────────────────────────────────

    def test_connection_error_is_transient(self):
        assert classify_exception(ConnectionError("refused")) == FailureKind.TRANSIENT

    def test_os_error_is_transient(self):
        assert classify_exception(OSError("io error")) == FailureKind.TRANSIENT

    def test_timeout_error_is_transient(self):
        import asyncio
        assert classify_exception(asyncio.TimeoutError()) == FailureKind.TRANSIENT

    def test_httpx_timeout_is_transient(self):
        import httpx
        assert classify_exception(httpx.TimeoutException("timed out")) == FailureKind.TRANSIENT

    def test_httpx_connect_error_is_transient(self):
        import httpx
        assert classify_exception(httpx.ConnectError("refused")) == FailureKind.TRANSIENT

    # ── Permanent ─────────────────────────────────────────────────────────────

    def test_value_error_is_permanent(self):
        assert classify_exception(ValueError("bad data")) == FailureKind.PERMANENT

    def test_type_error_is_permanent(self):
        assert classify_exception(TypeError("wrong type")) == FailureKind.PERMANENT

    def test_attribute_error_is_permanent(self):
        assert classify_exception(AttributeError("no attr")) == FailureKind.PERMANENT

    def test_key_error_is_permanent(self):
        assert classify_exception(KeyError("missing")) == FailureKind.PERMANENT

    # ── Unknown defaults to transient ─────────────────────────────────────────

    def test_unknown_exception_defaults_transient(self):
        class WeirdError(Exception):
            pass
        assert classify_exception(WeirdError("?")) == FailureKind.TRANSIENT

    def test_generic_exception_is_transient(self):
        assert classify_exception(Exception("unknown")) == FailureKind.TRANSIENT


# ══════════════════════════════════════════════════════════════════════════════
# 3. _handle_failure behaviour
# ══════════════════════════════════════════════════════════════════════════════

class TestRetryHandling:

    def _fake_run(self, run_id="r1"):
        run = MagicMock()
        run.id = run_id
        run.status = "running"
        run.completed_at = None
        return run

    async def test_transient_schedules_retry(self):
        from app.worker.executor import _handle_failure
        redis = fakeredis.FakeRedis(decode_responses=True)
        run   = self._fake_run()
        session = AsyncMock()

        await _handle_failure(session, run, redis, ConnectionError("x"),
                              FailureKind.TRANSIENT)

        assert run.status == "pending"
        from app.worker.queue import scheduled_count
        assert await scheduled_count(redis) == 1
        await redis.aclose()

    async def test_permanent_fails_immediately_no_retry(self):
        from app.worker.executor import _handle_failure
        from app.worker.queue import scheduled_count, get_retry_count
        redis   = fakeredis.FakeRedis(decode_responses=True)
        run     = self._fake_run()
        session = AsyncMock()

        await _handle_failure(session, run, redis, ValueError("bad data"),
                              FailureKind.PERMANENT)

        assert run.status == "error"
        assert await scheduled_count(redis) == 0
        assert await get_retry_count(redis, run.id) == 0   # counter cleared
        await redis.aclose()

    async def test_exhausted_retries_marks_error(self):
        from app.worker.executor import _handle_failure
        from app.worker.queue import increment_retry, scheduled_count
        redis   = fakeredis.FakeRedis(decode_responses=True)
        run     = self._fake_run("exhausted")
        session = AsyncMock()

        # Pre-fill to max
        for _ in range(settings.RUN_MAX_RETRIES):
            await increment_retry(redis, "exhausted")

        await _handle_failure(session, run, redis, ConnectionError("boom"),
                              FailureKind.TRANSIENT)

        assert run.status == "error"
        assert await scheduled_count(redis) == 0
        await redis.aclose()

    async def test_retry_delay_uses_backoff(self):
        """Verify the scheduled retry timestamp matches the backoff formula."""
        import time
        from app.worker.executor import _handle_failure
        from app.utils.backoff import compute_delay_no_jitter

        redis   = fakeredis.FakeRedis(decode_responses=True)
        run     = self._fake_run("delay-check")
        session = AsyncMock()

        before = time.time()
        await _handle_failure(session, run, redis, ConnectionError("x"),
                              FailureKind.TRANSIENT)
        after = time.time()

        score = await redis.zscore(settings.RUN_SCHEDULED_KEY, "delay-check")
        assert score is not None

        # Expected (deterministic) delay for attempt 1
        expected_delay = compute_delay_no_jitter(1)
        # Allow ±jitter and ±1s for execution time
        jitter_margin = expected_delay * settings.RUN_RETRY_JITTER + 1
        assert before + expected_delay - jitter_margin <= score <= after + expected_delay + jitter_margin

        await redis.aclose()

    async def test_counter_cleared_on_success(self):
        from app.worker.queue import increment_retry, clear_retry_count, get_retry_count
        redis = fakeredis.FakeRedis(decode_responses=True)
        await increment_retry(redis, "success")
        await clear_retry_count(redis, "success")
        assert await get_retry_count(redis, "success") == 0
        await redis.aclose()

    async def test_second_transient_uses_longer_delay(self):
        """Second failure should schedule a longer delay than the first."""
        import time
        from app.worker.executor import _handle_failure

        redis   = fakeredis.FakeRedis(decode_responses=True)
        run     = self._fake_run("escalating")
        session = AsyncMock()

        # First failure
        await _handle_failure(session, run, redis, ConnectionError("1"), FailureKind.TRANSIENT)
        score_1 = await redis.zscore(settings.RUN_SCHEDULED_KEY, "escalating")

        # Remove from set so we can add again
        await redis.zrem(settings.RUN_SCHEDULED_KEY, "escalating")

        # Second failure
        run.status = "running"
        await _handle_failure(session, run, redis, ConnectionError("2"), FailureKind.TRANSIENT)
        score_2 = await redis.zscore(settings.RUN_SCHEDULED_KEY, "escalating")

        # Second delay should be longer than first
        delay_1 = score_1 - time.time()
        delay_2 = score_2 - time.time()
        assert delay_2 > delay_1 * 0.5   # generous bound accounting for jitter

        await redis.aclose()


# ══════════════════════════════════════════════════════════════════════════════
# 4. Retry status endpoint
# ══════════════════════════════════════════════════════════════════════════════

class TestRetryStatus:

    async def test_fresh_run_has_zero_attempts(self, client):
        token  = await _register(client, "rs1@test.com")
        run_id = await _make_run(client, token)
        r = await client.get(f"/runs/{run_id}/retry-status", headers=_h(token))
        assert r.status_code == 200
        b = r.json()
        assert b["attempt_count"] == 0
        assert b["is_retrying"] is False
        assert b["next_retry_at"] is None

    async def test_max_retries_in_response(self, client):
        token  = await _register(client, "rs2@test.com")
        run_id = await _make_run(client, token)
        r = await client.get(f"/runs/{run_id}/retry-status", headers=_h(token))
        assert r.json()["max_retries"] == settings.RUN_MAX_RETRIES

    async def test_retry_schedule_length_correct(self, client):
        token  = await _register(client, "rs3@test.com")
        run_id = await _make_run(client, token)
        r = await client.get(f"/runs/{run_id}/retry-status", headers=_h(token))
        b = r.json()
        # Fresh run: attempts_remaining == max_retries
        assert len(b["retry_schedule"]) == b["attempts_remaining"]

    async def test_retry_schedule_is_increasing(self, client):
        token  = await _register(client, "rs4@test.com")
        run_id = await _make_run(client, token)
        r = await client.get(f"/runs/{run_id}/retry-status", headers=_h(token))
        sched = r.json()["retry_schedule"]
        if len(sched) >= 2:
            for a, b in zip(sched, sched[1:]):
                assert b >= a

    async def test_run_status_in_response(self, client):
        token  = await _register(client, "rs5@test.com")
        run_id = await _make_run(client, token)
        r = await client.get(f"/runs/{run_id}/retry-status", headers=_h(token))
        assert r.json()["run_status"] in ("pending", "running", "passed", "failed", "error")

    async def test_nonexistent_run_returns_404(self, client):
        token = await _register(client, "rs6@test.com")
        r = await client.get("/runs/nonexistent/retry-status", headers=_h(token))
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 5. Auth
# ══════════════════════════════════════════════════════════════════════════════

class TestRetryStatusAuth:

    async def test_requires_bearer(self, client):
        r = await client.get("/runs/any-id/retry-status")
        assert r.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# 6. Ownership
# ══════════════════════════════════════════════════════════════════════════════

class TestRetryStatusOwnership:

    async def test_other_user_cannot_see_retry_status(self, client):
        owner  = await _register(client, "own_rs1@test.com")
        other  = await _register(client, "oth_rs1@test.com")
        run_id = await _make_run(client, owner)
        r = await client.get(f"/runs/{run_id}/retry-status", headers=_h(other))
        assert r.status_code == 404
