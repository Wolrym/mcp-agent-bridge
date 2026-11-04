# MCP Agent Bridge - architecture

Two local MCP servers that let an AI agent work on real projects on this
Windows machine: one for files, one for command execution and context. A
PySide6 control panel starts them, publishes them through a Cloudflare
Tunnel, and shows whether a client can actually reach them.

Single Python codebase (3.10+), no PowerShell orchestration, no Node.

## Layout

```
run_core.py                 headless entry point + ServerSupervisor + port checks
start.bat / start_gui.bat   launchers (with a console)
tools/make_shortcuts.py     creates the windowless and the debug shortcut
assets/                     app icon (.ico for Windows, .png)
config/settings.json        runtime settings (gitignored)
core/
  config.py                 settings store: token, ports, tunnel, limits, security, projects
  projects.py               project registry + active project
  paths.py                  path resolution and the project boundary
  skills.py                 skill discovery: groups, project skill folders, front matter
  logs.py                   ring buffer, live subscribers, console + rotating file sinks
  guard.py                  accident guard for agent shell commands
  processes.py              supervision of cloudflared
  jobs.py                   every agent command runs as a job (output streamed to a file)
  tunnel.py                 cloudflared command building and lifecycle
  health.py                 local and public readiness probes
  backups.py                undo history for every file mutation
  notifier.py               Telegram "agent finished / went idle" messages
servers/
  common.py                 tool registration wrapper + the authenticated HTTP app
  auth.py                   bearer-token middleware, client IP, brute-force brake
  health.py                 token-free /health endpoint
  files_server.py           Files System MCP (port 9500)
  terminal_server.py        Terminal MCP (port 9501)
  tools_files.py            file tools
  tools_terminal.py         command, job, project and skill tools
gui/
  app.py                    QApplication bootstrap: theme, log sinks, single instance
  main_window.py            panel layout and every action
  theme.qss                 stylesheet
  widgets/                  primitives, frameless chrome, setup guide
skills/mcp-coding-agent/    the original skill (kept as it was)
skills/mcp-coding-agent-v2/ the same skill, updated for the current tools
skills/<group>/             third-party skills, local only (gitignored)
tests/                      runnable check scripts, no framework
```

## Key decisions

### One wrapper around every tool

Tools are registered through `servers.common.install(mcp, source)`, which
replaces `mcp.tool` with a wrapper that:

- runs sync tools on a worker thread. FastMCP calls a sync tool inline on
  the event loop, and both servers share one loop, so a slow grep or a big
  read used to freeze every other call and `/health` with it;
- serialises tools that change files (`exclusive=True`), so parallel calls
  cannot interleave their undo-journal writes;
- logs one line per call: tool, the arguments that matter (bulky ones by
  size only), duration, and the error if it failed. The SDK's own
  per-request INFO lines are silenced;
- keeps the idle notifier informed, at the start and at the end of a call;
- turns off structured output. With it on, FastMCP sends every result
  twice - as text and as `structuredContent` - and the agent pays for
  both.

### Sessions

The client observed so far opens a new MCP session for every call and
never closes it, so sessions cannot tell chats apart. The SDK keeps idle
sessions forever by default; `servers.session_idle_seconds` (900) drops
them. Because every chat shares one active project, agents are told to use
absolute paths.

### Own file server

The third-party filesystem server fixes its allowed root at launch, which
makes live project switching impossible, so the file tools live here.
Every call resolves relative paths against the active project root;
absolute paths outside it are refused unless
`security.allow_outside_project` is set.

- Reads are paged (`offset`/`limit`), lines over 2000 characters are
  clipped and a page also stops at a character budget, so one minified
  file cannot flood the context.
- Writes are exact bytes. Edits keep CRLF or LF and the UTF-8 BOM (text
  mode on Windows used to turn `\r\n` into `\r\r\n`). A file that is not
  UTF-8 is refused instead of having its bytes replaced.
- `read_file` returns pictures as image content, so a multimodal agent can
  look at a screenshot. Other binaries get a hint to `pack_files`.
- `pack_files` / `unpack_files` move a base64 zip between this PC and an
  agent's own sandbox. Unpacking checks for zip-slip, never overwrites
  without `overwrite=true`, and records undo entries.
- `config/settings.json` cannot be written by an agent.

