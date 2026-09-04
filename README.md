# Notion MCP Workspace (remake)

Two MCP servers for coding from Notion on this Windows machine, with token
auth, live project switching and a Cloudflare Tunnel. Pure Python.

See `ARCHITECTURE.md` for the design and the reasoning behind it.

## Setup on a New Machine (Quickstart for Teammates)

### 1. Prerequisites (Windows)
1. **Python 3.10+**: Download from [python.org](https://www.python.org/downloads/) (make sure to check **"Add python.exe to PATH"**).
2. **Cloudflare Tunnel CLI (`cloudflared`)**:
   Open PowerShell and install via winget:
   ```powershell
   winget install Cloudflare.cloudflared
   ```
   *(Or download `cloudflared-windows-amd64.exe` from Cloudflare GitHub releases, rename to `cloudflared.exe`, and add to PATH).*

### 2. Install Project Dependencies
Open a terminal in the project folder:
```cmd
pip install -r requirements.txt
```
*(Optionally use a virtualenv: `python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt`)*

### 3. Sharing Project with Others (Clean Zip / Clone)
If sharing as a `.zip` archive, **exclude these machine-specific files**:
- `config/settings.json` (created automatically on first launch with clean defaults)
- `__pycache__/`
- `.mcp-runs/` and `.mcp-backups/`

### 4. Run the Control Panel
Double click `start_gui.bat` or run:
```cmd
python -m gui.app
```
On first start:
1. In the **Cloudflare tunnel** card, set your **Base domain** (e.g. `wolroom.store`) and your unique **User prefix** (e.g. `alex`).
2. Point cloudflared config to your tunnel credentials (`~/.cloudflared/config.yml`).
3. Click **Start everything** in the top bar.
4. Click **Notion setup guide** to copy endpoints and add skills directly into Notion.

Headless:

```
python run_core.py                # servers + tunnel
python run_core.py --no-tunnel    # local only
python run_core.py --print-config # token, ports, projects, endpoints
```

Settings-only commands (safer than editing the JSON by hand):

```
python run_core.py --set-tunnel-config "C:\Users\Dima\.cloudflared\config.yml"
python run_core.py --files-hostname mcp-files.wolroom.store
python run_core.py --terminal-hostname mcp-term.wolroom.store
python run_core.py --enable-tunnel
python run_core.py --disable-tunnel
python run_core.py --regenerate-token
```

Settings live in `config\settings.json`, created on first run from the
defaults. It holds the auth token, ports, tunnel setup, limits and the
project registry. If the file ever becomes invalid JSON, it is moved aside
as `settings.broken.json` and recreated from defaults - which is why hand
editing is discouraged.

Only one instance can hold the ports at a time: do not run `run_core.py`
and the control panel simultaneously.

## Control panel

`gui/` is a PySide6 app styled after shadcn/ui (zinc palette, flat cards,
subtle borders). It imports the same `ServerSupervisor` the CLI uses, so
both entry points behave identically.

- Servers card: status badge, start / stop / restart, local URLs with copy
- Tunnel card: status badge, start / stop, public URLs, config file picker
- Projects card: list, add folder, remove, set active
- Authentication card: reveal / copy / regenerate the token
- Activity card: live log from the servers and cloudflared
- "Notion setup guide" button: a separate modal with the whole onboarding -
  endpoint URLs, token, a ready-made "connect an MCP server" request, the
  full skill text with a copy button, daily-use habits and troubleshooting

## Test

```
python tests\smoke_test.py
```

Starts both servers on ports 9400 / 9401 with a throwaway settings file and
checks auth and the tool lists. Safe to run while anything else is live.

## Tools

**Files System** - `list_directory`, `read_file`, `read_multiple_files`,
`write_file`, `edit_file`, `create_directory`, `move_file`, `delete_file`,
`search_files`, `grep`, `get_file_info`

**Terminal** - `run_command`, `get_active_project`, `list_skills`,
`get_skill`

Paths may be absolute or relative to the active project. Relative is
preferred: it keeps working after the user switches projects.

## Projects

The active project decides where relative paths resolve and where commands
run. It is read on every tool call, so switching takes effect immediately
with no restart.

By default, paths outside the active project root are refused. Set
`security.allow_outside_project` to `true` to lift that.

## Auth

Every request needs the token from `config\settings.json`:

```
Authorization: Bearer <token>
```

`X-API-Key` and `X-Auth-Token` are accepted too, for clients that cannot
send an Authorization header. Requests without a valid token get 401 before
reaching any tool. Use header-based auth when adding the connection in
Notion.

The token is generated once and reused across restarts. It only changes if
you regenerate it, which invalidates the connections already added in
Notion.

## Ports

Defaults are 9500 (Files System) and 9501 (Terminal). The old gateway still
owns 9300 / 9301, so both stacks can run side by side; the cloudflared
ingress must point at whichever ports are configured here.

## Cloudflare Tunnel

One-time setup:

```
cloudflared tunnel login
cloudflared tunnel create notion-sync
cloudflared tunnel route dns notion-sync mcp-files.wolroom.store
cloudflared tunnel route dns notion-sync mcp-term.wolroom.store
```

Ingress in the cloudflared config, keeping `http_status:404` last:

```yaml
tunnel: notion-sync
credentials-file: C:\Users\Dima\.cloudflared\<tunnel-id>.json
ingress:
  - hostname: cmd.wolroom.store
    service: http://localhost:8734
  - hostname: mcp-files.wolroom.store
    service: http://localhost:9500
  - hostname: mcp-term.wolroom.store
    service: http://localhost:9501
  - service: http_status:404
```

`cmd.wolroom.store` stays as a fallback to the legacy command server.

cloudflared runs as a child process: it starts with the app and is
terminated when the app exits.

Notion endpoints:

- Files System: `https://mcp-files.wolroom.store/mcp`
- Terminal: `https://mcp-term.wolroom.store/mcp`

## Status

Done: settings store, project registry, path sandbox, logging, process
supervisor, both MCP servers, bearer auth, tunnel wiring, smoke test,
control panel with the Notion setup guide.

Next: session identification experiments, then agent memory across chats.
