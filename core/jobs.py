"""Background jobs: commands that outlive a single MCP request.

An MCP tool call is an ordinary HTTP request, and the client on the other
side stops waiting after roughly a minute. A slow command - `npm install`,
a build, a test suite, a dev server - therefore cannot be awaited inside
one call no matter how generous a timeout we pass to the shell. Asking for
600 seconds only guarantees that the answer arrives after nobody is
listening.

So slow commands are started here instead. The tool returns a job id
immediately, the output is streamed to a file on disk, and the agent reads
as much of it as it likes, whenever it likes. Jobs belong to this process
and are killed on shutdown, so nothing keeps running behind the user's
back.

This is deliberately separate from `core.processes`, which supervises the
long-lived service the app itself owns (cloudflared). Jobs here are
agent-initiated and disposable.
"""
from __future__ import annotations

import locale
import os
import re
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path

from core import logs
from core.config import PROJECT_ROOT

# Output lives next to the app, never inside the user's project, so a
# repository is not polluted with our scratch files.
RUNS_DIR = PROJECT_ROOT / ".mcp-runs"
MAX_JOBS = 40

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# A separate process group lets us signal the whole tree instead of only
# the shell we spawned. On Windows `npm` is a batch file wrapping node, so
# the process that actually matters is always a grandchild. Every command
# the agent runs uses these flags, foreground ones included - that is also
# what makes the polite stop below safe to attempt.
_CREATION_FLAGS = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | _NO_WINDOW
CREATION_FLAGS = _CREATION_FLAGS

# How long a process gets to wind itself down before it is killed outright.
GRACE_SECONDS = 5.0


def kill_tree(
    process: subprocess.Popen,
    *,
    grace: float = GRACE_SECONDS,
    timeout: float = 5.0,
) -> str:
    """Stop a process and every child it spawned; report how it ended.

    Two stages, on purpose. First Ctrl+Break to the process group, which pip,
    npm and git read as "the user pressed Ctrl+C": they delete their partial
    archives and temp folders instead of leaving them on disk. Only a process
    that ignores that gets killed outright.

    Killing just the shell is never enough - the real work would keep running
    and keep holding its file locks, which is how a timed-out install used to
    poison the next attempt.
    """
    if process.poll() is not None:
        return "already finished"
    if grace > 0 and os.name == "nt":
        try:
            # Safe only because the child owns its own process group; sent to
            # our own group this would take the servers down with it.
            process.send_signal(signal.CTRL_BREAK_EVENT)
        except Exception:  # noqa: BLE001 - fall through to the hard kill
            pass
        else:
            try:
                process.wait(timeout=grace)
                return "stopped cleanly"
            except subprocess.TimeoutExpired:
                pass
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            creationflags=_NO_WINDOW,
        )
    else:  # pragma: no cover - the target platform is Windows
        process.kill()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
    return "killed"


def _console_encodings() -> list:
    """Code pages Windows console programs fall back to, best guess first."""
    names = []
    if os.name == "nt":
        try:
            import ctypes

            names.append(f"cp{ctypes.windll.kernel32.GetOEMCP()}")
            names.append(f"cp{ctypes.windll.kernel32.GetACP()}")
        except Exception:  # noqa: BLE001
            pass
    names.append(locale.getpreferredencoding(False) or "utf-8")
    return names


_FALLBACKS = _console_encodings()


def decode_line(raw: bytes) -> str:
    """Decode one line of command output.

    Git, Python and Node print UTF-8, while cmd built-ins and many older
    tools print in the console code page (cp866 on a Ukrainian or Russian
    Windows). One command can mix both, so this goes line by line instead
    of guessing once for the whole output.
    """
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    for name in _FALLBACKS:
        try:
            return raw.decode(name)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def child_env() -> dict:
    """Environment for agent commands: UTF-8, unbuffered Python output."""
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


