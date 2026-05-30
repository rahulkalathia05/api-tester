from datetime import datetime, timedelta, timezone

import redis.asyncio as redis
from fastapi import HTTPException, status
from jose import JWTError  # top-level — not deferred inside methods
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.redis_keys import blacklist_key, refresh_key
from app.core.security import (
    DUMMY_HASH,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest, UserOut

# Shared sentinel exceptions — identical wording ensures callers cannot infer
# which specific check failed (email enumeration / token type confusion).
_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid email or password",
)
_INVALID_TOKEN = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired token",
)


# ── Standalone function ────────────────────────────────────────────────────────
# logout is a pure Redis operation — it has no shared state with the service
# class, so it is a module-level function rather than a method.

async def revoke_tokens(
    access_token: str,
    refresh_token: str | None,
    redis_client: redis.Redis,
) -> None:
    """
    Blacklist the access JTI for its remaining lifetime and optionally delete
    the refresh JTI from the Redis whitelist.

    Silent on expired / malformed tokens — the client cannot do anything about
    a token that is already invalid.
    """
    try:
        payload = decode_access_token(access_token)
        jti = payload["jti"]
        exp = payload["exp"]
        ttl = max(1, int(exp - datetime.now(timezone.utc).timestamp()))
        await redis_client.setex(blacklist_key(jti), ttl, "1")
    except (JWTError, KeyError):
        pass  # already expired — nothing to blacklist

    if refresh_token:
        try:
            payload = decode_refresh_token(refresh_token)
            await redis_client.delete(refresh_key(payload["jti"]))
        except (JWTError, KeyError):
            pass


# ── Service class ──────────────────────────────────────────────────────────────

class AuthService:
    """
    Handles every operation that touches both the database and Redis:
    registration, login, and token refresh.

    Operations that only touch the database (profile update, password change)
    live in UserService and never receive a Redis client.

    Logout is a standalone function (revoke_tokens) because it is a pure
    Redis operation with no class-level state.
    """

    def __init__(self, db: AsyncSession, redis_client: redis.Redis) -> None:
        self._redis = redis_client
        self._repo = UserRepository(db)

    async def _issue_tokens(self, user: User) -> AuthResponse:
        """Create an access+refresh pair; whitelist the refresh JTI in Redis."""
        access_token, _ = create_access_token(user.id)
        refresh_token, refresh_jti = create_refresh_token(user.id)
        ttl = int(timedelta(days=settings.JWT_REFRESH_EXPIRE_DAYS).total_seconds())
        await self._redis.setex(refresh_key(refresh_jti), ttl, user.id)
        return AuthResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user=UserOut.model_validate(user),
        )

    async def register(self, body: RegisterRequest) -> AuthResponse:
        # Email is already lowercase — normalised by the schema validator.
        if await self._repo.email_exists(body.email):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )
        user = await self._repo.create(
            email=body.email,
            name=body.name.strip(),
            password_hash=hash_password(body.password),
        )
        return await self._issue_tokens(user)

    async def login(self, body: LoginRequest) -> AuthResponse:
        user = await self._repo.get_by_email(body.email)
        # Always run bcrypt — even when no user is found — so the response
        # time does not reveal whether the email is registered.
        candidate_hash = user.password_hash if user else DUMMY_HASH
        if not verify_password(body.password, candidate_hash) or user is None:
            raise _INVALID_CREDENTIALS
        return await self._issue_tokens(user)

    async def refresh(self, refresh_token: str) -> AuthResponse:
        try:
            payload = decode_refresh_token(refresh_token)
            jti: str = payload["jti"]
            user_id: str = payload["sub"]
        except (JWTError, KeyError):
            raise _INVALID_TOKEN

        if not await self._redis.get(refresh_key(jti)):
            raise _INVALID_TOKEN

        # Rotate: delete the old JTI before issuing a new pair so replaying
        # the same refresh token a second time always fails.
        await self._redis.delete(refresh_key(jti))

        user = await self._repo.get(user_id)
        if user is None:
            raise _INVALID_TOKEN

        return await self._issue_tokens(user)
