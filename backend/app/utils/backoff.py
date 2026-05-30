"""
Exponential backoff with full jitter.

Algorithm (AWS "Full Jitter" pattern):
  base_delay = min(BASE * MULTIPLIER^(attempt-1), MAX_DELAY)
  actual_delay = random.uniform(0, base_delay) if jitter else base_delay

"Full jitter" spreads retries across the entire [0, cap] window, which
significantly reduces thundering-herd effects when many workers retry
simultaneously after a downstream outage.

Reference: https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/

Example with defaults (base=30, multiplier=4, max=3600, jitter=0.2):
  attempt 1:  base=30s     → actual ≈ 24–36s
  attempt 2:  base=120s    → actual ≈ 96–144s
  attempt 3:  base=480s    → actual ≈ 384–576s
  attempt 4+: base=3600s   → actual ≈ 2880–3600s  (capped)
"""
from __future__ import annotations

import random

from app.config import settings


def compute_delay(attempt: int) -> int:
    """
    Return the delay in seconds for the given attempt number (1-based).

    Uses the four global config parameters:
      RUN_RETRY_BASE_DELAY_S  — base seconds
      RUN_RETRY_MULTIPLIER    — growth factor per attempt
      RUN_RETRY_MAX_DELAY_S   — ceiling
      RUN_RETRY_JITTER        — fractional jitter range (0.2 = ±20%)

    Always returns at least 1 second.
    """
    base  = settings.RUN_RETRY_BASE_DELAY_S * (settings.RUN_RETRY_MULTIPLIER ** (attempt - 1))
    cap   = min(base, settings.RUN_RETRY_MAX_DELAY_S)
    jitter = cap * settings.RUN_RETRY_JITTER
    delay  = cap + random.uniform(-jitter, jitter)
    return max(1, int(delay))


def compute_delay_no_jitter(attempt: int) -> int:
    """
    Deterministic version (no random component) — used in tests and logging
    to show the "expected" delay without the randomised spread.
    """
    base = settings.RUN_RETRY_BASE_DELAY_S * (settings.RUN_RETRY_MULTIPLIER ** (attempt - 1))
    return max(1, int(min(base, settings.RUN_RETRY_MAX_DELAY_S)))


def delay_sequence(max_retries: int) -> list[int]:
    """Return the deterministic delay for each attempt — useful for docs/UI."""
    return [compute_delay_no_jitter(i + 1) for i in range(max_retries)]
