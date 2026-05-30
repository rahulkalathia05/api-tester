import logging

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("app.errors")


def _request_id(request: Request) -> str:
    try:
        return request.state.request_id
    except AttributeError:
        return "-"


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = exc.errors()
    first = errors[0] if errors else {}
    loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
    msg = first.get("msg", "Validation error")
    detail = f"{loc}: {msg}" if loc else msg

    logger.warning(
        "Validation error on %s %s: %s",
        request.method,
        request.url.path,
        detail,
        extra={"request_id": _request_id(request)},
    )
    return JSONResponse(
        status_code=422,
        content={"detail": detail, "code": "VALIDATION_ERROR"},
    )


async def http_exception_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
    level = logging.WARNING if exc.status_code < 500 else logging.ERROR
    logger.log(
        level,
        "HTTP %d on %s %s: %s",
        exc.status_code,
        request.method,
        request.url.path,
        exc.detail,
        extra={"request_id": _request_id(request)},
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": _status_code(exc.status_code)},
        headers=getattr(exc, "headers", None),
    )


async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    logger.exception(
        "Unhandled exception on %s %s",
        request.method,
        request.url.path,
        extra={"request_id": _request_id(request), "exc_type": type(exc).__name__},
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "code": "INTERNAL_ERROR"},
    )


def _status_code(status: int) -> str:
    return {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
        500: "INTERNAL_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }.get(status, "ERROR")
