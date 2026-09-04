"""Bearer token authentication for the public MCP endpoints.

The servers are reachable from the internet through the tunnel, and the
terminal one can run arbitrary commands, so every request must carry the
token from the settings file.

This is a pure ASGI middleware rather than a Starlette
`BaseHTTPMiddleware`: the MCP transport streams responses, and
BaseHTTPMiddleware buffers them.
"""
from __future__ import annotations

import json
import secrets

from core import logs
from core.config import settings

# Accepted ways to present the token. Notion sends header-based auth, other
# clients may use a plain API key header.
BEARER_PREFIX = "bearer "
API_KEY_HEADERS = (b"x-api-key", b"x-auth-token")


def _extract_token(headers: list) -> str:
    lookup = {key.lower(): value for key, value in headers}
    raw = lookup.get(b"authorization", b"").decode("latin-1").strip()
    if raw.lower().startswith(BEARER_PREFIX):
        return raw[len(BEARER_PREFIX):].strip()
    for header in API_KEY_HEADERS:
        value = lookup.get(header)
        if value:
            return value.decode("latin-1").strip()
    return ""


class BearerAuthMiddleware:
    """Reject any HTTP request that does not carry the configured token."""

    def __init__(self, app, name: str, public_paths: tuple = ("/health",)) -> None:
        self.app = app
        self.name = name
        self.public_paths = public_paths

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope.get("path") in self.public_paths:
            await self.app(scope, receive, send)
            return

        if not settings.get("auth", "enabled", default=True):
            await self.app(scope, receive, send)
            return

        expected = str(settings.get("auth", "token", default=""))
        provided = _extract_token(scope.get("headers", []))

        if not expected:
            await self._deny(send, "Server has no auth token configured.")
            logs.log(self.name, "Rejected request: no token configured", level="error")
            return

        if not provided or not secrets.compare_digest(provided, expected):
            client = scope.get("client") or ("?", 0)
            logs.log(
                self.name,
                f"Rejected unauthenticated request from {client[0]}",
                level="warn",
            )
            await self._deny(send, "Missing or invalid authentication token.")
            return

        await self.app(scope, receive, send)

    async def _deny(self, send, message: str) -> None:
        body = json.dumps({"error": "unauthorized", "message": message}).encode()
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"www-authenticate", b"Bearer"),
            ],
        })
        await send({"type": "http.response.body", "body": body})
