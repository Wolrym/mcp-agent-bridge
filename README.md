# MCP Agent Bridge

Two MCP servers that give an AI agent real hands on this Windows machine -
one for files, one for commands, background jobs and skills - with token
auth, live project switching, an undo history and an optional Cloudflare
Tunnel for remote clients. Pure Python, with a PySide6 control panel.

See `ARCHITECTURE.md` for the design and the reasoning behind it.

## Works with

Any MCP client that can reach a remote (streamable HTTP) server and send a
Bearer token - for example Notion AI custom connections, Claude Code,
Cursor or VS Code. A client on the same machine can use
`http://127.0.0.1:9500/mcp` and `http://127.0.0.1:9501/mcp` directly; the
tunnel is only needed for clients that run elsewhere.

## Quick start (Windows)

1. **Python 3.10+** from [python.org](https://www.python.org/downloads/)
   (tick "Add python.exe to PATH"), then in the project folder:
   ```cmd
   pip install -r requirements.txt
   ```
2. **cloudflared** (only for remote clients):
   `winget install Cloudflare.cloudflared`
3. Create the shortcuts once - nothing is built or installed:
   ```cmd
   python tools\make_shortcuts.py            :: add --desktop for desktop copies
   ```
   **MCP Agent Bridge** opens the panel without a console window (log in
   `logs\bridge.log`); **MCP Agent Bridge (debug)** keeps a console open
   with the live log and any traceback. Shortcuts hold absolute paths, so
   run the script again after moving or renaming the folder.
   `start_gui.bat` and `python -m gui.app` still work too.
4. On the **Tunnel** page set the base domain and your user prefix,
   point it at your cloudflared `config.yml`, then press **Start
   everything** at the top of the sidebar.
5. Open **Setup guide**: it has the endpoint URLs, the token, a config
   snippet and a ready-made "connect an MCP server" request to copy.

Headless:

```cmd
python run_core.py                 :: servers + tunnel
python run_core.py --no-tunnel     :: local only
python run_core.py --print-config  :: token, ports, projects, endpoints
```

Settings-only commands (safer than editing the JSON by hand):

```cmd
python run_core.py --set-tunnel-config "C:\Users\<you>\.cloudflared\config.yml"
python run_core.py --domain example.com --user-slug alex
python run_core.py --enable-tunnel
python run_core.py --disable-tunnel
python run_core.py --enable-backups
python run_core.py --regenerate-token
```

Only one instance can hold the ports: do not run `run_core.py` and the
control panel at the same time. A second panel refuses to start.

When sharing the folder, leave out `config/settings.json` (it holds your
token and is recreated on first launch), `logs/`, `.mcp-runs/`,
`.mcp-backups/` and `__pycache__/`.

## Tools

**Files System** (port 9500)

| Tool | What it does |
| --- | --- |
| `read_file` | Paged text read (`offset`/`limit`, long lines clipped); PNG/JPEG/GIF/WebP come back as images |
| `read_multiple_files` | Several files in one call, each paged |
| `write_file` | Create or replace; keeps the existing line endings and BOM |
| `edit_file` | Exact snippet replace (`replace_all`, `dry_run`); refuses non-UTF-8 files instead of corrupting them |
| `list_directory`, `get_file_info` | Listing (capped) and metadata |
| `search_files`, `grep` | Glob and regex search, skipping `.git`, `node_modules` and friends |
| `create_directory`, `move_file`, `delete_file` | The usual, with undo |
| `list_changes`, `undo_change` | Undo history (when backups are enabled) |
| `pack_files`, `unpack_files` | Base64 zip transfer to and from an agent's own sandbox - for images, PDFs, office files, whole folders |

**Terminal** (port 9501) - commands go through `cmd.exe`

| Tool | What it does |
| --- | --- |
| `run_command` | Runs a command and waits up to 45 s; if it is still running it stays alive in the background and the reply gives its job id |
| `start_process` | Starts a dev server, watcher or long build in the background |
| `wait_process` | Waits for a job and returns early when it ends or a line matches `until` (regex); `tail` for the last lines |
| `get_output`, `stop_process`, `list_processes` | Job output (paged or `tail`), stop the whole process tree, list jobs |
| `get_active_project` | The default folder, whether outside access is allowed, other projects |
| `list_skills`, `get_skill` | Global skills - the bridge's own (`skills/core/`) and those installed with `npx skills` (`skills/.agents/skills/`), grouped by folder or by `skills/categories.json` - plus project skills (`.agents/skills`, `.agent/skills`, `.claude/skills`, `.opencode/skills`) and the project's `AGENTS.md` / `CLAUDE.md` / `GEMINI.md`; `skills/bin/` is hidden. `tools/pack_skill.py` zips one, several or all skills |
| `notify_user` | Telegram "task finished" message, if configured |

Every result is sent once, as plain text. (FastMCP's default also sends a
structured copy, which doubles what the agent pays for each reply.)

## Projects and paths

The active project is the default for relative paths and for commands
without `cwd`. It is read on every call, so switching takes effect at
once - for every connected agent, because they all share this machine.
Agents should therefore use absolute paths. File tools refuse paths
outside the active project unless `security.allow_outside_project` is on.

## Security

- **The token is full control of this PC.** `run_command` runs anything
  the user can run, so the path checks of the file tools are a convenience,
  not a sandbox. Keep the token secret; regenerate it if it leaks.
- Every request needs `Authorization: Bearer <token>` (`X-API-Key` and
  `X-Auth-Token` also work). 20 wrong tokens from one address within five
  minutes block that address for 15 minutes (HTTP 429); behind the tunnel
  the real address comes from `CF-Connecting-IP`.
- `/health` needs no token and reveals only `{"status", "server"}`.
- An accident guard (`security.block_dangerous_commands`, on by default)
  refuses a short list of commands that wreck a machine (`format`,
  `diskpart`, `shutdown`, deleting a drive root, ...) or kill this app or
  its tunnel (`taskkill /im python.exe`, `cloudflared tunnel delete`, ...).
- Agents cannot overwrite `config/settings.json` through the file tools
  (`security.allow_settings_edit`).

## Settings

`config/settings.json` is created on first run. Prefer the panel or the
CLI flags: an invalid file is moved aside as `settings.broken.json` and
replaced with defaults. Useful keys:

| Key | Default | Meaning |
| --- | --- | --- |
| `limits.command_timeout` | 45 | How long `run_command` waits before backgrounding (never more than 50) |
| `limits.max_output_chars` | 100000 | Cap on one command output or file page |
| `limits.max_read_lines` | 900 | Default page size of `read_file` |
| `limits.max_image_bytes` | 5000000 | Largest image `read_file` returns |
| `limits.max_pack_mb` | 25 | Largest `pack_files` / `unpack_files` archive |
| `servers.session_idle_seconds` | 900 | Drop MCP sessions idle this long |
| `security.allow_outside_project` | false | Let file tools leave the active project |
| `security.block_dangerous_commands` | true | Accident guard |
| `backups.enabled` | false | Keep the undo history in `.mcp-backups/` |

## Logs

The panel's Activity page shows one line per tool call (tool, key
arguments, duration, error) plus server and tunnel events; long lines wrap
under their message. Calls shows only tool calls, Problems only warnings
and errors. Everything also goes to `logs/bridge.log` (rotated at about
1 MB), including cloudflared's start-up details, which the panel leaves
out. cloudflared lines that only mean a client hung up ("context
canceled", "stream ... canceled by remote with error code 0") are dropped.

## Cloudflare Tunnel

One-time setup, with your own tunnel name and hostnames:

```cmd
cloudflared tunnel login
cloudflared tunnel create mcp-agent-bridge
cloudflared tunnel route dns mcp-agent-bridge alex-files.example.com
cloudflared tunnel route dns mcp-agent-bridge alex-term.example.com
```

Ingress in the cloudflared config, keeping `http_status:404` last:

```yaml
tunnel: mcp-agent-bridge
credentials-file: C:\Users\<you>\.cloudflared\<tunnel-id>.json
ingress:
  - hostname: alex-files.example.com
    service: http://localhost:9500
  - hostname: alex-term.example.com
    service: http://localhost:9501
  - service: http_status:404
```

cloudflared runs as a child process of the panel: it starts with it and
stops when the panel exits. A wildcard CNAME (`*` -> your tunnel) lets
every teammate pick a prefix without touching DNS.

## Tests

Plain scripts, each safe to run while the real panel is live (throwaway
settings, ports 9400/9401 at most):

```cmd
python tests\tools_test.py     :: tool behaviour through FastMCP
python tests\smoke_test.py     :: both servers over HTTP: auth, tool lists, /health
python tests\jobs_test.py
python tests\backups_test.py
python tests\test_notifier.py
```
