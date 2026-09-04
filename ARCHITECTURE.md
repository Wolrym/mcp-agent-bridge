# Notion MCP Connect

Two local MCP servers that let a Notion agent work on real projects on this
Windows machine: one for files, one for command execution and context. A
PySide6 control panel starts them, publishes them through a Cloudflare
Tunnel, and shows whether Notion can actually reach them.

Single Python codebase, no PowerShell orchestration, no Node.

## Layout

```
run_core.py                 headless entry point + ServerSupervisor + port checks
start.bat / start_gui.bat   launchers
config/settings.json        runtime settings (gitignored)
core/
  config.py                 settings store: token, ports, tunnel, limits, projects, gui
  projects.py               project registry + active project
  paths.py                  path resolution and the project sandbox
  skills.py                 skill discovery under skills/
  logs.py                   ring buffer + live subscribers (the GUI listens)
  processes.py              supervision of cloudflared
  jobs.py                   background jobs the agent starts (long commands)
  tunnel.py                 cloudflared command building and lifecycle
  health.py                 local and public readiness probes
  backups.py                undo history for every file mutation
servers/
  auth.py                   bearer-token middleware
  health.py                 token-free /health endpoint
  files_server.py           Files System MCP (port 9500)
  terminal_server.py        Terminal MCP (port 9501)
  tools_files.py            file tools
  tools_terminal.py         command, job, project and skill tools
gui/
  app.py                    QApplication bootstrap, theme, autostart
  main_window.py            panel layout and every action
  theme.qss                 shadcn-like zinc tokens
  widgets/                  primitives, frameless chrome, setup guide
skills/mcp-coding-agent/    the skill the agent loads in a chat
tests/                      runnable check scripts, no framework
```

## Key decisions

### Own file server

The third-party filesystem server fixes its allowed root at launch, which
makes live project switching impossible, so the file tools are implemented
here. Every tool resolves relative paths against the active project root at
call time; absolute paths outside it are rejected unless
`security.allow_outside_project` is set. Switching project in the panel
takes effect on the next tool call - and on every open chat at once.

### Tool split

Files System: `list_directory`, `read_file`, `read_multiple_files`,
`write_file`, `edit_file`, `create_directory`, `move_file`, `delete_file`,
`search_files`, `grep`, `get_file_info`, `list_changes`, `undo_change`.

Terminal: `run_command`, `start_process`, `get_output`, `stop_process`,
`list_processes`, `get_active_project`, `list_skills`, `get_skill`.

Reads are paged (`offset`/`limit`) so a large file cannot flood the context.

### Undo history

Every write, edit, move and delete stores the previous bytes under
`.mcp-backups/` with a journal entry. `list_changes` shows recent ones and
`undo_change` restores one, refusing when the file changed afterwards.

### Commands and background jobs

A tool call is an HTTP request and the client stops waiting after about a
minute, so command execution is split in two:

- `run_command` waits for the result, but runs the process on a worker
  thread (`asyncio.to_thread`). Running it inline blocked the single event
  loop that serves both servers, so one slow command froze every other tool
  call and `/health` with it. Requested timeouts are clamped to
  `limits.command_timeout_max`, and a timeout stops the whole process tree
  rather than just the shell.

Stopping is always two-stage (`core.jobs.kill_tree`): Ctrl+Break to the
process group first, so pip, npm and git delete their partial downloads,
then a hard `taskkill /T /F` for whatever ignored it. The reply says which
of the two happened, so the agent knows whether the on-disk state may be
half-written. This is why every command runs in its own process group.
- `start_process` returns a job id immediately and streams output to a file
  under `.mcp-runs/`. `get_output` reads it in pages, `stop_process` kills
  the tree, `list_processes` lists what is alive. Jobs are killed when the
  servers stop, so nothing is orphaned.

### Startup and ports

Ports are probed before uvicorn binds them. A busy port produces one
readable log line naming it, instead of uvicorn's `sys.exit(1)` escaping
the worker thread as a page of traceback. The usual cause is an older copy
of the panel still running.

### Auth and tunnel

Every request needs `Authorization: Bearer <token>`; `/health` is the only
exception, so readiness can be checked without a secret. `cloudflared` runs
as a child process of the panel, using the user's own
`~/.cloudflared/config.yml`:

```yaml
tunnel: notion-sync
ingress:
  - hostname: mcp-files.wolroom.store
    service: http://localhost:9500
  - hostname: mcp-term.wolroom.store
    service: http://localhost:9501
  - service: http_status:404
```

Notion endpoints: `https://mcp-files.wolroom.store/mcp` and
`https://mcp-term.wolroom.store/mcp`.

### Readiness

`core/health.py` probes both local ports and both public hostnames and
reduces them to one state: `Ready in Notion`, `Running locally`,
`Starting...` or `Not running`. The panel shows it as a pill in the title
bar, next to the button that starts and stops the whole stack. Cloudflare
blocks a `Python-urllib` user agent with a 1010 error, so the probe sends a
browser-like one.

### GUI

PySide6 with a frameless custom title bar and a shadcn-like zinc palette.
Cards for servers, tunnel, projects, connection details and the live log,
plus a setup guide window that walks through connecting Notion and
installing the skill. `gui.autostart` brings the servers and the tunnel up
as soon as the panel opens.

## Tests

Plain scripts, run individually with `python tests\<name>.py`:
`smoke_test.py`, `backups_test.py`, `jobs_test.py`, `gui_controls_test.py`,
`probe_health.py`, `health_selftest.py`.

## Open items

- Session identification: log `Mcp-Session-Id` per call and compare two
  Notion chats. If chats are distinguishable, warn the agent when the
  active project changed mid-session.
- Windows Job Object for `cloudflared` so a hard-killed panel cannot orphan
  it.
- Agent memory across chats. Idea stage only.
