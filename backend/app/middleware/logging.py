from __future__ import annotations

import logging
import time
import uuid

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("app.access")


class RequestLoggingMiddleware:
    """
    Raw ASGI middleware — safe with SSE streaming (no buffering).

    Adds to every request:
      - 8-char hex correlation ID attached to scope["state"]["request_id"]
      - X-Request-ID response header
      - Structured access log line on response.start
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        request_id = uuid.uuid4().hex[:8]

        # scope["state"] must be a plain dict — Starlette wraps it in State()
        # on first access of request.state.  Passing a State instance would
        # create State(State()), making _state non-subscriptable.
        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id

        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000)
            logger.info(
                "%s %s %d",
                request.method,
                request.url.path,
                status_code,
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": status_code,
                    "duration_ms": duration_ms,
                },
            )
