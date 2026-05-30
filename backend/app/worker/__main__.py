"""
Background worker entry point.

Start with:
    python -m app.worker

Three concurrent tasks run inside the same event loop:

  1. _job_loop    — BLPOP the main queue and execute runs.
                   Concurrency is bounded by a semaphore (RUN_WORKER_CONCURRENCY).

  2. _retry_loop  — Every 10 s, pop due items from the sorted retry set
                   and push them back onto the main queue.

  3. _recovery    — Runs once at startup to re-queue stalled runs.

Shutdown
────────
SIGTERM or SIGINT sets _shutdown_event.  The job loop stops accepting new
jobs.  The semaphore ensures we wait for all in-flight jobs to finish before
the process exits (up to SHUTDOWN_TIMEOUT_SECONDS).
"""
import asyncio
import logging
import signal

from app.config import settings
from app.core.redis_client import get_redis_client
from app.utils.logger import setup_logging
from app.worker.executor import execute_collection_run, recover_stalled_runs
from app.worker.queue import dequeue_run, enqueue_run, pop_due_retries
from app.worker.scheduler import schedule_loop
from app.utils.backoff import delay_sequence

setup_logging()
logger = logging.getLogger("app.worker")

RETRY_POLL_INTERVAL  = 10    # seconds between retry-set sweeps
SHUTDOWN_TIMEOUT     = 30    # seconds to wait for in-flight jobs after SIGTERM


# ── Job processing loop ───────────────────────────────────────────────────────

async def _job_loop(
    redis,
    semaphore: asyncio.Semaphore,
    shutdown: asyncio.Event,
) -> None:
    """
    Pop jobs from the main queue and execute them under a concurrency limit.

    BLPOP with timeout=1 so the loop can check the shutdown event frequently.
    When shutdown is requested, drain remaining in-flight work (semaphore
    acquire will block until slots are free).
    """
    logger.info(
        "Job loop started (concurrency=%d)", settings.RUN_WORKER_CONCURRENCY
    )

    while not shutdown.is_set():
        job = await dequeue_run(redis, timeout=1)
        if job is None:
            continue

        run_id = job.get("run_id")
        if not run_id:
            logger.warning("Received malformed job (no run_id): %s", job)
            continue

        logger.info("Dequeued run %s", run_id, extra={"run_id": run_id})

        # Acquire a slot — blocks if RUN_WORKER_CONCURRENCY runs are already active
        await semaphore.acquire()

        async def _task(rid: str) -> None:
            try:
                await execute_collection_run(rid, redis)
            except Exception:
                logger.exception("Unhandled error in run %s", rid,
                                 extra={"run_id": rid})
            finally:
                semaphore.release()

        asyncio.create_task(_task(run_id))

    logger.info("Job loop: no longer accepting new jobs")


# ── Retry scheduler loop ──────────────────────────────────────────────────────

async def _retry_loop(redis, shutdown: asyncio.Event) -> None:
    """
    Every RETRY_POLL_INTERVAL seconds, pop run_ids from the sorted retry set
    whose scheduled time has passed and push them back onto the main queue.
    """
    logger.info("Retry scheduler started (poll interval=%ds)", RETRY_POLL_INTERVAL)

    while not shutdown.is_set():
        try:
            due = await pop_due_retries(redis)
            for run_id in due:
                await enqueue_run(redis, run_id)
                logger.info(
                    "Re-queued run %s after retry delay",
                    run_id, extra={"run_id": run_id},
                )
            if due:
                logger.info("Re-queued %d run(s) for retry", len(due))
        except Exception:
            logger.exception("Error in retry scheduler")

        # Sleep in short chunks so shutdown is responsive
        for _ in range(RETRY_POLL_INTERVAL):
            if shutdown.is_set():
                break
            await asyncio.sleep(1)

    logger.info("Retry scheduler stopped")


# ── Graceful shutdown ─────────────────────────────────────────────────────────

async def _drain(semaphore: asyncio.Semaphore) -> None:
    """
    Wait for all in-flight tasks to release their semaphore slots.

    Acquiring all N slots means zero tasks are running.
    Times out after SHUTDOWN_TIMEOUT seconds with a warning.
    """
    logger.info("Waiting up to %ds for in-flight runs to finish…", SHUTDOWN_TIMEOUT)
    n = settings.RUN_WORKER_CONCURRENCY
    try:
        await asyncio.wait_for(
            asyncio.gather(*[semaphore.acquire() for _ in range(n)]),
            timeout=SHUTDOWN_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Shutdown timeout — %d run(s) may still be in progress",
            n - semaphore._value,  # type: ignore[attr-defined]
        )


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    shutdown = asyncio.Event()

    def _handle_signal(*_) -> None:
        logger.info("Shutdown signal received")
        shutdown.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    redis     = get_redis_client()
    semaphore = asyncio.Semaphore(settings.RUN_WORKER_CONCURRENCY)

    # Recover any stalled runs from a previous crash before accepting new work
    recovered = await recover_stalled_runs(redis)
    if recovered:
        logger.info("Startup recovery: re-queued %d stalled run(s)", recovered)

    logger.info(
        "Worker ready (concurrency=%d, max_retries=%d, retry_delays=%s)",
        settings.RUN_WORKER_CONCURRENCY,
        settings.RUN_MAX_RETRIES,
        delay_sequence(settings.RUN_MAX_RETRIES),
    )

    await asyncio.gather(
        _job_loop(redis, semaphore, shutdown),
        _retry_loop(redis, shutdown),
        schedule_loop(redis, shutdown),    # fires cron schedules every 60 s
    )

    # Gracefully wait for in-flight tasks
    await _drain(semaphore)

    await redis.aclose()
    logger.info("Worker stopped cleanly")


if __name__ == "__main__":
    asyncio.run(main())
