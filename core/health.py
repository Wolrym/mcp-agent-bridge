"""Readiness checks: "is this thing actually usable from Notion yet?"

A started process is not the same as a reachable endpoint - uvicorn needs a
moment to bind, and cloudflared needs a few seconds to register its tunnel.
This module answers the question the user actually has by making real HTTP
requests to the public /health path.

Two details that cost us a debugging session, kept here on purpose:

* Cloudflare rejects the default urllib user agent with HTTP 403 and its
  own error code 1010, so every probe must look like an ordinary client.
* A server built before /health existed does not 404 the request - the MCP
  transport turns an unknown GET into an event stream that never ends, so
  the probe hangs until the timeout. That is reported as its own reason
  rather than a generic failure.

Only the standard library is used, so a readiness check can never be the
reason the app fails to start.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from core.config import settings

HEALTH_PATH = "/health"

# Cloudflare blocks "Python-urllib/x.y" at the edge with error 1010.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 mcp-control-panel"
)

# States, in increasing order of "good":
OFFLINE = "offline"      # nothing is answering
STARTING = "starting"    # only part of the stack answers
LOCAL = "local"          # local endpoints are up, no public access
READY = "ready"          # reachable the way Notion will reach it


def _probe(url: str, timeout: float) -> dict:
    """Ask one endpoint how it is doing.

    Returns {"ok": bool, "detail": str}. The detail is written for a human
    reading a tooltip, so it names the likely cause instead of the
    exception class.
    """
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, method="GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if 200 <= response.status < 300:
                return {"ok": True, "detail": "ok"}
            return {"ok": False, "detail": "unexpected status " + str(response.status)}
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return {"ok": False, "detail": "running, but too old to have /health"}
        if exc.code in (502, 503, 530):
            return {"ok": False, "detail": "tunnel is up, the server behind it is not"}
        if exc.code == 403:
            return {"ok": False, "detail": "blocked at the Cloudflare edge (403)"}
        return {"ok": False, "detail": "HTTP " + str(exc.code)}
    except (socket.timeout, TimeoutError):
        return {"ok": False, "detail": "no reply before the timeout"}
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return {"ok": False, "detail": "no reply before the timeout"}
        if isinstance(reason, socket.gaierror) or "getaddrinfo failed" in str(reason):
            return {"ok": False, "detail": "DNS lookup failed"}
        return {"ok": False, "detail": "not reachable"}
    except (OSError, ValueError) as exc:
        if isinstance(exc, socket.gaierror) or "getaddrinfo failed" in str(exc):
            return {"ok": False, "detail": "DNS lookup failed"}
        return {"ok": False, "detail": "not reachable"}


def local_urls() -> dict:
    servers = settings.get("servers", default={}) or {}
    host = servers.get("host") or "127.0.0.1"
    base = "http://" + str(host) + ":"
    return {
        "files": base + str(servers.get("files_port")) + HEALTH_PATH,
        "terminal": base + str(servers.get("terminal_port")) + HEALTH_PATH,
    }


def public_urls() -> dict:
    """Health URLs behind the tunnel, empty when the tunnel is not in use."""
    config = settings.get("tunnel", default={}) or {}
    if not config.get("enabled"):
        return {}
    urls = {}
    if config.get("files_hostname"):
        urls["files"] = "https://" + str(config["files_hostname"]) + HEALTH_PATH
    if config.get("terminal_hostname"):
        urls["terminal"] = "https://" + str(config["terminal_hostname"]) + HEALTH_PATH
    return urls


def snapshot(timeout: float = 2.0, check_public: bool = True) -> dict:
    """Probe every endpoint and summarise the result.

    Returns a dict with:
        state  - one of OFFLINE, STARTING, LOCAL, READY
        label  - short text for the UI
        local  - {name: {"ok": bool, "detail": str}}
        public - same shape, empty when the tunnel is off
    """
    local = local_urls()
    public = public_urls() if check_public else {}

    targets = [("local", name, url) for name, url in local.items()]
    targets += [("public", name, url) for name, url in public.items()]

    # Probing in parallel keeps one slow or unreachable hostname from
    # dominating the total wait.
    with ThreadPoolExecutor(max_workers=max(len(targets), 1)) as pool:
        outcomes = list(pool.map(lambda target: _probe(target[2], timeout), targets))

    results: dict = {"local": {}, "public": {}}
    for (kind, name, _url), outcome in zip(targets, outcomes):
        results[kind][name] = outcome

    def all_ok(group: dict) -> bool:
        return bool(group) and all(item["ok"] for item in group.values())

    def any_ok(group: dict) -> bool:
        return any(item["ok"] for item in group.values())

    local_ok = all_ok(results["local"])

    if public:
        if local_ok and all_ok(results["public"]):
            state, text = READY, "Ready in Notion"
        elif local_ok:
            state, text = STARTING, "Local only"
        elif any_ok(results["local"]) or any_ok(results["public"]):
            state, text = STARTING, "Starting..."
        else:
            state, text = OFFLINE, "Not running"
    else:
        if local_ok:
            state, text = LOCAL, "Running locally"
        elif any_ok(results["local"]):
            state, text = STARTING, "Starting..."
        else:
            state, text = OFFLINE, "Not running"

    return {
        "state": state,
        "label": text,
        "local": results["local"],
        "public": results["public"],
    }


def describe(result: dict) -> str:
    """One-line detail string for tooltips and logs."""
    def part(kind: str) -> str:
        values = result.get(kind) or {}
        if not values:
            return ""
        inner = ", ".join(
            name + ": " + str(item.get("detail", "?"))
            for name, item in sorted(values.items())
        )
        return kind + " (" + inner + ")"

    return "   |   ".join(p for p in (part("local"), part("public")) if p)


def fetch_project(timeout: float = 2.0) -> str:
    """Ask a running server which project it is serving, for cross-checking."""
    url = local_urls().get("files", "")
    if not url:
        return ""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return str(payload.get("project") or "")
    except (urllib.error.URLError, OSError, ValueError):
        return ""
