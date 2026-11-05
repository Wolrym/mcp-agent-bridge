"""Terminal MCP tools.

Execution and context only: running commands, reporting which project is
active, and serving coding skills. Anything that reads or writes files
lives in the Files System server instead.

Every command - quick or slow - runs as a job whose output streams to a
file. run_command simply waits for its job for a while: if the command
finishes in time the reply is the full result, and if it does not, the
job keeps running and the reply hands over its id. Nothing is killed just
because the client's one-minute request window ran out.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path

from core import guard, jobs, logs, notifier, paths, projects, skills
from core.config import settings
from servers.common import install

# The client abandons a request after about a minute, so no single call
# may wait longer than this, whatever the settings say.
CLIENT_SAFE_WAIT = 50


def _limit(name: str, fallback: int) -> int:
    return int(settings.get("limits", name, default=fallback) or fallback)


def _wait_budget(requested: int, default: int) -> int:
    ceiling = min(
        _limit("command_timeout_max", CLIENT_SAFE_WAIT),
        _limit("wait_seconds_max", CLIENT_SAFE_WAIT),
        CLIENT_SAFE_WAIT,
    )
    return max(1, min(requested or default, ceiling))


def _clip(text: str, cap: int) -> str:
    """Keep the head and the tail of an oversized output."""
    if len(text) <= cap:
        return text
    head = text[: cap // 3]
    tail = text[-(cap - len(head)):]
    dropped = len(text) - len(head) - len(tail)
    return f"{head}\n... ({dropped} characters cut from the middle) ...\n{tail}"


def _format_job_output(job, offset: int = 0, limit: int = 200, tail: int = 0) -> str:
    """Render a job's status and a page of its output."""
    page = job.read_output(
        offset=offset, limit=min(limit, _limit("max_read_lines", 900)), tail=tail
    )
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
    body = _clip("\n".join(page["lines"]), _limit("max_output_chars", 100000))
    tail_note = []
    remaining = total - page["next_offset"]
    if remaining > 0:
        tail_note.append(
            f"[{remaining} more line(s) - continue with offset={page['next_offset']}]"
        )
    elif job.running:
        tail_note.append(
            f"[end of output so far - next read: offset={page['next_offset']}]"
        )
    return "\n".join(head + ["--- output ---", body] + tail_note)


async def _wait(job, seconds: int, pattern=None, offset: int = 0) -> bool:
    """Wait until the job ends, `pattern` shows up, or time runs out.

    Returns True when the pattern matched.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds

    async def matches() -> bool:
        # Reading the output file is blocking I/O; keep it off the loop
        # both servers share.
        return await asyncio.to_thread(job.output_matches, pattern, offset)

    while job.running and loop.time() < deadline:
        if pattern is not None and await matches():
            return True
        await asyncio.sleep(0.25 if pattern is None else 0.5)
    return pattern is not None and await matches()


def _collect(job) -> tuple:
    """Read a finished job's output and drop the job (blocking)."""
    lines = job.read_lines()
    exit_code = job.exit_code
    jobs.registry.forget(job.id)
    return lines, exit_code


def _working_dir(cwd: str) -> Path:
    working_dir = paths.resolve(cwd, must_exist=True)
    if not working_dir.is_dir():
        raise paths.PathError(f"not a directory: {working_dir}")
    return working_dir


