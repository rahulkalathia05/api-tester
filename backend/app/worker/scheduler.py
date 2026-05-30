"""
Cron-based schedule firing loop.

Runs inside the worker process alongside _job_loop and _retry_loop.

Every POLL_INTERVAL seconds:
  1. Query for active ScheduledRun rows whose next_run_at ≤ now.
  2. For each due schedule:
       a. Create a TestRun with trigger_type='scheduled'.
       b. Enqueue the run.
       c. Update last_run_at = now, next_run_at = croniter(cron, now).next.
  3. Commit.

The poll interval is 60 seconds — fine-grained enough for minute-level
precision while keeping DB load negligible.

Idempotency note: if the worker is killed between step 2 and step 3, the
next_run_at is NOT updated, so the schedule will fire again on the next
poll.  This means a schedule might fire twice within one interval in a crash
scenario.  For the vast majority of use-cases (hourly/daily/weekly), this
is harmless.  A distributed lock (Redis SETNX) would eliminate it entirely
if strict exactly-once delivery were required.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.core.database import AsyncSessionLocal
from app.models.scheduled_run import ScheduledRun
from app.models.test_run import TestRun
from app.repositories.schedule_repo import ScheduleRepository
from app.utils.cron import next_after
from app.worker.queue import enqueue_run

logger = logging.getLogger("app.worker.scheduler")

POLL_INTERVAL = 60   # seconds between checks


async def fire_due_schedules(redis: aioredis.Redis) -> int:
    """
    Fire all due schedules.  Opens its own DB session.
    Returns the number of runs enqueued.
    """
    now   = datetime.now(timezone.utc)
    fired = 0

    async with AsyncSessionLocal() as session:
        repo = ScheduleRepository(session)
        due  = await repo.find_due(now)

        if not due:
            return 0

        for schedule, workspace_id in due:
            run = TestRun(
                workspace_id=workspace_id,
                collection_id=schedule.collection_id,
                environment_id=schedule.environment_id,
                trigger_type="scheduled",
                status="pending",
            )
            session.add(run)
            await session.flush()

            await enqueue_run(redis, run.id, collection_id=schedule.collection_id)

            schedule.last_run_at = now
            schedule.next_run_at = next_after(schedule.cron_expression, now)

            logger.info(
                "Fired schedule %s → run %s (next: %s)",
                schedule.id, run.id, schedule.next_run_at.isoformat(),
                extra={
                    "schedule_id": schedule.id,
                    "run_id":      run.id,
                    "cron":        schedule.cron_expression,
                    "next_run_at": schedule.next_run_at.isoformat(),
                },
            )
            fired += 1

        await session.commit()

    return fired


async def schedule_loop(redis: aioredis.Redis, shutdown: asyncio.Event) -> None:
    """
    Main scheduling loop — runs as a task in the worker event loop.

    Polls every POLL_INTERVAL seconds and fires due schedules.
    Responds to the shutdown event within 1 second.
    """
    logger.info("Schedule loop started (poll interval=%ds)", POLL_INTERVAL)

    while not shutdown.is_set():
        try:
            fired = await fire_due_schedules(redis)
            if fired:
                logger.info("Fired %d schedule(s)", fired, extra={"fired": fired})
        except Exception:
            logger.exception("Error in schedule loop")

        # Sleep in 1-second chunks for responsive shutdown
        for _ in range(POLL_INTERVAL):
            if shutdown.is_set():
                break
            await asyncio.sleep(1)

    logger.info("Schedule loop stopped")