class Job:
    """One background command and the file its output is streamed into."""

    def __init__(self, command: str, cwd: Path, origin: str = "start_process") -> None:
        self.id = uuid.uuid4().hex[:8]
        self.origin = origin
        self.command = command
        self.cwd = cwd
        self.started_at = time.time()
        self.finished_at: float | None = None
        self.exit_code: int | None = None
        self.stopped = False
        self.ending: str | None = None
        self.log_path = RUNS_DIR / (self.id + ".log")
        self._process: subprocess.Popen | None = None
        self._sink = None
        self._lock = threading.RLock()

    # --- lifecycle -------------------------------------------------------

    def start(self) -> None:
        """Spawn the command with its output redirected to the log file.

        Redirecting straight to a file rather than through a pipe means no
        reader thread can fall behind and no pipe buffer can fill up and
        wedge the child, which is a classic way for a chatty build to hang.
        """
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        self._sink = open(self.log_path, "wb")
        self._process = subprocess.Popen(
            self.command,
            shell=True,
            cwd=str(self.cwd),
            # No stdin: a command that asks a question gets end-of-input
            # and fails fast instead of waiting forever for an answer.
            stdin=subprocess.DEVNULL,
            stdout=self._sink,
            stderr=subprocess.STDOUT,
            env=child_env(),
            creationflags=_CREATION_FLAGS,
        )
        logs.log(
            "terminal",
            "job " + self.id + " started (pid "
            + str(self._process.pid) + "): " + self.command,
        )
        threading.Thread(
            target=self._watch, name="job-" + self.id, daemon=True
        ).start()

    def _watch(self) -> None:
        process = self._process
        if process is None:
            return
        code = process.wait()
        with self._lock:
            self.exit_code = code
            self.finished_at = time.time()
            if self._sink is not None:
                try:
                    self._sink.close()
                except OSError:
                    pass
                self._sink = None
        level = "info" if code == 0 else "warn"
        logs.log(
            "terminal",
            "job " + self.id + " finished with exit code " + str(code),
            level=level,
        )

    def stop(self) -> bool:
        """Kill the job. Returns False if it had already finished."""
        with self._lock:
            process = self._process
        if process is None or process.poll() is not None:
            return False
        self.ending = kill_tree(process)
        self.stopped = True
        logs.log(
            "terminal",
            "job " + self.id + " stopped by request (" + self.ending + ")",
            level="warn",
        )
        return True

    # --- state -----------------------------------------------------------

    @property
    def running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    @property
    def pid(self) -> int | None:
        with self._lock:
            return self._process.pid if self._process else None

    def elapsed(self) -> float:
        end = self.finished_at or time.time()
        return max(0.0, end - self.started_at)

    def state(self) -> str:
        if self.running:
            return "running"
        if self.stopped:
            return "stopped"
        return "finished"

    def status_line(self) -> str:
        parts = [
            self.id,
            self.state(),
            str(round(self.elapsed())) + "s",
        ]
        if self.exit_code is not None:
            parts.append("exit " + str(self.exit_code))
        parts.append(self.command)
        return "  ".join(parts)

    # --- output ----------------------------------------------------------

    def read_lines(self) -> list:
        """Every captured line so far, decoded."""
        try:
            with open(self.log_path, "rb") as fh:
                data = fh.read()
        except FileNotFoundError:
            return []
        return [decode_line(line.rstrip(b"\r")) for line in data.split(b"\n")][
            : -1 if data.endswith(b"\n") or not data else None
        ]

    def read_output(self, offset: int = 0, limit: int = 200, tail: int = 0) -> dict:
        """Read the captured output by line, the way a paged file read works.

        Args:
            offset: 0-based line to start from.
            limit: How many lines to return at most.
            tail: When set, return the last `tail` lines instead.
        """
        lines = self.read_lines()
        total = len(lines)
        if tail > 0:
            start = max(0, total - tail)
            window = lines[start:]
        else:
            start = max(0, offset)
            window = lines[start:start + max(1, limit)]
        return {
            "lines": window,
            "total": total,
            "start": start,
            "next_offset": start + len(window),
        }

    def output_matches(self, pattern: "re.Pattern", offset: int = 0) -> bool:
        """True when a line at or after `offset` matches `pattern`."""
        return any(pattern.search(line) for line in self.read_lines()[offset:])

    def discard(self) -> None:
        """Forget the job and delete its output file."""
        self.stop()
        try:
            self.log_path.unlink()
        except OSError:
            pass


class JobRegistry:
    """Every background job this process started, newest last."""

    def __init__(self) -> None:
        self._jobs: dict = {}
        self._lock = threading.RLock()

    def start(self, command: str, cwd: Path, origin: str = "start_process") -> Job:
        job = Job(command, cwd, origin)
        job.start()
        with self._lock:
            self._jobs[job.id] = job
            self._prune()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id.strip())

    def forget(self, job_id: str) -> None:
        """Drop a finished job and its output file."""
        with self._lock:
            job = self._jobs.pop(job_id, None)
        if job is None:
            return
        # The watcher thread closes the output file a moment after the
        # process exits; Windows refuses to delete a file that is open.
        for _ in range(40):
            if job.finished_at is not None:
                break
            time.sleep(0.05)
        job.discard()

    def list_jobs(self) -> list:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.started_at)

    def running_count(self) -> int:
        return sum(1 for job in self.list_jobs() if job.running)

    def stop_all(self) -> None:
        for job in self.list_jobs():
            job.stop()

    def _prune(self) -> None:
        """Drop the oldest finished jobs once the list grows too long."""
        jobs = sorted(self._jobs.values(), key=lambda j: j.started_at)
        surplus = len(jobs) - MAX_JOBS
        for job in jobs:
            if surplus <= 0:
                break
            if job.running:
                continue
            self._jobs.pop(job.id, None)
            job.discard()
            surplus -= 1


registry = JobRegistry()
