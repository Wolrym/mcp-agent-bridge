"""Headless entry point: run both MCP servers and the tunnel.

    python run_core.py                                  run everything
    python run_core.py --no-tunnel                       run without cloudflared
    python run_core.py --print-config                    show settings and exit
    python run_core.py --set-tunnel-config <path.yml>    point at your config
    python run_core.py --enable-tunnel                    turn the tunnel on
    python run_core.py --disable-tunnel                   turn the tunnel off

Settings changes should go through these flags (or the future GUI) rather
than hand-editing config\settings.json: a single JSON syntax mistake there
makes the whole file unreadable, which resets everything to defaults.

The GUI will later import `ServerSupervisor` and drive the exact same
lifecycle, so nothing here is throwaway scaffolding.
"""
from __future__ import annotations

import argparse
import asyncio
import socket
import sys
import threading
from pathlib import Path

import uvicorn

from core import jobs, logs, projects, tunnel
from core.config import SETTINGS_PATH, settings
from core.processes import registry
from servers import files_server, terminal_server


def port_conflict(host: str, port: int) -> str:
    """Return a readable reason if the port is taken, or an empty string.

    Checking first turns "only one usage of each socket address is normally
    permitted" plus a page of traceback into one sentence the user can act
    on. The usual cause is a previous copy of the panel that is still alive.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return (
                "Port " + str(port) + " is already in use, so this server did "
                "not start. Another copy of the panel is most likely still "
                "running - stop it (or free the port) and start again."
            )
    return ""


class ServerSupervisor:
    """Runs both MCP servers in a background asyncio loop.

    Kept separate from the CLI so the GUI can start and stop the same
    thing from a button without touching uvicorn directly.
    """

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._servers: list = []

    def _build_servers(self) -> list:
        host = str(settings.get("servers", "host", default="127.0.0.1"))
        specs = [
            (
                "files",
                files_server.build_app(),
                int(settings.get("servers", "files_port", default=9300)),
            ),
            (
                "terminal",
                terminal_server.build_app(),
                int(settings.get("servers", "terminal_port", default=9301)),
            ),
        ]
        built = []
        for name, app, port in specs:
            config = uvicorn.Config(
                app,
                host=host,
                port=port,
                log_level="warning",
                access_log=False,
            )
            built.append((name, uvicorn.Server(config), host, port))
        return built

    async def _run_one(self, name: str, server: uvicorn.Server) -> None:
        """Serve one app and turn any failure into a single log line.

        uvicorn calls sys.exit(1) when startup fails. Left alone, that
        SystemExit escapes this worker thread and prints a wall of
        traceback instead of telling the user what went wrong.
        """
        try:
            await server.serve()
        except SystemExit:
            logs.log(name, "Server stopped during startup.", level="error")
        except Exception as exc:  # noqa: BLE001
            logs.log(name, "Server stopped: " + str(exc), level="error")

    async def _serve(self) -> None:
        built = self._build_servers()
        usable = []
        for name, server, host, port in built:
            conflict = port_conflict(host, port)
            if conflict:
                logs.log(name, conflict, level="error")
                continue
            usable.append((name, server, host, port))

        if not usable:
            logs.log("core", "Nothing started: every port was busy.", level="error")
            return

        self._servers = [server for _, server, _, _ in usable]
        path = str(settings.get("servers", "http_path", default="/mcp"))
        for name, _, host, port in usable:
            logs.log(name, "Listening on http://" + host + ":" + str(port) + path)
        await asyncio.gather(
            *(self._run_one(name, server) for name, server, _, _ in usable)
        )

    def start(self) -> None:
        """Start both servers in a background thread."""
        if self.running:
            return

        def run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._serve())
            finally:
                loop.close()

        self._thread = threading.Thread(target=run, name="mcp-servers", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        """Ask both servers to shut down and wait for the thread to finish."""
        # Background jobs live in this process. Once the servers are gone
        # nobody can read or stop them any more, so they go first instead of
        # being orphaned.
        jobs.registry.stop_all()
        for server in self._servers:
            server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._servers = []
        self._thread = None

    def wait(self, interval: float = 0.5) -> None:
        """Block until the servers stop or the caller interrupts."""
        while self.running:
            assert self._thread is not None
            self._thread.join(timeout=interval)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


def _print_config() -> None:
    data = settings.all()
    servers = data["servers"]
    host, path = servers["host"], servers["http_path"]

    print("settings file : " + str(SETTINGS_PATH))
    print("auth token    : " + data["auth"]["token"])
    print("active project: " + str(data["active_project_id"]))
    for project in data["projects"]:
        print("  - " + project["id"] + ": " + project["root"])

    print("files (local) : http://" + host + ":" + str(servers["files_port"]) + path)
    print("term  (local) : http://" + host + ":" + str(servers["terminal_port"]) + path)

    t = data["tunnel"]
    print("tunnel enabled: " + str(t["enabled"]))
    print("tunnel config : " + (t["config_file"] or "(not set)"))
    print("tunnel domain : " + str(t.get("domain", "wolroom.store")))
    print("tunnel user   : " + str(t.get("user_slug") or "(none / default)"))
    for label, url in tunnel.public_urls().items():
        print(label.ljust(14) + ": " + url)


def _apply_cli_settings(args: argparse.Namespace) -> bool:
    """Handle settings-only flags. Returns True if any were handled."""
    handled = False

    if args.set_tunnel_config:
        path = Path(args.set_tunnel_config).expanduser().resolve()
        if not path.is_file():
            print("Error: file not found: " + str(path))
            sys.exit(1)
        settings.set("tunnel", "config_file", str(path))
        print("tunnel.config_file set to " + str(path))
        handled = True

    if args.files_hostname:
        settings.set("tunnel", "files_hostname", args.files_hostname)
        print("tunnel.files_hostname set to " + args.files_hostname)
        handled = True

    if args.terminal_hostname:
        settings.set("tunnel", "terminal_hostname", args.terminal_hostname)
        print("tunnel.terminal_hostname set to " + args.terminal_hostname)
        handled = True

    if args.enable_tunnel:
        settings.set("tunnel", "enabled", True)
        print("tunnel.enabled set to true")
        handled = True

    if args.disable_tunnel:
        settings.set("tunnel", "enabled", False)
        print("tunnel.enabled set to false")
        handled = True

    if args.domain or args.user_slug is not None:
        cfg = settings.get("tunnel", default={}) or {}
        domain = args.domain or cfg.get("domain", "wolroom.store")
        user_slug = args.user_slug if args.user_slug is not None else cfg.get("user_slug", "")
        tunnel.apply_settings(domain, user_slug, restart_tunnel_if_running=False)
        print(f"tunnel domain set to '{domain}', user prefix set to '{user_slug}'")
        handled = True

    if args.regenerate_token:
        token = settings.regenerate_token()
        print("new auth token: " + token)
        handled = True

    return handled


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the MCP workspace servers.")
    parser.add_argument(
        "--no-tunnel", action="store_true", help="Do not start cloudflared."
    )
    parser.add_argument(
        "--print-config", action="store_true", help="Show settings and exit."
    )
    parser.add_argument(
        "--domain", metavar="DOMAIN",
        help="Set tunnel base domain (e.g. wolroom.store).",
    )
    parser.add_argument(
        "--user-slug", metavar="NAME",
        help="Set user prefix for multi-user isolation (e.g. dima).",
    )
    parser.add_argument(
        "--set-tunnel-config", metavar="PATH",
        help="Set tunnel.config_file to this cloudflared config.yml path.",
    )
    parser.add_argument(
        "--files-hostname", metavar="HOST",
        help="Set tunnel.files_hostname (for reference/URLs only).",
    )
    parser.add_argument(
        "--terminal-hostname", metavar="HOST",
        help="Set tunnel.terminal_hostname (for reference/URLs only).",
    )
    parser.add_argument(
        "--enable-tunnel", action="store_true", help="Set tunnel.enabled to true."
    )
    parser.add_argument(
        "--disable-tunnel", action="store_true", help="Set tunnel.enabled to false."
    )
    parser.add_argument(
        "--regenerate-token", action="store_true",
        help="Generate a new auth token (breaks existing Notion connections).",
    )
    args = parser.parse_args(argv)

    if _apply_cli_settings(args):
        _print_config()
        return 0

    if args.print_config:
        _print_config()
        return 0

    logs.subscribe(
        lambda record: print(
            "[" + record["source"] + "] " + record["message"], flush=True
        )
    )

    try:
        project = projects.active_project()
        logs.log("core", "Active project: " + project["name"] + " (" + project["root"] + ")")
    except Exception as exc:  # noqa: BLE001
        logs.log("core", str(exc), level="warn")

    supervisor = ServerSupervisor()
    supervisor.start()

    if not args.no_tunnel:
        tunnel.start()

    logs.log("core", "Running. Press Ctrl+C to stop.")
    try:
        supervisor.wait()
    except KeyboardInterrupt:
        logs.log("core", "Shutting down")
    finally:
        supervisor.stop()
        registry.stop_all()
    return 0


if __name__ == "__main__":
    sys.exit(main())
