"""
Cron expression utilities — thin wrapper around croniter.

All datetimes returned are timezone-aware (UTC).
"""
from __future__ import annotations

from datetime import datetime, timezone

from croniter import croniter


def validate_cron(expression: str) -> bool:
    """Return True if the expression is a valid 5-field cron string."""
    return croniter.is_valid(expression)


def next_after(expression: str, base: datetime) -> datetime:
    """
    Return the next UTC datetime after `base` at which `expression` fires.

    The returned datetime is always timezone-aware (UTC).
    """
    # croniter works with naive datetimes; strip tz, compute, re-attach
    naive_base = base.replace(tzinfo=None)
    it         = croniter(expression, naive_base)
    naive_next = it.get_next(datetime)
    return naive_next.replace(tzinfo=timezone.utc)


def previous_before(expression: str, base: datetime) -> datetime:
    """Return the most recent past fire time before `base`."""
    naive_base = base.replace(tzinfo=None)
    it         = croniter(expression, naive_base)
    naive_prev = it.get_prev(datetime)
    return naive_prev.replace(tzinfo=timezone.utc)


# ── Human-readable description ────────────────────────────────────────────────
# Maps common patterns to plain-English descriptions.
# Falls back to the raw expression for unrecognised patterns.

_PATTERNS: dict[str, str] = {
    "*/15 * * * *": "Every 15 minutes",
    "*/30 * * * *": "Every 30 minutes",
    "0 * * * *":    "Every hour",
    "0 */2 * * *":  "Every 2 hours",
    "0 */3 * * *":  "Every 3 hours",
    "0 */6 * * *":  "Every 6 hours",
    "0 */12 * * *": "Every 12 hours",
    "0 0 * * *":    "Daily at midnight (UTC)",
    "0 9 * * *":    "Daily at 09:00 UTC",
    "0 12 * * *":   "Daily at noon (UTC)",
    "0 18 * * *":   "Daily at 18:00 UTC",
    "0 9 * * 1":    "Every Monday at 09:00 UTC",
    "0 9 * * 0":    "Every Sunday at 09:00 UTC",
    "0 0 1 * *":    "First day of every month",
    "0 0 * * 0":    "Every Sunday at midnight (UTC)",
}


def cron_description(expression: str) -> str:
    """Return a plain-English description of a cron expression."""
    return _PATTERNS.get(expression.strip(), expression)
