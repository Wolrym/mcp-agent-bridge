"""Supervision of external child processes (currently cloudflared).

Everything the app spawns is owned by this module: started on launch,
stopped on exit, output forwarded into the shared log so the GUI can show
it. No PowerShell orchestration and no orphaned windows.
"""
from __future__ import annotations

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


class ManagedProcess:
    """A single supervised child process."""

    def __init__(self, name: str, command: Sequence[str]) -> None:
        self.name = name
        self.command = list(command)
        self._process: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._lock = threading.RLock()

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
            text = line.rstrip()
            if text:
                logs.log(self.name, text)
        code = process.wait()
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
