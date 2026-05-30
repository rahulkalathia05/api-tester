from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.core.error_handlers import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.redis_client import get_redis_client
from app.middleware.logging import RequestLoggingMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.routers import auth, workspaces
from app.routers.analytics import router as analytics_router
from app.routers.collections import router as collections_router
from app.routers.environments import router as environments_router
from app.routers.import_ import router as import_router
from app.routers.runner import router as runner_router
from app.routers.schedules import router as schedules_router
from app.utils.logger import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


# ── Config validation ─────────────────────────────────────────────────────────

def _validate_config() -> None:
    if not settings.OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set — AI analysis features will fail")
    _DEV_SECRET = "change-me-in-production-use-a-long-random-string"
    if settings.JWT_SECRET == _DEV_SECRET:
        logger.warning("JWT_SECRET is a dev default — set a strong secret before deploying")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_config()
    logger.info("Starting %s", settings.APP_NAME)
    yield
    await engine.dispose()
    await get_redis_client().aclose()
    logger.info("Shutdown complete")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url=None,
    lifespan=lifespan,
)

# ── Middleware ────────────────────────────────────────────────────────────────
# Registration order is innermost-first; execution order is outermost-first.
# Effective order: RequestLogging → SecurityHeaders → CORS → app

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)

# ── Exception handlers ────────────────────────────────────────────────────────

app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(auth.router,        prefix="/auth",       tags=["auth"])
app.include_router(workspaces.router,  prefix="/workspaces", tags=["workspaces"])
app.include_router(collections_router)   # /workspaces/*/collections, /collections/*, /requests/*, /assertions/*
app.include_router(runner_router)        # /requests/*/run, /collections/*/run, /runs/*, /results/*
app.include_router(analytics_router)    # /workspaces/{id}/analytics
app.include_router(environments_router) # /workspaces/*/environments, /environments/*, /variables/*
app.include_router(schedules_router)    # /collections/*/schedules, /schedules/*, /schedules/presets
app.include_router(import_router)       # /workspaces/{id}/import/postman
# app.include_router(analytics.router,  prefix="/workspaces",   tags=["analytics"])


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["health"])
async def health() -> JSONResponse:
    checks: dict[str, str] = {}
    healthy = True

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = "error"
        healthy = False
        logger.error("Health: database unreachable — %r", exc)

    try:
        await get_redis_client().ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = "error"
        healthy = False
        logger.error("Health: redis unreachable — %r", exc)

    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "app": settings.APP_NAME,
            "checks": checks,
        },
    )
