from __future__ import annotations

import hmac

from fastapi.security.utils import get_authorization_scheme_param
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def is_authenticated(authorization: str | None, token: str | None) -> bool:
    if token is None:
        return True
    scheme, credentials = get_authorization_scheme_param(authorization)
    return scheme.lower() == "bearer" and hmac.compare_digest(
        credentials.encode(), token.encode("ascii")
    )


class ServerVersionMiddleware:
    """Advertise the application version only to authenticated API callers."""

    def __init__(self, app: ASGIApp, *, version: str, token: str | None) -> None:
        self.app = app
        self.version = version
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or not scope["path"].startswith("/api/")
            or not is_authenticated(Headers(scope=scope).get("authorization"), self.token)
        ):
            await self.app(scope, receive, send)
            return

        async def send_version(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Labtasker-Server-Version"] = self.version
            await send(message)

        await self.app(scope, receive, send_version)


class RequestBodyLimitMiddleware:
    """Buffer one bounded request body before entering the application."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared_length = _content_length(scope)
        if declared_length is not None and declared_length > self.max_bytes:
            await self._reject(scope, receive, send)
            return

        messages: list[Message] = []
        received_bytes = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break
            received_bytes += len(message.get("body", b""))
            if received_bytes > self.max_bytes:
                await self._reject(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        index = 0

        async def replay() -> Message:
            nonlocal index
            if index < len(messages):
                message = messages[index]
                index += 1
                return message
            return await receive()

        await self.app(scope, replay, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "request_too_large",
                    "message": "Request body exceeds the 1 MiB limit.",
                    "details": {"max_bytes": self.max_bytes},
                }
            },
        )
        await response(scope, receive, send)


def _content_length(scope: Scope) -> int | None:
    for name, raw_value in scope.get("headers", []):
        if name.lower() != b"content-length":
            continue
        try:
            value = int(raw_value)
        except ValueError:
            return None
        return value if value >= 0 else None
    return None
