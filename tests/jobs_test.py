"""Checks for background jobs, command timeouts and port conflicts.

Run it directly:

    python tests\\jobs_test.py

Everything here runs real processes, because the bugs being guarded
against - a timeout that leaves child processes alive, a blocked event
loop, a port conflict reported as a traceback - only show up with real
ones.
"""
from __future__ import annotations

import asyncio
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import run_core  # noqa: E402
from core import jobs  # noqa: E402
from servers import tools_terminal  # noqa: E402

failures = []


def check(label: str, condition: bool, detail: str = "") -> None:
    mark = "ok  " if condition else "FAIL"
    print(mark + " " + label + (("  " + detail) if detail else ""))
    if not condition:
        failures.append(label)


def py(code: str) -> str:
    """Build a one-liner command that survives cmd.exe quoting.

    The interpreter path contains a space on this machine, so it has to be
    quoted, and the code must stay on a single line: cmd.exe mangles
    embedded newlines inside -c.
    """
    return '"' + sys.executable + '" -c "' + code + '"'


def test_short_command() -> None:
    result = tools_terminal._execute(py("print('hi')"), ROOT, 30)
    check("a quick command succeeds", result.get("exit_code") == 0)
    check("its output comes back", "hi" in (result.get("stdout") or ""))


def test_timeout_kills_the_tree() -> None:
    started = time.time()
    result = tools_terminal._execute(py("import time; time.sleep(45)"), ROOT, 2)
    elapsed = time.time() - started
    check("a timeout is reported", result.get("timed_out") is True)
    check("and it returns promptly", elapsed < 20, str(round(elapsed, 1)) + "s")


def test_command_does_not_block_the_loop() -> None:
    """The whole point of the fix: other work continues while a command runs."""

    async def scenario() -> int:
        ticks = 0

        async def tick() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0.05)
                ticks += 1

        ticker = asyncio.create_task(tick())
        await asyncio.to_thread(
            tools_terminal._execute, py("import time; time.sleep(1.5)"), ROOT, 30
        )
        ticker.cancel()
        return ticks

    ticks = asyncio.run(scenario())
    check("the event loop keeps running", ticks > 5, str(ticks) + " ticks")


def test_job_runs_to_completion() -> None:
    job = jobs.registry.start(
        py("import time; [(print('line', i, flush=True), time.sleep(0.4)) for i in range(3)]"),
        ROOT,
    )
    check("the job starts immediately", job.running is True)

    deadline = time.time() + 30
    while job.running and time.time() < deadline:
        time.sleep(0.2)

    check("it finishes", job.running is False)
    check("with a clean exit code", job.exit_code == 0, str(job.exit_code))
    check("and it is no longer listed as running", jobs.registry.running_count() == 0)

    page = job.read_output(offset=0, limit=2)
    check("output is paged", len(page["lines"]) == 2 and page["total"] == 3, str(page["total"]) + " lines")
    rest = job.read_output(offset=page["next_offset"], limit=200)
    check("the next offset continues", len(rest["lines"]) == 1)
    check("the job is findable by id", jobs.registry.get(job.id) is job)


def test_job_can_be_stopped() -> None:
    job = jobs.registry.start(py("import time; time.sleep(120)"), ROOT)
    time.sleep(0.5)
    check("a long job stays running", job.running is True)
    started = time.time()
    check("stopping it reports success", job.stop() is True)
    elapsed = time.time() - started
    check("and it really is gone", job.running is False)
    check(
        "the outcome is recorded",
        job.ending in {"stopped cleanly", "killed"},
        str(job.ending),
    )
    # The polite Ctrl+Break gets a few seconds; a hard kill must not be
    # delayed longer than that grace period.
    check(
        "stopping does not drag on",
        elapsed < jobs.GRACE_SECONDS + 10,
        str(round(elapsed, 1)) + "s",
    )
    check("stopping twice is harmless", job.stop() is False)
    check("its state reads as stopped", job.state() == "stopped", job.state())
    job.discard()


def test_port_conflict_is_explained() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        port = taken.getsockname()[1]
        message = run_core.port_conflict("127.0.0.1", port)
        check("a busy port is detected", bool(message))
        check("the message names the port", str(port) in message)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    check("a free port passes", run_core.port_conflict("127.0.0.1", free_port) == "")


def main() -> int:
    test_short_command()
    test_timeout_kills_the_tree()
    test_command_does_not_block_the_loop()
    test_job_runs_to_completion()
    test_job_can_be_stopped()
    test_port_conflict_is_explained()

    jobs.registry.stop_all()
    print()
    if failures:
        print(str(len(failures)) + " check(s) failed: " + ", ".join(failures))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
