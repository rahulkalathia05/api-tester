"""
Centralised Redis key factory.

Every key the application touches is defined here so grep finds them all
and accidental typos are caught at import time rather than at runtime.
"""


def blacklist_key(jti: str) -> str:
    """Access-token JTI blacklist (set on logout)."""
    return f"auth:blacklist:{jti}"


def refresh_key(jti: str) -> str:
    """Refresh-token whitelist (present = valid)."""
    return f"auth:refresh:{jti}"


def rate_limit_key(prefix: str, identifier: str) -> str:
    return f"ratelimit:{prefix}:{identifier}"


def run_stream_key(run_id: str) -> str:
    """Pub/sub channel for live SSE updates of a test run."""
    return f"run:stream:{run_id}"


def run_lock_key(run_id: str) -> str:
    """Distributed lock — prevents duplicate concurrent execution of one run."""
    return f"run:lock:{run_id}"
