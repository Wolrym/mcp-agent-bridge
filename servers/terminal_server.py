"""Terminal MCP server.

Runs shell commands and serves project context and skills, over streamable
HTTP behind bearer token auth.

Security note: this server executes arbitrary commands with the rights of
the user running it. It must never be reachable without a valid token.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from servers import tools_terminal
from servers.common import build_http_app

SERVER_NAME = "terminal"


def build_mcp() -> FastMCP:
    """Create the FastMCP instance with every terminal tool registered."""
    mcp = FastMCP(SERVER_NAME, log_level="WARNING")
    tools_terminal.register(mcp)
    return mcp


def build_app():
    """Return the authenticated ASGI app for this server."""
    return build_http_app(build_mcp(), SERVER_NAME)
