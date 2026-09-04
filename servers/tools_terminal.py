"""Terminal MCP tools.

Execution and context only: running commands, reporting which project is
active, and serving coding skills. Anything that reads or writes files
lives in the Files System server instead.
"""
from __future__ import annotations

import asyncio
import subprocess
from datetime import datetime
from pathlib import Path

from core import jobs, logs, paths, projects, skills
from core.config import settings


def _limit(name: str, fallback: int) -> int:
    return int(settings.get("limits", name, default=fallback) or fallback)


def _truncate(text: str, cap: int) -> str:
    if len(text) <= cap:
        return text
    return text[:cap] + f"\n... (truncated at {cap} characters)"


def _format_job_output(job, offset: int = 0, limit: int = 200) -> str:
    """Render a job's status and a page of its output. Shared by get_output
    and wait_process so both report output the same way."""
    page = job.read_output(offset=offset, limit=min(limit, _limit("max_read_lines", 900)))
    head = [
        f"job {job.id}: {job.state()} after {round(job.elapsed())}s",
        f"$ {job.command}",
    ]
    if job.exit_code is not None:
        head.append(f"exit code: {job.exit_code}")

    total = page["total"]
    shown = len(page["lines"])
    if not total:
        head.append("(no output yet)")
        return "\n".join(head)

    first = page["start"] + 1
    head.append(f"[output: lines {first}-{page['start'] + shown} of {total}]")
    body = "\n".join(page["lines"])
    tail = []
    remaining = total - page["next_offset"]
    if remaining > 0:
        tail.append(
            f"[{remaining} more line(s) - continue with "
            f"offset={page['next_offset']}]"
        )
    elif job.running:
        tail.append(
            "[still running - call again later with "
            f"offset={page['next_offset']} for new output]"
        )
    return "\n".join(head + ["--- output ---", body] + tail)


