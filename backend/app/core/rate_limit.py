from fastapi import Depends, HTTPException, Request, status
from app.config import settings
from app.dependencies import RedisDep

_INCR_LUA = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""


def rate_limit(key_prefix: str, limit: int, window: int) -> Depends:
    """
    Per-IP fixed-window rate limiter.

    Usage:
        @router.post("/login", dependencies=[rate_limit("auth:login", 10, 60)])
    """
    async def _check(request: Request, redis: RedisDep) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        ip = request.client.host if request.client else "unknown"
        key = f"ratelimit:{key_prefix}:{ip}"

        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window)

        if count > limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: {limit} requests per {window}s.",
                headers={"Retry-After": str(window)},
            )

    return Depends(_check)
