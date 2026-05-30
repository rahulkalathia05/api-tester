"""
Redis-backed execution queue.

Main queue  — RPUSH / BLPOP list.  Worker pops jobs in FIFO order.
Retry queue — sorted set scored by next-attempt Unix timestamp.  The
              scheduler loop pops items whose score ≤ now and re-pushes
              them onto the main queue.
Retry counter — plain string keys runner:retry:{run_id} that track how
              many times a run has been attempted.

Atomicity note: INCR + EXPIRE are sent as a pipeline so the TTL is
always set even if the process is killed between the two commands.
"""
from __future__ import annotations

import json
import time
from typing import Any

import redis.asyncio as redis

from app.config import settings


# ── Main queue ────────────────────────────────────────────────────────────────

async def enqueue_run(redis_client: redis.Redis, run_id: str, **meta: Any) -> None:
    payload = json.dumps({"run_id": run_id, **meta})
    await redis_client.rpush(settings.RUN_QUEUE_KEY, payload)


async def dequeue_run(redis_client: redis.Redis, timeout: int = 5) -> dict | None:
    result = await redis_client.blpop([settings.RUN_QUEUE_KEY], timeout=timeout)
    if result is None:
        return None
    _, raw = result
    return json.loads(raw)


async def queue_length(redis_client: redis.Redis) -> int:
    return await redis_client.llen(settings.RUN_QUEUE_KEY)


# ── Retry counter ─────────────────────────────────────────────────────────────

def _retry_key(run_id: str) -> str:
    return f"{settings.RUN_RETRY_PREFIX}{run_id}"


async def get_retry_count(redis_client: redis.Redis, run_id: str) -> int:
    val = await redis_client.get(_retry_key(run_id))
    return int(val) if val else 0


async def increment_retry(redis_client: redis.Redis, run_id: str) -> int:
    """Atomically increment the retry counter and (re)set its TTL."""
    key = _retry_key(run_id)
    pipe = redis_client.pipeline()
    pipe.incr(key)
    pipe.expire(key, settings.RUN_RETRY_TTL)
    results = await pipe.execute()
    return int(results[0])


async def clear_retry_count(redis_client: redis.Redis, run_id: str) -> None:
    await redis_client.delete(_retry_key(run_id))


# ── Scheduled retry queue ─────────────────────────────────────────────────────

async def schedule_retry(
    redis_client: redis.Redis,
    run_id: str,
    delay_seconds: int,
) -> None:
    """Add run_id to the sorted set with score = now + delay."""
    score = time.time() + delay_seconds
    await redis_client.zadd(settings.RUN_SCHEDULED_KEY, {run_id: score})


async def pop_due_retries(redis_client: redis.Redis) -> list[str]:
    """
    Return all run_ids whose scheduled retry time has arrived and remove
    them from the sorted set atomically.
    """
    now = time.time()
    # ZRANGEBYSCORE from -inf to now, then ZREM to remove them
    members = await redis_client.zrangebyscore(
        settings.RUN_SCHEDULED_KEY, "-inf", now
    )
    if not members:
        return []
    await redis_client.zrem(settings.RUN_SCHEDULED_KEY, *members)
    return [m if isinstance(m, str) else m.decode() for m in members]


async def scheduled_count(redis_client: redis.Redis) -> int:
    return await redis_client.zcard(settings.RUN_SCHEDULED_KEY)
