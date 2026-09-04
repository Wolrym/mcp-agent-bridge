"""Terminal MCP server.

Runs shell commands and serves project context and skills. Exposed over
streamable HTTP behind bearer token auth.

Security note: this server executes arbitrary commands with the rights of
the user running it. It must never be reachable without a valid token.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from core.config import settings
from servers import tools_terminal
from servers.auth import BearerAuthMiddleware
from servers.health import HealthMiddleware

SERVER_NAME = "terminal"


def build_mcp() -> FastMCP:
    """Create the FastMCP instance with every terminal tool registered."""
    mcp = FastMCP(SERVER_NAME)
    tools_terminal.register(mcp)
    return mcp


def build_app():
    """Return the authenticated ASGI app for this server."""
    mcp = build_mcp()
    mcp.settings.streamable_http_path = str(
        settings.get("servers", "http_path", default="/mcp")
    )
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )
    app = BearerAuthMiddleware(mcp.streamable_http_app(), name=SERVER_NAME)
    # Health sits outermost so readiness checks need no token.
    return HealthMiddleware(app, name=SERVER_NAME)
