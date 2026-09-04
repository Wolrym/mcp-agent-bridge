"""Settings storage for the MCP workspace.

One JSON file holds everything the servers and the future GUI need:
auth token, ports, tunnel setup, limits and the project registry.

The store is process-wide, thread-safe and observable: the GUI can
subscribe with `subscribe()` and re-render whenever anything changes.
Servers always read through `get()`, so a change made in the GUI takes
effect on the next tool call without a restart.

Prefer changing settings through `run_core.py`'s CLI flags or the GUI over
hand-editing the JSON file: a single syntax mistake (a stray comma, an
un-escaped backslash) makes the whole file unreadable, and this store then
falls back to defaults - which looks like your edits were silently wiped.
"""
from __future__ import annotations

import copy
import json
import os
import secrets
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
SETTINGS_PATH = Path(
    os.environ.get("MCP_SETTINGS_PATH", CONFIG_DIR / "settings.json")
)

DEFAULTS: dict[str, Any] = {
    "version": 1,
    "auth": {"enabled": True, "token": ""},
    "servers": {
        "host": "127.0.0.1",
        "files_port": 9500,
        "terminal_port": 9501,
        "http_path": "/mcp",
    },
    "tunnel": {
        "enabled": False,
        "binary": "cloudflared",
        "tunnel_name": "notion-sync",
        "config_file": "",
        "domain": "wolroom.store",
        "user_slug": "",
        "files_hostname": "",
        "terminal_hostname": "",
    },
    "limits": {
        "command_timeout": 60,
        # A tool call is an HTTP request and the client gives up after about
        # a minute, so waiting longer than this inside one call is pointless.
        # Anything slower belongs in a background job.
        "command_timeout_max": 120,
        "max_output_chars": 100000,
        "max_read_bytes": 5000000,
        "max_read_lines": 900,
        "max_results": 300,
        "max_backup_bytes": 20000000,
        "backup_retention_days": 14,
        # Ceiling for wait_process. A tool call is still one HTTP request,
        # so this has to stay comfortably under the client's ~60s deadline
        # rather than at it.
        "wait_seconds_max": 50,
    },
    "security": {"allow_outside_project": False},
    "backups": {"enabled": False},
    # GUI-only preferences. `autostart` brings the servers and the tunnel up
    # as soon as the panel opens, so the machine is reachable without a
    # click. The headless CLI ignores it: there, starting is the whole point.
    "gui": {"autostart": False},
    "skills_root": "",
    "projects": [],
    "active_project_id": None,
}

Listener = Callable[[dict], None]


def _merge_defaults(defaults: dict, data: dict) -> dict:
    """Return `data` with any missing keys filled in from `defaults`."""
    merged = copy.deepcopy(defaults)
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_defaults(merged[key], value)
        else:
            merged[key] = value
    return merged


class SettingsStore:
    """Thread-safe JSON-backed settings with change notifications."""

    def __init__(self, path: Path = SETTINGS_PATH) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._listeners: list = []
        self._data: dict = copy.deepcopy(DEFAULTS)
        self.load()

    # --- persistence -----------------------------------------------------

    def load(self) -> dict:
        with self._lock:
            raw: dict = {}
            parse_error = False
            if self._path.is_file():
                try:
                    raw = json.loads(self._path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    raw = {}
                    parse_error = True
            self._data = _merge_defaults(DEFAULTS, raw)
            changed = self._bootstrap()
            if parse_error:
                # Keep the broken file around for inspection instead of
                # silently losing it, then write out a fresh valid one.
                broken = self._path.with_suffix(".broken.json")
                try:
                    self._path.replace(broken)
                except OSError:
                    pass
                changed = True
            if changed or not self._path.is_file():
                self._write()
            return copy.deepcopy(self._data)

    def _bootstrap(self) -> bool:
        """Fill in values that must exist but cannot be shipped as defaults."""
        changed = False
        if not self._data["auth"].get("token"):
            self._data["auth"]["token"] = secrets.token_urlsafe(32)
            changed = True
        # skills_root stays empty on purpose: core.skills resolves it
        # relative to the project folder, so moving or renaming that folder
        # does not strand an absolute path in the settings file. Setting it
        # explicitly still wins.
        if not self._data["projects"]:
            self._data["projects"] = [
                {
                    "id": "home",
                    "name": "home",
                    "root": str(Path.home()),
                    "selected_at": None,
                }
            ]
            changed = True
        ids = {p["id"] for p in self._data["projects"]}
        if self._data.get("active_project_id") not in ids:
            self._data["active_project_id"] = self._data["projects"][0]["id"]
            changed = True

        tunnel_cfg = self._data.setdefault("tunnel", {})
        if "domain" not in tunnel_cfg:
            files_h = tunnel_cfg.get("files_hostname", "")
            if "." in files_h:
                parts = files_h.split(".")
                tunnel_cfg["domain"] = ".".join(parts[1:])
            else:
                tunnel_cfg["domain"] = "wolroom.store"
            changed = True
        if "user_slug" not in tunnel_cfg:
            tunnel_cfg["user_slug"] = ""
            changed = True

        if "backups" not in self._data:
            self._data["backups"] = {"enabled": False}
            changed = True
        return changed

    def _write(self) -> None:
        """Atomically persist the current state."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, self._path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    # --- access ----------------------------------------------------------

    def all(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    def get(self, *keys: str, default: Any = None) -> Any:
        """Read a nested value, e.g. settings.get("servers", "files_port")."""
        with self._lock:
            node: Any = self._data
            for key in keys:
                if not isinstance(node, dict) or key not in node:
                    return default
                node = node[key]
            return copy.deepcopy(node)

    def update(self, mutate: Callable[[dict], None]) -> dict:
        """Apply `mutate` to the settings, persist, and notify listeners."""
        with self._lock:
            draft = copy.deepcopy(self._data)
            mutate(draft)
            self._data = _merge_defaults(DEFAULTS, draft)
            self._bootstrap()
            self._write()
            snapshot = copy.deepcopy(self._data)
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(snapshot)
            except Exception:  # noqa: BLE001 - a bad listener must not break writes
                pass
        return snapshot

    def set(self, *keys_and_value: Any) -> dict:
        """Set a nested value: settings.set("servers", "files_port", 9300)."""
        *keys, value = keys_and_value

        def mutate(draft: dict) -> None:
            node = draft
            for key in keys[:-1]:
                node = node.setdefault(key, {})
            node[keys[-1]] = value

        return self.update(mutate)

    def regenerate_token(self) -> str:
        self.set("auth", "token", secrets.token_urlsafe(32))
        return str(self.get("auth", "token"))

    # --- observation -----------------------------------------------------

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        """Register a change listener. Returns an unsubscribe callable."""
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe


settings = SettingsStore()
