"""Pieces both MCP servers share: tool registration and the HTTP app.

Every tool is registered through `install(mcp, source)`, which replaces
`mcp.tool` with a wrapper that:

* runs plain (sync) tools on a worker thread. FastMCP calls a sync tool
  inline on the event loop, and both servers share that loop, so one slow
  grep or a big read used to stall every other call and /health with it;
* serialises the tools that change files (`exclusive=True`), so parallel
  calls cannot interleave their undo-journal writes;
* logs one readable line per call - tool, the arguments that matter, how
  long it took, and the error if it failed - in place of the SDK's
  "Processing request of type CallToolRequest";
* tells the idle notifier that the agent is still busy, when a call
  starts and again when it ends;
* switches off FastMCP's structured output. With it on, every result is
  sent twice, as text and again as structuredContent, so the agent pays
  for each reply two times.
"""
from __future__ import annotations

import functools
import inspect
import logging
import threading
import time

import anyio

from core import logs, notifier
from core.config import settings

_exclusive = threading.Lock()

# Arguments whose value is bulky or private: logged by size only.
_BULKY = {"content", "old_string", "new_string", "data"}

# The SDK logs every request at INFO, which buried the useful lines.
for _name in ("mcp", "mcp.server", "mcp.server.streamable_http_manager"):
    logging.getLogger(_name).setLevel(logging.WARNING)


def _summarise(arguments: dict) -> str:
    parts = []
    for key, value in arguments.items():
        if value in ("", None, 0, False) or value == [] or value == {}:
            continue
        if key in _BULKY:
            parts.append(f"{key}=<{len(str(value))} chars>")
            continue
        text = " ".join(str(value).split())
        if len(text) > 120:
            text = text[:117] + "..."
        parts.append(f"{key}={text}")
    return ", ".join(parts)


def _locked(fn, args, kwargs):
    with _exclusive:
        return fn(*args, **kwargs)


def install(mcp, source: str) -> None:
    """Replace `mcp.tool` with the tracking wrapper described above."""
    raw_tool = mcp.tool

    def tool(*args, exclusive: bool = False, **kwargs):
        kwargs.setdefault("structured_output", False)
        decorator = raw_tool(*args, **kwargs)

        def wrap(fn):
            signature = inspect.signature(fn)
            is_async = inspect.iscoroutinefunction(fn)

            @functools.wraps(fn)
            async def wrapped(*f_args, **f_kwargs):
                notifier.record_tool_activity(fn.__name__)
                try:
                    bound = signature.bind_partial(*f_args, **f_kwargs).arguments
                except TypeError:
                    bound = dict(f_kwargs)
                summary = _summarise(bound)
                started = time.monotonic()
                try:
                    if is_async:
                        result = await fn(*f_args, **f_kwargs)
                    elif exclusive:
                        result = await anyio.to_thread.run_sync(
                            _locked, fn, f_args, f_kwargs
                        )
                    else:
                        result = await anyio.to_thread.run_sync(
                            functools.partial(fn, *f_args, **f_kwargs)
                        )
                except Exception as exc:  # noqa: BLE001 - logged, then re-raised
                    logs.log(
                        source, f"{fn.__name__}({summary}) crashed: {exc}",
                        level="error", kind="call",
                    )
                    raise
                finally:
                    if fn.__name__ != "notify_user":
                        notifier.record_tool_finished()
                took = time.monotonic() - started
                failed = isinstance(result, str) and result.startswith("Error")
                line = f"{fn.__name__}({summary})  {took:.2f}s"
                if failed:
                    line += "  -> " + result.splitlines()[0][:200]
                logs.log(source, line, level="warn" if failed else "info", kind="call")
                return result

            return decorator(wrapped)

        return wrap

    mcp.tool = tool


def build_http_app(mcp, name: str):
    """Wrap a FastMCP instance into the authenticated ASGI app we serve."""
    from mcp.server.transport_security import TransportSecuritySettings

    from servers.auth import BearerAuthMiddleware
    from servers.health import HealthMiddleware

    mcp.settings.streamable_http_path = str(
        settings.get("servers", "http_path", default="/mcp")
    )
    # The tunnel forwards a public Host header, which the default DNS
    # rebinding protection would reject. The token check below is what
    # keeps strangers out.
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )
    inner = mcp.streamable_http_app()

    # Some clients open a fresh MCP session for every single call and
    # never close it. Without an idle timeout each of those sessions stays
    # in memory until the app exits.
    idle = int(settings.get("servers", "session_idle_seconds", default=900) or 0)
    manager = getattr(mcp, "_session_manager", None)
    if idle > 0 and manager is not None and hasattr(manager, "session_idle_timeout"):
        manager.session_idle_timeout = float(idle)

    app = BearerAuthMiddleware(inner, name=name)
    # Health sits outermost so readiness checks need no token.
    return HealthMiddleware(app, name=name)