### Undo history

Every write, edit, move and delete stores the previous bytes under
`.mcp-backups/` with a journal entry (when `backups.enabled`).
`list_changes` shows recent ones and `undo_change` restores one, refusing
when the file changed afterwards.

### Commands and background jobs

A tool call is an HTTP request and the client stops waiting after about a
minute. So every command, quick or slow, runs as a job whose output
streams to a file under `.mcp-runs/`:

- `run_command` starts the job and waits up to 45 s (hard ceiling 50).
  If the command finishes, the reply is its full output and the job is
  forgotten. If not, nothing is killed: the job keeps running and the
  reply hands over its id. The agent no longer has to guess in advance
  whether something is quick.
- `wait_process` waits for a job and returns as soon as it ends or a new
  line matches `until` - one call instead of sleep + poll. `get_output`
  reads immediately (paged or `tail`).
- Jobs get `stdin=DEVNULL` (a command waiting for input used to hang until
  the timeout) and `PYTHONIOENCODING=utf-8`. Output is decoded per line as
  UTF-8, falling back to the console code page, so Cyrillic from cmd.exe
  is no longer mojibake.
- Stopping is two-stage (`core.jobs.kill_tree`): Ctrl+Break to the
  process group first, then `taskkill /T /F`. The reply says which one it
  took, so the agent knows whether on-disk state may be half-written.
  Jobs are stopped when the servers stop, so nothing is orphaned.
- `core.guard` refuses a short list of machine-wrecking commands and
  commands that would kill this app or its tunnel. It is a seatbelt
  against a confused agent, not a security boundary.

### Skills

`skills/` holds the bridge's own skills at the top level. A folder
without a `SKILL.md` that contains skill folders is a group (`design/`,
`animation/`, `frontend/`); `list_skills` shows groups collapsed to one
line, and `list_skills(group=...)` opens one. Projects can bring their
own skills in `.agents/skills`, `.claude/skills` or `.opencode/skills`;
`list_skills(project=...)` and `get_skill(name, project=...)` include
them, and a project skill wins a name clash. Front matter supports YAML
block scalars (`description: >-`). `get_skill` lists every bundled file.

### Startup, ports and logs

Ports are probed before uvicorn binds them; a busy port produces one
readable log line instead of a traceback. The panel holds a lock file, so
a second copy refuses to start. Under `pythonw.exe` there is no console:
`sys.stdout`/`stderr` are pointed at the null device (uvicorn crashed on
`None.isatty()`), and every log line plus any unhandled exception goes to
`logs/bridge.log`.

### Auth and tunnel

Every request needs `Authorization: Bearer <token>`; `/health` is the only
exception and reveals only the server name. The client address comes from
`CF-Connecting-IP` behind the tunnel; 20 wrong tokens in five minutes block
an address for 15 minutes (loopback never). `cloudflared` runs as a child
process of the panel with the user's own config:

```yaml
tunnel: <tunnel-name>
ingress:
  - hostname: <user>-files.<domain>
    service: http://localhost:9500
  - hostname: <user>-term.<domain>
    service: http://localhost:9501
  - service: http_status:404
```

### Readiness

`core/health.py` probes both local ports and both public hostnames and
reduces them to one state: `Ready (public)`, `Running locally`,
`Starting...` or `Not running`. Cloudflare blocks a `Python-urllib` user
agent with error 1010, so the probe sends a browser-like one.

### GUI

PySide6 with a frameless custom title bar. Cards for servers, tunnel,
projects, connection details and the live log, plus a setup guide window
with URLs, token, a config snippet and the skill texts. `gui.autostart`
brings everything up as soon as the panel opens.

## Tests

Plain scripts, run individually with `python tests\<name>.py`:
`tools_test.py`, `smoke_test.py`, `jobs_test.py`, `backups_test.py`,
`test_notifier.py`, `gui_controls_test.py`, `health_selftest.py`,
`probe_health.py`. None of them writes the real settings file.

## Open items

- Windows Job Object for `cloudflared`, so a hard-killed panel cannot
  orphan it.
- Agent memory across chats lives in the skill, not the server: the
  `mcp-coding-agent-brief` variant keeps `.agent/STATE.md`, small
  conventional commits and checkpoint tags in each project.
