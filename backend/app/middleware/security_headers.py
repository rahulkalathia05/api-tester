from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import settings

_BASE_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"x-xss-protection", b"1; mode=block"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
]

_HSTS = (b"strict-transport-security", b"max-age=31536000; includeSubDomains")


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        extra = [] if settings.DEBUG else [_HSTS]
        self._headers = _BASE_HEADERS + extra

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = self._headers

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                merged = list(message.get("headers", [])) + headers
                message = {**message, "headers": merged}
            await send(message)

        await self.app(scope, receive, send_wrapper)
