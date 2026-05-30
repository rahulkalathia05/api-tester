from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials

from app.core.rate_limit import rate_limit
from app.dependencies import CurrentUser, DBDep, RedisDep, bearer
from app.schemas.auth import (
    AuthResponse,
    ChangePasswordRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    UpdateProfileRequest,
    UserOut,
)
from app.services.auth_service import AuthService, revoke_tokens
from app.services.user_service import UserService

router = APIRouter()

_rl_login     = rate_limit("auth:login",     limit=10, window=60)
_rl_register  = rate_limit("auth:register",  limit=5,  window=60)
_rl_refresh   = rate_limit("auth:refresh",   limit=20, window=60)
_rl_change_pw = rate_limit("auth:change_pw", limit=5,  window=60)


# ── Token operations — need both DB and Redis ─────────────────────────────────

@router.post("/register", response_model=AuthResponse, status_code=201,
             dependencies=[_rl_register])
async def register(body: RegisterRequest, db: DBDep, redis: RedisDep) -> AuthResponse:
    return await AuthService(db, redis).register(body)


@router.post("/login", response_model=AuthResponse, dependencies=[_rl_login])
async def login(body: LoginRequest, db: DBDep, redis: RedisDep) -> AuthResponse:
    return await AuthService(db, redis).login(body)


@router.post("/refresh", response_model=AuthResponse, dependencies=[_rl_refresh])
async def refresh(body: RefreshRequest, db: DBDep, redis: RedisDep) -> AuthResponse:
    return await AuthService(db, redis).refresh(body.refresh_token)


@router.post("/logout", status_code=204)
async def logout(
    body: LogoutRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
    redis: RedisDep,
) -> None:
    # Logout is a pure Redis operation — no database session needed.
    await revoke_tokens(credentials.credentials, body.refresh_token, redis)


# ── Profile operations — DB only, no Redis ────────────────────────────────────

@router.get("/me", response_model=UserOut)
async def me(current_user: CurrentUser) -> UserOut:
    return UserOut.model_validate(current_user)


@router.patch("/me", response_model=UserOut)
async def update_me(
    body: UpdateProfileRequest,
    current_user: CurrentUser,
    db: DBDep,
) -> UserOut:
    return await UserService(db).update_profile(current_user, body)


@router.post("/change-password", status_code=204, dependencies=[_rl_change_pw])
async def change_password(
    body: ChangePasswordRequest,
    current_user: CurrentUser,
    db: DBDep,
) -> None:
    await UserService(db).change_password(current_user, body)
