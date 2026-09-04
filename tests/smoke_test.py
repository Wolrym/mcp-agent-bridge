"""End-to-end smoke test for the core.

Starts both MCP servers on throwaway ports with a throwaway settings file,
then checks that:

  1. an unauthenticated request is rejected with 401
  2. an authenticated initialize handshake succeeds
  3. both servers expose the expected tool set

It never touches the real settings file and never starts the tunnel, so it
is safe to run while the old gateway is live.

    python tests/smoke_test.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

TOKEN = "smoke-test-token"
FILES_PORT = 9400
TERMINAL_PORT = 9401

# The settings singleton is created on import, so the environment has to be
# prepared before anything from `core` is imported.
_temp_dir = tempfile.mkdtemp(prefix="mcp-smoke-")
_settings_path = Path(_temp_dir) / "settings.json"
_settings_path.write_text(
    json.dumps({
        "auth": {"enabled": True, "token": TOKEN},
        "servers": {
            "host": "127.0.0.1",
            "files_port": FILES_PORT,
            "terminal_port": TERMINAL_PORT,
            "http_path": "/mcp",
        },
        "skills_root": str(REPO_ROOT.parent / "skills"),
        "projects": [
            {"id": "remake", "name": "remake", "root": str(REPO_ROOT), "selected_at": None}
        ],
        "active_project_id": "remake",
    }),
    encoding="utf-8",
)
os.environ["MCP_SETTINGS_PATH"] = str(_settings_path)

import httpx  # noqa: E402  (must come after the env is prepared)

from run_core import ServerSupervisor  # noqa: E402

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "smoke-test", "version": "1.0"},
    },
}

failures: list = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(("  PASS  " if condition else "  FAIL  ") + label + (f" - {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def parse_sse(body: str) -> dict:
    """Pull the first JSON payload out of an SSE response body."""
    for line in body.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return {}


def wait_for_port(url: str, attempts: int = 40) -> bool:
    for _ in range(attempts):
        try:
            httpx.post(url, json=INITIALIZE, headers=HEADERS, timeout=2)
            return True
        except httpx.HTTPError:
            time.sleep(0.25)
    return False


def exercise(name: str, port: int, expected_tools: set) -> None:
    url = f"http://127.0.0.1:{port}/mcp"
    print(f"\n{name} @ {url}")

    anonymous = httpx.post(url, json=INITIALIZE, headers=HEADERS, timeout=10)
    check("rejects requests without a token", anonymous.status_code == 401,
          f"got {anonymous.status_code}")

    bad = httpx.post(url, json=INITIALIZE, timeout=10,
                     headers={**HEADERS, "Authorization": "Bearer wrong"})
    check("rejects a wrong token", bad.status_code == 401, f"got {bad.status_code}")

    auth = {**HEADERS, "Authorization": f"Bearer {TOKEN}"}
    handshake = httpx.post(url, json=INITIALIZE, headers=auth, timeout=10)
    check("accepts the configured token", handshake.status_code == 200,
          f"got {handshake.status_code}")

    session_id = handshake.headers.get("mcp-session-id", "")
    check("returns a session id", bool(session_id), session_id or "missing")
    if not session_id:
        return

    session_headers = {**auth, "mcp-session-id": session_id}
    httpx.post(url, headers=session_headers, timeout=10,
               json={"jsonrpc": "2.0", "method": "notifications/initialized"})

    listed = httpx.post(url, headers=session_headers, timeout=10,
                        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    payload = parse_sse(listed.text)
    tools = {tool["name"] for tool in payload.get("result", {}).get("tools", [])}
    print("  tools: " + (", ".join(sorted(tools)) if tools else "(none)"))
    missing = expected_tools - tools
    check("exposes the expected tools", not missing,
          f"missing {sorted(missing)}" if missing else "")


def main() -> int:
    supervisor = ServerSupervisor()
    supervisor.start()
    try:
        if not wait_for_port(f"http://127.0.0.1:{FILES_PORT}/mcp"):
            print("Servers did not come up in time.")
            return 1

        exercise("Files System", FILES_PORT, {
            "list_directory", "read_file", "read_multiple_files", "write_file",
            "edit_file", "create_directory", "move_file", "delete_file",
            "search_files", "grep", "get_file_info",
        })
        exercise("Terminal", TERMINAL_PORT, {
            "run_command", "get_active_project", "list_skills", "get_skill",
        })
    finally:
        supervisor.stop()

    print("")
    if failures:
        print(f"{len(failures)} check(s) failed: " + ", ".join(failures))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
