"""Prove out the /health endpoint and the probe itself.

1. Boots the files server on a spare port in this process and probes it,
   so we can tell whether the middleware works regardless of whatever the
   control panel happens to be running right now.
2. Probes the public hostnames with a plain and a browser-like
   User-Agent, because Cloudflare rejects some clients at the edge.

    python tests\\health_selftest.py
"""
from __future__ import annotations

import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn  # noqa: E402

from core import health  # noqa: E402

PORT = 9400
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def probe(url: str, user_agent: str = "") -> str:
    headers = {"User-Agent": user_agent} if user_agent else {}
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            body = response.read()[:120].decode("utf-8", "replace")
        return "HTTP " + str(response.status) + "  " + body.strip()
    except urllib.error.HTTPError as exc:
        body = exc.read()[:120].decode("utf-8", "replace")
        return "HTTP " + str(exc.code) + "  " + body.strip()
    except Exception as exc:  # noqa: BLE001 - diagnostics
        return type(exc).__name__ + ": " + str(exc)


def main() -> int:
    from servers.files_server import build_app

    config = uvicorn.Config(build_app(), host="127.0.0.1", port=PORT, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.2)

    base = "http://127.0.0.1:" + str(PORT)
    print("local /health      :", probe(base + "/health"))
    print("local /nope        :", probe(base + "/nope"))

    server.should_exit = True
    thread.join(timeout=10)

    print()
    for name, url in sorted(health.public_urls().items()):
        print(name, "plain UA   :", probe(url))
        print(name, "browser UA :", probe(url, BROWSER_UA))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
