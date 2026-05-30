import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.config import settings

# ── Passwords ──────────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(
        plain.encode(), bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)
    ).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# Pre-computed dummy hash — used when no user is found during login so the
# bcrypt timing is constant and email enumeration via timing is prevented.
DUMMY_HASH: str = bcrypt.hashpw(
    b"dummy-timing-prevention",
    bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS),
).decode()


# ── JWT ────────────────────────────────────────────────────────────────────────
# access  — stateless, verified by signature + expiry
# refresh — stateful, jti must be in Redis to be valid
# iss     — issuer claim prevents cross-service token reuse


def create_access_token(user_id: str) -> tuple[str, str]:
    """Return (encoded_jwt, jti)."""
    jti = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    payload = {
        "iss": settings.JWT_ISSUER,
        "sub": user_id,
        "jti": jti,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM), jti


def create_refresh_token(user_id: str) -> tuple[str, str]:
    """Return (encoded_jwt, jti). Store jti in Redis to make it valid."""
    jti = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    payload = {
        "iss": settings.JWT_ISSUER,
        "sub": user_id,
        "jti": jti,
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(days=settings.JWT_REFRESH_EXPIRE_DAYS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM), jti


def decode_token(token: str) -> dict:
    """Decode + verify signature, expiry, and issuer."""
    return jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        issuer=settings.JWT_ISSUER,
    )


def decode_access_token(token: str) -> dict:
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise JWTError("Not an access token")
    return payload


def decode_refresh_token(token: str) -> dict:
    payload = decode_token(token)
    if payload.get("type") != "refresh":
        raise JWTError("Not a refresh token")
    return payload
