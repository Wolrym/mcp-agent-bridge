"""A tiny public /health endpoint in front of each MCP server.

The MCP transport itself only answers proper protocol requests, which
makes "is it up yet?" awkward to answer - both for the control panel and
for a human with a browser. This middleware intercepts one path and
replies with plain JSON, before authentication, so a readiness check never
needs the token.

It deliberately exposes nothing sensitive: server name, whether it is
serving, and which project is active.
"""
from __future__ import annotations

import json

from core import projects

HEALTH_PATH = "/health"


class HealthMiddleware:
    """Answer GET /health directly; pass everything else through."""

    def __init__(self, app, name: str, path: str = HEALTH_PATH) -> None:
        self.app = app
        self.name = name
        self.path = path

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http" or scope.get("path") != self.path:
            await self.app(scope, receive, send)
            return

        payload = {"status": "ok", "server": self.name}
        try:
            project = projects.active_project()
            payload["project"] = project["name"]
            payload["root"] = project["root"]
        except Exception:  # noqa: BLE001 - health must never fail loudly
            payload["project"] = None

        body = json.dumps(payload).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"),
            ],
        })
        await send({"type": "http.response.body", "body": body})
