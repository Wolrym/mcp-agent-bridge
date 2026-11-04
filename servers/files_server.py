"""Files System MCP server.

A plain FastMCP server exposed over streamable HTTP behind bearer token
auth. It replaces the Node based filesystem server, whose allowed root was
fixed at launch and therefore could not follow the active project.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from servers import tools_files
from servers.common import build_http_app

SERVER_NAME = "files-system"


def build_mcp() -> FastMCP:
    """Create the FastMCP instance with every file tool registered."""
    mcp = FastMCP(SERVER_NAME, log_level="WARNING")
    tools_files.register(mcp)
    return mcp


def build_app():
    """Return the authenticated ASGI app for this server."""
    return build_http_app(build_mcp(), SERVER_NAME)
