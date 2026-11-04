"""Bearer token authentication for the public MCP endpoints.

The servers are reachable from the internet through the tunnel, and the
terminal one can run arbitrary commands, so every request must carry the
token from the settings file.

This is a pure ASGI middleware rather than a Starlette
`BaseHTTPMiddleware`: the MCP transport streams responses, and
BaseHTTPMiddleware buffers them.
"""
from __future__ import annotations

import json
import secrets
import threading
import time

from core import logs
from core.config import settings

# Accepted ways to present the token: a bearer header (what most MCP
# clients send) or a plain API key header for clients that cannot.
BEARER_PREFIX = "bearer "
API_KEY_HEADERS = (b"x-api-key", b"x-auth-token")


# Brute-force brake: an address that keeps failing gets a short break.
# The token is far too long to guess, so this mostly keeps the log quiet.
FAIL_WINDOW = 300
FAIL_LIMIT = 20
BLOCK_SECONDS = 900
_failures: dict = {}
_blocked: dict = {}
_last_logged: dict = {}
_brake_lock = threading.Lock()
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def client_ip(scope) -> str:
    """The real caller. Behind the tunnel every request comes from
    localhost, and Cloudflare passes the original address in a header."""
    lookup = {key.lower(): value for key, value in scope.get("headers", [])}
    for header in (b"cf-connecting-ip", b"x-forwarded-for"):
        value = lookup.get(header)
        if value:
            return value.decode("latin-1").split(",")[0].strip()
    client = scope.get("client") or ("?", 0)
    return str(client[0])


def _is_blocked(ip: str, now: float) -> bool:
    with _brake_lock:
        until = _blocked.get(ip)
        if until and until > now:
            return True
        _blocked.pop(ip, None)
        return False


def _record_failure(ip: str, now: float) -> bool:
    """Count a failure. Returns True when the address just got blocked."""
    if ip in LOOPBACK:
        return False
    with _brake_lock:
        recent = [t for t in _failures.get(ip, []) if now - t < FAIL_WINDOW]
        recent.append(now)
        _failures[ip] = recent
        if len(recent) >= FAIL_LIMIT:
            _blocked[ip] = now + BLOCK_SECONDS
            _failures.pop(ip, None)
            return True
        return False


def _should_log(ip: str, now: float) -> bool:
    with _brake_lock:
        if now - _last_logged.get(ip, 0) < 60:
            return False
        _last_logged[ip] = now
        return True


def _extract_token(headers: list) -> str:
    lookup = {key.lower(): value for key, value in headers}
    raw = lookup.get(b"authorization", b"").decode("latin-1").strip()
    if raw.lower().startswith(BEARER_PREFIX):
        return raw[len(BEARER_PREFIX):].strip()
    for header in API_KEY_HEADERS:
        value = lookup.get(header)
        if value:
            return value.decode("latin-1").strip()
    return ""


class BearerAuthMiddleware:
    """Reject any HTTP request that does not carry the configured token."""

    def __init__(self, app, name: str, public_paths: tuple = ("/health",)) -> None:
        self.app = app
        self.name = name
        self.public_paths = public_paths

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope.get("path") in self.public_paths:
            await self.app(scope, receive, send)
            return

        if not settings.get("auth", "enabled", default=True):
            await self.app(scope, receive, send)
            return

        expected = str(settings.get("auth", "token", default=""))
        provided = _extract_token(scope.get("headers", []))
        ip = client_ip(scope)
        now = time.time()

        if _is_blocked(ip, now):
            await self._deny(send, "Too many failed attempts. Try again later.", status=429)
            return

        if not expected:
            await self._deny(send, "Server has no auth token configured.")
            logs.log(self.name, "Rejected request: no token configured", level="error")
            return

        # compare_digest needs bytes here: a str with non-ASCII characters
        # (anything can arrive in a header) would raise instead of failing.
        valid = bool(provided) and secrets.compare_digest(
            provided.encode("utf-8", "surrogateescape"), expected.encode("utf-8")
        )
        if not valid:
            # Only wrong tokens count towards the brake. Requests with no
            # token at all - scanners, a client probing for OAuth before
            # sending its header - are refused but must not get a real
            # client's address blocked.
            if provided and _record_failure(ip, now):
                logs.log(
                    self.name,
                    f"Blocked {ip} for {BLOCK_SECONDS // 60} min after "
                    f"{FAIL_LIMIT} failed attempts",
                    level="warn",
                )
            elif _should_log(ip, now):
                logs.log(
                    self.name,
                    f"Rejected request without a valid token from {ip}",
                    level="warn",
                )
            await self._deny(send, "Missing or invalid authentication token.")
            return

        await self.app(scope, receive, send)

    async def _deny(self, send, message: str, status: int = 401) -> None:
        error = "unauthorized" if status == 401 else "too_many_requests"
        body = json.dumps({"error": error, "message": message}).encode()
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"www-authenticate", b"Bearer"),
            ],
        })
        await send({"type": "http.response.body", "body": body})
