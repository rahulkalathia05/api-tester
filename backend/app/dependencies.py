from typing import Annotated, AsyncGenerator

import redis.asyncio as redis
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.redis_client import get_redis_client
from app.core.redis_keys import blacklist_key
from app.core.security import decode_access_token
from app.models.user import User
from app.repositories.user_repo import UserRepository

bearer = HTTPBearer()


# ── Database ───────────────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a session; auto-commit on success, auto-rollback on error."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Redis ──────────────────────────────────────────────────────────────────────

def get_redis() -> redis.Redis:
    return get_redis_client()


# ── Auth ───────────────────────────────────────────────────────────────────────

async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis_client: Annotated[redis.Redis, Depends(get_redis)],
) -> User:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
    )
    try:
        payload = decode_access_token(credentials.credentials)
        user_id: str = payload["sub"]
        jti: str = payload["jti"]
    except (JWTError, KeyError):
        raise exc

    if await redis_client.get(blacklist_key(jti)):
        raise exc

    user = await UserRepository(db).get(user_id)
    if user is None:
        raise exc
    return user


# ── Annotated shorthand aliases ────────────────────────────────────────────────

DBDep        = Annotated[AsyncSession, Depends(get_db)]
RedisDep     = Annotated[redis.Redis, Depends(get_redis)]
CurrentUser  = Annotated[User, Depends(get_current_user)]
