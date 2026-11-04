import json
import os
import sys
import tempfile
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Never run against the real settings: test_credentials_resolution writes
# fake credentials, and once that replaced the user's real bot token and
# chat id. The settings singleton is created on import, so this comes first.
_settings_file = Path(tempfile.mkdtemp(prefix="mcp-notifier-")) / "settings.json"
_settings_file.write_text(
    json.dumps({"auth": {"enabled": True, "token": "notifier-test"}}), encoding="utf-8"
)
os.environ["MCP_SETTINGS_PATH"] = str(_settings_file)

from core import notifier
from core.config import settings


def test_notifier_formatting():
    # Test formatting with idle trigger
    msg_idle = notifier.format_notification(
        trigger_type="idle",
        idle_seconds=60,
        duration_seconds=125,
        total_calls=4,
        counts={"read_file": 2, "edit_file": 1, "run_command": 1},
    )
    assert "Agent Task Completed" in msg_idle
    assert "Idle timeout (60s)" in msg_idle
    assert "2m 5s" in msg_idle
    assert "4 tool call(s)" in msg_idle
    assert "edit_file ×1" in msg_idle
    print("test_notifier_formatting (idle): PASS")

    # Test formatting with explicit agent message
    msg_explicit = notifier.format_notification(
        trigger_type="explicit",
        agent_message="Refactored database schema and verified tests.",
        duration_seconds=45,
        total_calls=2,
    )
    assert "Completed by agent" in msg_explicit
    assert "Refactored database schema" in msg_explicit
    assert "<blockquote>" in msg_explicit
    print("test_notifier_formatting (explicit): PASS")


def test_credentials_resolution():
    settings.set("notifications", "bot_token", "test_bot_123")
    settings.set("notifications", "chat_id", "test_chat_456")
    token, chat = notifier.get_credentials()
    assert token == "test_bot_123"
    assert chat == "test_chat_456"
    assert notifier.is_configured() is True
    print("test_credentials_resolution: PASS")


def test_activity_tracker():
    tracker = notifier._ActivityTracker()
    tracker.record_activity("read_file", "main.py")
    tracker.record_activity("write_file", "test.py")

    assert tracker._tool_counts.get("read_file") == 1
    assert tracker._tool_counts.get("write_file") == 1
    assert len(tracker._last_tools) == 2

    tracker.reset_session()
    assert len(tracker._tool_counts) == 0
    assert len(tracker._last_tools) == 0
    print("test_activity_tracker: PASS")


if __name__ == "__main__":
    test_notifier_formatting()
    test_credentials_resolution()
    test_activity_tracker()
    print("\nALL NOTIFIER UNIT TESTS PASSED!")