def _execute(command: str, working_dir: Path, seconds: int) -> dict:
    """Run a command to completion. Always called on a worker thread."""
    try:
        process = subprocess.Popen(
            command,
            shell=True,
            cwd=str(working_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            # Own process group: required for the polite Ctrl+Break below,
            # and it keeps stray console windows from appearing.
            creationflags=jobs.CREATION_FLAGS,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}

    try:
        stdout, stderr = process.communicate(timeout=seconds)
    except subprocess.TimeoutExpired:
        # Stop the whole tree, asking nicely first so pip or npm can clear
        # its partial downloads. Terminating only the shell would leave the
        # real work - node, msbuild, pip - running and holding file locks,
        # which is how a timed-out install used to poison the next attempt.
        ending = jobs.kill_tree(process)
        stdout, stderr = process.communicate()
        return {
            "timed_out": True,
            "ending": ending,
            "stdout": stdout,
            "stderr": stderr,
        }
    return {"exit_code": process.returncode, "stdout": stdout, "stderr": stderr}


def register(mcp) -> None:
    """Attach every terminal tool to the given FastMCP instance."""

    @mcp.tool()
    async def run_command(command: str, cwd: str = "", timeout: int = 0) -> str:
        """Run a short shell command inside the active project and wait for it.

        The machine is Windows, so commands must be PowerShell or CMD
        compatible.

        Use this only for work that finishes quickly. A tool call is an HTTP
        request and the client stops waiting after about a minute, so
        installs, builds, test suites and dev servers belong in
        start_process instead - asking for a longer timeout here cannot
        work, the answer would arrive after nobody is listening.

        Args:
            command: Command line to execute.
            cwd: Working directory, absolute or relative to the project.
                Defaults to the project root.
            timeout: Seconds before the command is aborted. 0 uses the
                configured default. Anything above the configured maximum is
                clamped down to it.
        """
        if not command.strip():
            return "Error: command is required."

        requested = timeout or _limit("command_timeout", 60)
        ceiling = _limit("command_timeout_max", 120)
        seconds = max(1, min(requested, ceiling))
        try:
            working_dir = paths.resolve(cwd, must_exist=True)
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"
        if not working_dir.is_dir():
            return f"Error: not a directory: {working_dir}"

        logs.log("terminal", f"$ {command}  (cwd: {working_dir})")
        # The command runs on a worker thread. Executing it inline would
        # block the event loop that serves both MCP servers, so one slow
        # command would freeze every other tool call - and the health check
        # with them - until it finished.
        result = await asyncio.to_thread(_execute, command, working_dir, seconds)

        if result.get("error"):
            return f"Error: {result['error']}"

        cap = _limit("max_output_chars", 100000)
        parts = [f"$ {command}", f"(cwd: {working_dir})"]
        if seconds < requested:
            parts.append(
                f"note: timeout lowered from {requested}s to the {seconds}s "
                "maximum; use start_process for work that takes longer"
            )
        if result.get("timed_out"):
            logs.log("terminal", f"Command timed out after {seconds}s", level="warn")
            ending = result.get("ending") or "killed"
            note = (
                f"timed out after {seconds} seconds - the command and its "
                f"child processes were stopped ({ending})."
            )
            if ending != "stopped cleanly":
                note += (
                    " It did not shut down on request, so whatever it was "
                    "writing may be half-finished; re-running the same "
                    "command normally completes it."
                )
            note += (
                " If it simply needs more time, run it with start_process "
                "and read the output with get_output."
            )
            parts.append(note)
        else:
            parts.append(f"exit code: {result['exit_code']}")

        stdout = result.get("stdout") or ""
        stderr = result.get("stderr") or ""
        if stdout:
            parts += ["--- stdout ---", _truncate(stdout.rstrip(), cap)]
        if stderr:
            parts += ["--- stderr ---", _truncate(stderr.rstrip(), cap)]
        if not stdout and not stderr:
            parts.append("(no output)")
        return "\n".join(parts)

    @mcp.tool()
    def start_process(command: str, cwd: str = "") -> str:
        """Start a long-running command in the background and return at once.

        This is the right tool for installs, builds, test suites, linters on
        a big tree, and dev servers. The command keeps running on the user's
        machine after this call returns; read its output with get_output and
        end it with stop_process.

        Args:
            command: Command line to execute.
            cwd: Working directory, absolute or relative to the project.
                Defaults to the project root.
        """
        if not command.strip():
            return "Error: command is required."
        try:
            working_dir = paths.resolve(cwd, must_exist=True)
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"
        if not working_dir.is_dir():
            return f"Error: not a directory: {working_dir}"

        try:
            job = jobs.registry.start(command, working_dir)
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"

        return "\n".join([
            f"Started job {job.id} (pid {job.pid})",
            f"$ {command}",
            f"(cwd: {working_dir})",
            "Read the output with get_output(\"" + job.id + "\"). Give it a few "
            "seconds before the first read, and keep reading from the "
            "returned next offset until the job reports that it finished.",
        ])

    @mcp.tool()
    def get_output(job_id: str, offset: int = 0, limit: int = 200) -> str:
        """Read the output of a background job started with start_process.

        Args:
            job_id: Id returned by start_process.
            offset: First output line to return, 0-based. Pass the offset
                from the previous read to continue where you stopped.
            limit: How many lines to return at most.
        """
        job = jobs.registry.get(job_id)
        if job is None:
            return (
                f"Error: no job '{job_id}'. Call list_processes to see the "
                "jobs this session knows about."
            )
        return _format_job_output(job, offset, limit)

    @mcp.tool()
    async def wait_process(
        job_id: str, seconds: int = 20, offset: int = 0, limit: int = 200
    ) -> str:
        """Pause for a background job to progress, then report its output.

        Use this instead of calling get_output back-to-back while a job is
        still running: it waits here instead of spending a whole extra tool
        call to learn "nothing new yet". If the job finishes early, this
        returns immediately with the result instead of waiting out the full
        time.

        A tool call cannot wait past about a minute before Notion's client
        gives up, so seconds is capped comfortably under that. If the job is
        still running when this returns, just call it again - repeatedly, if
        one wait is not enough.

        Args:
            job_id: Id returned by start_process.
            seconds: How long to wait if the job is still running, at most
                the configured ceiling. 0 uses a short default.
            offset: First output line to return, 0-based, same as get_output.
            limit: How many lines to return at most.
        """
        job = jobs.registry.get(job_id)
        if job is None:
            return (
                f"Error: no job '{job_id}'. Call list_processes to see the "
                "jobs this session knows about."
            )

        ceiling = _limit("wait_seconds_max", 50)
        budget = max(1, min(seconds or 20, ceiling))
        loop = asyncio.get_event_loop()
        deadline = loop.time() + budget
        while job.running and loop.time() < deadline:
            await asyncio.sleep(0.5)

        return _format_job_output(job, offset, limit)

    @mcp.tool()
    def stop_process(job_id: str) -> str:
        """Stop a background job and every process it spawned.

        Args:
            job_id: Id returned by start_process.
        """
        job = jobs.registry.get(job_id)
        if job is None:
            return f"Error: no job '{job_id}'."
        if job.stop():
            ending = job.ending or "killed"
            message = f"Stopped job {job.id} and its child processes ({ending})."
            if ending != "stopped cleanly":
                message += (
                    " It ignored the shutdown request, so anything it was "
                    "writing may be half-finished."
                )
            return message
        return (
            f"Job {job.id} had already finished"
            + (f" with exit code {job.exit_code}." if job.exit_code is not None else ".")
        )

    @mcp.tool()
    def list_processes() -> str:
        """List the background jobs started in this session, oldest first."""
        found = jobs.registry.list_jobs()
        if not found:
            return "No background jobs. Start one with start_process."
        lines = [f"{len(found)} job(s), {jobs.registry.running_count()} still running:"]
        lines += ["  " + job.status_line() for job in found]
        return "\n".join(lines)

    @mcp.tool()
    def get_active_project() -> str:
        """Report which project the file and command tools are working in.

        Call this at the start of a session to confirm you are in the right
        project before touching anything.
        """
        try:
            project = projects.active_project()
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"

        lines = [
            f"name: {project['name']}",
            f"id: {project['id']}",
            f"root: {project['root']}",
        ]
        selected_at = project.get("selected_at")
        if selected_at:
            stamp = datetime.fromtimestamp(selected_at).strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"selected at: {stamp}")

        others = [p for p in projects.list_projects() if p["id"] != project["id"]]
        if others:
            lines.append(
                "other registered projects: "
                + ", ".join(f"{p['name']} ({p['id']})" for p in others)
            )
        lines.append(
            "The active project is chosen by the user in the control panel. "
            "If it is not the one you expect, stop and ask before making changes."
        )
        return "\n".join(lines)

    @mcp.tool()
    def list_skills(query: str = "") -> str:
        """List the available coding skills.

        The skills folder is re-scanned on every call, so new skills appear
        automatically.

        Args:
            query: Optional case-insensitive filter on name and description.
        """
        found = skills.discover()
        if not found:
            return f"No skills found in {skills.skills_root()}"

        needle = query.strip().lower()
        if needle:
            found = [
                s for s in found
                if needle in s["name"].lower() or needle in s["description"].lower()
            ]
            if not found:
                return (
                    f"No skills match '{query}'. "
                    "Call list_skills with no query to see all."
                )

        lines = [f"Found {len(found)} skill(s) in {skills.skills_root()}:", ""]
        for skill in found:
            description = " ".join(skill["description"].split())
            if len(description) > 220:
                description = description[:217] + "..."
            lines.append(
                f"- {skill['slug']}: {description}" if description else f"- {skill['slug']}"
            )
        return "\n".join(lines)

    @mcp.tool()
    def get_skill(name: str) -> str:
        """Fetch the full text of a coding skill by name.

        Args:
            name: Skill name, for example "clean-code".
        """
        if not name.strip():
            return "Error: a skill name is required."

        skill, candidates = skills.find(name)
        if skill is None:
            if not candidates:
                return f"No skills found in {skills.skills_root()}"
            names = ", ".join(sorted(c["slug"] for c in candidates))
            return f"No single match for '{name}'. Available or close: {names}"

        try:
            with open(skill["file"], "r", encoding="utf-8") as fh:
                content = fh.read()
        except OSError as exc:
            return f"Error reading skill '{skill['slug']}': {exc}"

        header = [f"# Skill: {skill['name']}", f"(source: {skill['file']})"]
        if skill.get("references"):
            header += ["", "Bundled reference files (read them if you need them):"]
            header += [f"  - {ref}" for ref in skill["references"]]
        header += ["", "=" * 60, ""]
        return "\n".join(header) + content
