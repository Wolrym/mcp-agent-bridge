"""Telegram notification system and agent activity tracking.

Features:
- Sends formatted HTML notifications via Telegram Bot API.
- Tracks tool activity across servers (files, terminal).
- Automated inactivity/idle timer: if tools were used and then idle for N seconds,
  sends a completion notification.
- Supports explicit `notify_user` calls from AI agents with their custom summary.
- Resolves bot token and chat ID from settings.json or environment variables
  (including optional .env file).
"""
from __future__ import annotations

import html
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from core import logs, projects
from core.config import PROJECT_ROOT, settings

# Optional .env loading from project root or user home
_ENV_LOADED = False


def _ensure_env_loaded() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True

    candidates = [
        PROJECT_ROOT / ".env",
        Path.home() / ".env",
    ]
    for env_path in candidates:
        if env_path.is_file():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = val
            except Exception as exc:  # noqa: BLE001
                logs.log("notify", f"Failed to parse {env_path}: {exc}", level="warn")


def get_credentials() -> tuple[str, str]:
    """Return (bot_token, chat_id) resolved from settings or environment."""
    _ensure_env_loaded()
    cfg = settings.get("notifications", default={}) or {}

    token = str(cfg.get("bot_token") or "").strip()
    if not token:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

    chat_id = str(cfg.get("chat_id") or "").strip()
    if not chat_id:
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    return token, chat_id


def is_configured() -> bool:
    token, chat_id = get_credentials()
    return bool(token and chat_id)


def is_enabled() -> bool:
    cfg = settings.get("notifications", default={}) or {}
    return bool(cfg.get("enabled", False)) and is_configured()


def send_telegram_message(
    text: str,
    parse_mode: str = "HTML",
    custom_token: str = "",
    custom_chat_id: str = "",
    timeout: float = 10.0,
) -> tuple[bool, str]:
    """Send a message to Telegram using standard library urllib.

    Returns (success: bool, detail: str).
    """
    token = custom_token.strip() or get_credentials()[0]
    chat_id = custom_chat_id.strip() or get_credentials()[1]

    if not token or not chat_id:
        return False, "Bot token or Chat ID is missing."

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            if resp_data.get("ok"):
                return True, "Message sent successfully."
            return False, resp_data.get("description", "Unknown Telegram error.")
    except urllib.error.HTTPError as exc:
        try:
            err_body = json.loads(exc.read().decode("utf-8"))
            detail = err_body.get("description", str(exc))
        except Exception:
            detail = f"HTTP {exc.code}: {exc.reason}"
        return False, detail
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


# --- Activity Tracker & Inactivity Timer ---

class _ActivityTracker:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._timer: threading.Timer | None = None
        self._session_start: float = 0.0
        self._last_activity: float = 0.0
        self._tool_counts: dict[str, int] = {}
        self._last_tools: list[str] = []

    def reset_session(self) -> None:
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None
            self._session_start = 0.0
            self._last_activity = 0.0
            self._tool_counts.clear()
            self._last_tools.clear()

    def record_activity(self, tool_name: str, detail: str = "") -> None:
        now = time.time()
        with self._lock:
            if not self._session_start:
                self._session_start = now
            self._last_activity = now

            self._tool_counts[tool_name] = self._tool_counts.get(tool_name, 0) + 1
            if detail:
                item = f"{tool_name}: {detail}"
            else:
                item = tool_name
            self._last_tools.append(item)
            if len(self._last_tools) > 15:
                self._last_tools.pop(0)

            self._reschedule()

    def touch(self) -> None:
        """Restart the idle countdown without counting a new call.

        Called when a tool call finishes: a command that ran for 45 seconds
        must not make the agent look idle the moment it returns.
        """
        with self._lock:
            if not self._session_start:
                return
            self._last_activity = time.time()
            self._reschedule()

    def _reschedule(self) -> None:
        # Cancel the existing idle timer, then start a fresh one if idle
        # notifications are active. Callers hold the lock.
        if self._timer:
            self._timer.cancel()
            self._timer = None
        cfg = settings.get("notifications", default={}) or {}
        if is_enabled() and cfg.get("notify_on_idle", True):
            idle_secs = int(cfg.get("idle_timeout_seconds", 60) or 60)
            if idle_secs > 0:
                self._timer = threading.Timer(idle_secs, self._on_idle_timeout)
                self._timer.daemon = True
                self._timer.start()

    def _on_idle_timeout(self) -> None:
        with self._lock:
            if not self._session_start:
                return
            duration = max(1, round(self._last_activity - self._session_start))
            total_calls = sum(self._tool_counts.values())
            counts = dict(self._tool_counts)
            last_tools = list(self._last_tools)
            # Reset session state before dispatching
            self._session_start = 0.0
            self._last_activity = 0.0
            self._tool_counts.clear()
            self._last_tools.clear()
            self._timer = None

        if not is_enabled():
            return

        cfg = settings.get("notifications", default={}) or {}
        idle_secs = int(cfg.get("idle_timeout_seconds", 60) or 60)

        # Build clean, executive message
        msg = format_notification(
            trigger_type="idle",
            idle_seconds=idle_secs,
            duration_seconds=duration,
            total_calls=total_calls,
            counts=counts,
            last_tools=last_tools,
        )
        ok, res = send_telegram_message(msg)
        if ok:
            logs.log("notify", f"Telegram notification sent (agent idle {idle_secs}s)")
        else:
            logs.log("notify", f"Telegram notification failed: {res}", level="warn")

    def explicit_notify(self, message: str = "") -> tuple[bool, str]:
        """Triggered when agent explicitly invokes notify_user tool."""
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None

            now = time.time()
            if self._session_start:
                duration = max(1, round(now - self._session_start))
            else:
                duration = 0
            total_calls = sum(self._tool_counts.values())
            counts = dict(self._tool_counts)
            last_tools = list(self._last_tools)

            self._session_start = 0.0
            self._last_activity = 0.0
            self._tool_counts.clear()
            self._last_tools.clear()

        if not is_enabled():
            return False, "Telegram notifications are disabled in settings."

        msg = format_notification(
            trigger_type="explicit",
            agent_message=message,
            duration_seconds=duration,
            total_calls=total_calls,
            counts=counts,
            last_tools=last_tools,
        )
        ok, res = send_telegram_message(msg)
        if ok:
            logs.log("notify", f"Telegram notification sent (via agent tool): {res}")
            return True, "Notification sent to user via Telegram."
        logs.log("notify", f"Telegram notification failed: {res}", level="warn")
        return False, f"Failed to send Telegram notification: {res}"


