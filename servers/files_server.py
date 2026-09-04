"""Files System MCP server.

A plain FastMCP server exposed over streamable HTTP and wrapped in bearer
token auth. It replaces the Node based filesystem server, whose allowed
root was fixed at launch and therefore could not follow the active
project.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from core.config import settings
from servers import tools_files
from servers.auth import BearerAuthMiddleware
from servers.health import HealthMiddleware

SERVER_NAME = "files-system"


def build_mcp() -> FastMCP:
    """Create the FastMCP instance with every file tool registered."""
    mcp = FastMCP(SERVER_NAME)
    tools_files.register(mcp)
    return mcp


def build_app():
    """Return the authenticated ASGI app for this server."""
    mcp = build_mcp()
    mcp.settings.streamable_http_path = str(
        settings.get("servers", "http_path", default="/mcp")
    )
    # The tunnel forwards a public Host header, which the default DNS
    # rebinding protection would reject.
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )
    app = BearerAuthMiddleware(mcp.streamable_http_app(), name=SERVER_NAME)
    # Health sits outermost so readiness checks need no token.
    return HealthMiddleware(app, name=SERVER_NAME)
