"""Diagnose the readiness pill: probe every endpoint and show the raw result.

    python tests\\probe_health.py

Prints the HTTP status (or the exact error) for each local and public
/health URL, plus the same call against /mcp so we can tell "server is
down" apart from "server is up but has no /health".
"""
from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import health  # noqa: E402
from core.config import settings  # noqa: E402

TIMEOUT = 8.0


def probe(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            body = response.read()[:160].decode("utf-8", "replace")
        return "HTTP " + str(response.status) + "  " + body
    except urllib.error.HTTPError as exc:
        body = exc.read()[:160].decode("utf-8", "replace")
        return "HTTP " + str(exc.code) + "  " + body
    except Exception as exc:  # noqa: BLE001 - diagnostics
        return type(exc).__name__ + ": " + str(exc)


def main() -> int:
    servers = settings.get("servers", default={}) or {}
    tunnel = settings.get("tunnel", default={}) or {}
    http_path = servers.get("http_path") or "/mcp"

    print("ports:", servers.get("files_port"), servers.get("terminal_port"))
    print("tunnel enabled:", tunnel.get("enabled"))
    print()

    print("--- /health ---")
    for kind, urls in (("local", health.local_urls()), ("public", health.public_urls())):
        for name, url in sorted(urls.items()):
            print(" ", kind, name, url)
            print("     ", probe(url))

    print()
    print("--- " + http_path + " (should answer even without /health) ---")
    host = servers.get("host") or "127.0.0.1"
    for name, port in (("files", servers.get("files_port")), ("terminal", servers.get("terminal_port"))):
        url = "http://" + str(host) + ":" + str(port) + http_path
        print(" ", name, url)
        print("     ", probe(url))

    print()
    print("snapshot:", health.snapshot(timeout=TIMEOUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