def register(mcp) -> None:
    """Attach every terminal tool to the given FastMCP instance."""
    install(mcp, "terminal")

    @mcp.tool()
    async def run_command(command: str, cwd: str = "", timeout: int = 0) -> str:
        """Run a shell command and wait for its result.

        The machine is Windows and commands go through cmd.exe: use cmd
        syntax, or wrap PowerShell explicitly with
        powershell -NoProfile -Command "...".

        The client gives up on a call after about a minute, so this waits
        at most `timeout` seconds (never more than 50). A command still
        running by then is NOT killed: it carries on as a background job,
        and the reply gives the job id for wait_process, get_output and
        stop_process. There is no need to guess in advance whether
        something is quick.

        Args:
            command: Command line to execute.
            cwd: Working directory. Use an absolute path. Defaults to the
                active project root.
            timeout: Seconds to wait before leaving the command running in
                the background. 0 uses the default (45).
        """
        if not command.strip():
            return "Error: command is required."
        blocked = guard.check(command)
        if blocked:
            logs.log("terminal", f"Blocked: {command}", level="warn")
            return "Error: " + blocked
        try:
            working_dir = _working_dir(cwd)
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"

        budget = _wait_budget(timeout, _limit("command_timeout", 45))
        try:
            job = await asyncio.to_thread(
                jobs.registry.start, command, working_dir, "run_command"
            )
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"
        await _wait(job, budget)

        if job.running:
            logs.log("terminal", f"job {job.id} still running after {budget}s, left in background")
            return "\n".join([
                f"$ {command}",
                f"(cwd: {working_dir})",
                f"still running after {budget}s, so it was left running in the "
                f"background as job {job.id} (nothing was stopped).",
                f"Next: wait_process(job_id=\"{job.id}\") to wait for it, or "
                f"stop_process(job_id=\"{job.id}\") if it is stuck.",
                _format_job_output(job, tail=30),
            ])

        lines, exit_code = await asyncio.to_thread(_collect, job)
        parts = [f"$ {command}", f"(cwd: {working_dir})", f"exit code: {exit_code}"]
        if lines:
            text = "\n".join(lines).rstrip()
            parts += ["--- output ---", _clip(text, _limit("max_output_chars", 100000))]
        else:
            parts.append("(no output)")
        return "\n".join(parts)

    @mcp.tool()
    def start_process(command: str, cwd: str = "") -> str:
        """Start a command in the background and return at once.

        For dev servers, watchers, and anything you want to keep running
        while you do other work. Read its output with wait_process or
        get_output, end it with stop_process. (A slow build or install can
        also simply go through run_command: it backgrounds itself.)

        Args:
            command: Command line to execute.
            cwd: Working directory. Use an absolute path. Defaults to the
                active project root.
        """
        if not command.strip():
            return "Error: command is required."
        blocked = guard.check(command)
        if blocked:
            logs.log("terminal", f"Blocked: {command}", level="warn")
            return "Error: " + blocked
        try:
            working_dir = _working_dir(cwd)
            job = jobs.registry.start(command, working_dir)
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"

        return "\n".join([
            f"Started job {job.id} (pid {job.pid})",
            f"$ {command}",
            f"(cwd: {working_dir})",
            f"Next: wait_process(job_id=\"{job.id}\"), optionally with until= "
            "a regex such as \"ready|listening|error\" for a server.",
        ])

    @mcp.tool()
    def get_output(job_id: str, offset: int = 0, limit: int = 200, tail: int = 0) -> str:
        """Read the output of a background job, right now.

        Args:
            job_id: Id returned by start_process or run_command.
            offset: First output line to return, 0-based. Pass the offset
                from the previous read to continue where you stopped.
            limit: How many lines to return at most.
            tail: Return only the last N lines instead - the useful part of
                a long build or test log.
        """
        job = jobs.registry.get(job_id)
        if job is None:
            return (
                f"Error: no job '{job_id}'. Call list_processes to see the "
                "jobs this session knows about."
            )
        return _format_job_output(job, offset, limit, tail)

    @mcp.tool()
    async def wait_process(
        job_id: str,
        seconds: int = 20,
        offset: int = 0,
        limit: int = 200,
        until: str = "",
        tail: int = 0,
    ) -> str:
        """Wait for a background job, then report its output.

        Returns as soon as the job finishes, or as soon as a new output
        line matches `until`, so you never wait longer than needed. One
        call replaces a sleep plus a poll. If the job is still running
        when the wait runs out, just call this again.

        Args:
            job_id: Id returned by start_process or run_command.
            seconds: Longest wait, capped at 50 (the client's request
                window). 0 uses 20.
            offset: First output line to return and to search, 0-based.
            limit: How many lines to return at most.
            until: Optional regex, e.g. "ready|listening|error|failed".
            tail: Return only the last N lines.
        """
        job = jobs.registry.get(job_id)
        if job is None:
            return (
                f"Error: no job '{job_id}'. Call list_processes to see the "
                "jobs this session knows about."
            )
        pattern = None
        if until:
            try:
                pattern = re.compile(until, re.IGNORECASE)
            except re.error as exc:
                return f"Error: until is not a valid regex: {exc}"
        matched = await _wait(job, _wait_budget(seconds, 20), pattern, offset)
        report = _format_job_output(job, offset, limit, tail)
        if pattern is not None and job.running:
            note = "matched until=" if matched else "no line matched until="
            report = f"[{note}{until!r}]\n" + report
        return report

    @mcp.tool()
    def stop_process(job_id: str) -> str:
        """Stop a background job and every process it spawned.

        Args:
            job_id: Id returned by start_process or run_command.
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
        """List the background jobs this app is tracking, oldest first."""
        found = jobs.registry.list_jobs()
        if not found:
            return "No background jobs."
        lines = [f"{len(found)} job(s), {jobs.registry.running_count()} still running:"]
        lines += ["  " + job.status_line() for job in found]
        return "\n".join(lines)

    @mcp.tool()
    def get_active_project() -> str:
        """Report the default project: where relative paths and a missing cwd resolve.

        Prefer absolute paths anyway; the user may run several agents on
        different projects at once, and this default is shared by all of
        them.
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
        outside = bool(settings.get("security", "allow_outside_project", default=False))
        lines.append(
            "access outside this folder: "
            + ("allowed (use absolute paths)" if outside else "refused")
        )
        log_file = logs.file_path()
        if log_file:
            lines.append(
                f"call log: {log_file} - every tool call, one line each; grep it "
                "for your project folder to see what earlier chats did"
            )
        others = [p for p in projects.list_projects() if p["id"] != project["id"]]
        if others:
            lines.append(
                "other registered projects: "
                + ", ".join(f"{p['name']} ({p['root']})" for p in others)
            )
        return "\n".join(lines)

    @mcp.tool()
    def list_skills(query: str = "", group: str = "", project: str = "") -> str:
        """List the available skills (instructions for specific kinds of work).

        Global skills (the bridge's own and those installed with
        `npx skills`; groups and categories collapsed to one line) and, with
        `project`, that project's skills and its instruction files
        (AGENTS.md, CLAUDE.md, GEMINI.md). Call it with `project` before the
        first change in a project. Re-scanned on every call.

        Args:
            query: Case-insensitive filter on name and description, across
                every group.
            group: Show the skills of one group or category, e.g. "design".
            project: Absolute project folder: adds its .agents/skills,
                .agent/skills, .claude/skills, .opencode/skills and its
                instruction files.
        """
        try:
            found = skills.discover(project or None)
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"
        instructions = skills.project_instructions(project or None)
        if not found and not instructions:
            where = f"{skills.skills_root()}" + (f" or {project}" if project else "")
            return f"No skills found in {where}"

        needle = query.strip().lower()
        wanted = group.strip().strip("/").lower()
        if needle:
            found = [
                s for s in found
                if needle in s["name"].lower() or needle in s["description"].lower()
                or needle in s["group"].lower()
            ]
            if not found:
                return f"No skills match '{query}'. Call list_skills with no query to see all."
            return "\n".join([f"{len(found)} skill(s) matching '{query}':", ""]
                             + [skills.describe(s) for s in found])
        if wanted:
            found = [s for s in found if s["group"].lower() == wanted]
            if not found:
                return f"No group '{group}'. Call list_skills with no arguments to see groups."
            return "\n".join([f"Group {wanted}: {len(found)} skill(s)", ""]
                             + [skills.describe(s) for s in found])

        top = [s for s in found if not s["group"] and s["origin"] == "bridge"]
        core = [s for s in top if s["source"] != "installed"]
        installed = [s for s in top if s["source"] == "installed"]
        local = [s for s in found if s["origin"] == "project"]
        groups: dict = {}
        for s in found:
            if s["group"] and s["origin"] == "bridge":
                groups.setdefault(s["group"], []).append(s["slug"])

        lines = [f"Global skills ({skills.skills_root()}):", ""]
        lines += [skills.describe(s) for s in core] or ["(no top-level skills)"]
        if installed:
            lines += ["", "Installed with npx skills:"]
            lines += [skills.describe(s) for s in installed]
        if groups:
            lines += ["", "Groups (list_skills(group=...) shows descriptions):"]
            for name, members in sorted(groups.items()):
                preview = ", ".join(members[:6]) + (", ..." if len(members) > 6 else "")
                lines.append(f"- {name}/  {len(members)} skills: {preview}")
        if not project:
            lines += ["", "Pass project=<folder> to add that project's own skills "
                          "and its AGENTS.md / CLAUDE.md."]
            return "\n".join(lines)

        lines += ["", f"Project {project}:"]
        if instructions:
            lines.append("Instructions - read these before changing anything:")
            lines += [
                f"- {path.name} ({size} B)" if size < 1024 else f"- {path.name} ({size / 1024:.1f} KB)"
                for path, size in instructions
            ]
        if local:
            shadowed = {s["slug"].lower() for s in top} | {s["name"].lower() for s in top}
            lines.append("Project skills (they win over a global skill with the same name):")
            for s in local:
                note = "  [overrides the global one]" if (
                    s["slug"].lower() in shadowed or s["name"].lower() in shadowed
                ) else ""
                lines.append(skills.describe(s) + note)
        if not instructions and not local:
            lines.append("(no AGENTS.md / CLAUDE.md and no project skills)")
        return "\n".join(lines)

    @mcp.tool()
    def get_skill(name: str, project: str = "") -> str:
        """Fetch the full text of a skill, plus the list of its bundled files.

        Args:
            name: Skill name, e.g. "mcp-coding-agent-v2" or "design/impeccable".
            project: Project folder, to also search its own skills.
        """
        if not name.strip():
            return "Error: a skill name is required."

        skill, candidates = skills.find(name, project or None)
        if skill is None:
            if not candidates:
                return f"No skills found in {skills.skills_root()}"
            names = ", ".join(sorted(skills.qualified(c) for c in candidates[:40]))
            return f"No single match for '{name}'. Available or close: {names}"

        try:
            content = Path(skill["file"]).read_text(encoding="utf-8")
        except OSError as exc:
            return f"Error reading skill '{skill['slug']}': {exc}"

        header = [f"# Skill: {skill['name']}", f"(source: {skill['file']})"]
        bundled = skills.bundled_files(skill)
        if bundled:
            header += ["", f"Bundled files under {skill['dir']} (read them only if needed):"]
            header += [f"  - {ref}" for ref in bundled]
        header += ["", "=" * 60, ""]
        return "\n".join(header) + content

    @mcp.tool()
    def notify_user(message: str = "") -> str:
        """Send the user a short Telegram message that the task is finished.

        Call it once, at the very end, when all files and commands are done.

        Args:
            message: Concise summary of what was accomplished (1-3 sentences).
        """
        cfg = settings.get("notifications", default={}) or {}
        if not cfg.get("notify_tool_enabled", True):
            return "Notification tool is disabled in settings."
        ok, res = notifier.notify_from_agent(message)
        return res