_tracker = _ActivityTracker()


def record_tool_activity(tool_name: str, detail: str = "") -> None:
    _tracker.record_activity(tool_name, detail)


def record_tool_finished() -> None:
    _tracker.touch()


def notify_from_agent(message: str = "") -> tuple[bool, str]:
    return _tracker.explicit_notify(message)


def send_test_message(token: str = "", chat_id: str = "") -> tuple[bool, str]:
    """Send an immediate test message from GUI to verify credentials."""
    try:
        proj = projects.active_project()
        proj_name = proj["name"]
    except Exception:
        proj_name = "Notion MCP Bridge"

    msg = (
        "<b>MCP Agent Bridge</b> &bull; Test Notification\n\n"
        "Connection to Telegram is working properly.\n"
        f"<b>Workspace:</b> <code>{html.escape(proj_name)}</code>\n"
        "Status: <i>Ready to receive agent completion alerts.</i>"
    )
    return send_telegram_message(msg, custom_token=token, custom_chat_id=chat_id)


def format_notification(
    trigger_type: str = "idle",
    agent_message: str = "",
    idle_seconds: int = 60,
    duration_seconds: int = 0,
    total_calls: int = 0,
    counts: dict[str, int] | None = None,
    last_tools: list[str] | None = None,
) -> str:
    """Format a clean, professional Telegram HTML message."""
    try:
        active = projects.active_project()
        proj_name = active.get("name", "Active Workspace")
    except Exception:
        proj_name = "Active Workspace"

    lines = []
    lines.append("<b>Agent Task Completed</b>")
    lines.append(f"<b>Workspace:</b> <code>{html.escape(proj_name)}</code>")

    # Time & activity summary
    stats = []
    if duration_seconds > 0:
        mins, secs = divmod(duration_seconds, 60)
        dur_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
        stats.append(f"active for {dur_str}")
    if total_calls > 0:
        stats.append(f"{total_calls} tool call(s)")

    if stats:
        lines.append(f"<b>Activity:</b> {', '.join(stats)}")

    if trigger_type == "idle":
        lines.append(f"<b>Status:</b> Idle timeout ({idle_seconds}s)")
    else:
        lines.append("<b>Status:</b> Completed by agent")

    # Agent message / quote if provided
    cleaned_msg = agent_message.strip() if agent_message else ""
    if cleaned_msg:
        escaped = html.escape(cleaned_msg)
        lines.append(f"\n<blockquote>{escaped}</blockquote>")
    elif counts:
        # Show top actions in a clean quote block with clean unicode × symbol
        summary_items = []
        for tool, count in sorted(counts.items(), key=lambda x: -x[1])[:3]:
            summary_items.append(f"{tool} ×{count}")
        if summary_items:
            lines.append(f"\n<blockquote>Actions: {', '.join(summary_items)}</blockquote>")

    return "\n".join(lines)
