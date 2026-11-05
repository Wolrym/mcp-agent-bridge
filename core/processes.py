"""Supervision of external child processes (currently cloudflared).

Everything the app spawns is owned by this module: started on launch,
stopped on exit, output forwarded into the shared log so the GUI can show
it. No PowerShell orchestration and no orphaned windows.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import threading
from typing import Sequence

from core import logs

# On Windows, keep child console windows hidden and make sure terminating
# the parent does not leave the child running.
_CREATION_FLAGS = 0
try:
    _CREATION_FLAGS = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
except AttributeError:  # pragma: no cover - non-Windows
    _CREATION_FLAGS = 0


# cloudflared prefixes every line with its own UTC time and level; the log
# already has a local time, so only the level is kept.
_CF_PREFIX = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z\s+(INF|WRN|ERR|DBG|FTL)\s+")
_CF_LEVEL = {"INF": "info", "DBG": "debug", "WRN": "warn", "ERR": "warn", "FTL": "error"}

# A client hanging up on a request, which MCP clients do all the time:
# "context canceled", or a stream reset with code 0 (NO_ERROR) - the
# Streamable HTTP client closing a response it has finished reading.
_HANGUPS = ("context canceled", "canceled by remote with error code 0")

# Start-up chatter that is fine to keep in the log file but buries the
# useful lines in the panel: the connectivity table, passed prechecks,
# TLS curve lists, the ICMP proxy and the metrics server.
_CHATTER = re.compile(
    r"^(?:[|+]|precheck component=.*status=pass|precheck complete hard_fail=false"
    r"|Tunnel connection curve preferences|ICMP proxy will use|Starting metrics server"
    r"|Generated Connector ID|Initial protocol|Settings: |Version |GOOS: |"
    r"cloudflared will not automatically update|Autoupdate frequency)"
)
_REGISTERED = "Registered tunnel connection "
_FIELD = re.compile(r"(\w+)=(\S+)")


def tidy_line(text: str):
    """(level, message) for one line of child output, or None to drop it.

    cloudflared tags its own lines INF / WRN / ERR; its ERR lines used to
    land in the panel as plain info, and most of them only meant that a
    client hung up. Those are dropped, real errors become warnings, and
    start-up chatter is kept at debug level (log file only).
    """
    text = text.strip()
    if not text:
        return None
    level = "info"
    match = _CF_PREFIX.match(text)
    if match:
        level = _CF_LEVEL[match.group(1)]
        text = text[match.end():]
    elif " ERR " in text or " WRN " in text:
        level = "warn"
    if any(marker in text for marker in _HANGUPS):
        return None
    if text.startswith("precheck") and "status=fail" in text:
        return "warn", text
    if _CHATTER.match(text):
        return "debug", text
    if text.startswith(_REGISTERED):
        fields = dict(_FIELD.findall(text))
        index = fields.get("connIndex", "")
        number = str(int(index) + 1) if index.isdigit() else index
        where = ", ".join(fields[k] for k in ("location", "protocol") if fields.get(k))
        return level, f"Tunnel connection {number} registered" + (f" ({where})" if where else "")
    return level, text


def classify_line(text: str):
    """Log level for one line of child output, or None to drop it."""
    tidy = tidy_line(text)
    return tidy[0] if tidy else None


class ManagedProcess:
    """A single supervised child process."""

    def __init__(self, name: str, command: Sequence[str]) -> None:
        self.name = name
        self.command = list(command)
        self._process: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._lock = threading.RLock()
        self._stopping = False

    # --- state -----------------------------------------------------------

    @property
    def running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    @property
    def pid(self) -> int | None:
        with self._lock:
            return self._process.pid if self._process else None

    def status(self) -> dict:
        with self._lock:
            code = self._process.poll() if self._process else None
        return {
            "name": self.name,
            "running": self.running,
            "pid": self.pid,
            "exit_code": code,
            "command": " ".join(self.command),
        }

    # --- lifecycle -------------------------------------------------------

    def start(self) -> None:
        """Start the process if it is not already running."""
        with self._lock:
            if self.running:
                return
            executable = shutil.which(self.command[0]) or self.command[0]
            self._stopping = False
            try:
                self._process = subprocess.Popen(
                    [executable, *self.command[1:]],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=_CREATION_FLAGS,
                )
            except FileNotFoundError:
                logs.log(
                    self.name,
                    f"Executable not found: {self.command[0]}",
                    level="error",
                )
                return
            except Exception as exc:  # noqa: BLE001
                logs.log(self.name, f"Failed to start: {exc}", level="error")
                return

            logs.log(self.name, f"Started (pid {self._process.pid})")
            self._reader = threading.Thread(
                target=self._pump_output, args=(self._process,), daemon=True
            )
            self._reader.start()

    def stop(self, timeout: float = 10.0) -> None:
        """Terminate the process, escalating to kill if it ignores us."""
        with self._lock:
            process = self._process
        if process is None or process.poll() is not None:
            return

        # Exiting because we asked it to is not an error.
        self._stopping = True
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logs.log(self.name, "Did not exit in time, killing", level="warn")
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logs.log(self.name, "Process could not be killed", level="error")
        logs.log(self.name, "Stopped")

    def restart(self) -> None:
        self.stop()
        self.start()

    # --- internals -------------------------------------------------------

    def _pump_output(self, process: subprocess.Popen) -> None:
        """Forward the child's combined output into the shared log."""
        stream = process.stdout
        if stream is None:
            return
        for line in stream:
            tidy = tidy_line(line)
            if tidy:
                logs.log(self.name, tidy[1], level=tidy[0])
        code = process.wait()
        if self._stopping:
            self._stopping = False
            return
        level = "info" if code == 0 else "error"
        logs.log(self.name, f"Exited with code {code}", level=level)


class ProcessRegistry:
    """Keeps track of every managed process so they can be stopped together."""

    def __init__(self) -> None:
        self._processes: dict = {}
        self._lock = threading.RLock()

    def register(self, process: ManagedProcess) -> ManagedProcess:
        with self._lock:
            existing = self._processes.get(process.name)
            if existing is not None and existing.running:
                existing.stop()
            self._processes[process.name] = process
            return process

    def get(self, name: str) -> ManagedProcess | None:
        with self._lock:
            return self._processes.get(name)

    def statuses(self) -> list:
        with self._lock:
            return [p.status() for p in self._processes.values()]

    def stop_all(self) -> None:
        with self._lock:
            processes = list(self._processes.values())
        for process in processes:
            process.stop()


registry = ProcessRegistry()
