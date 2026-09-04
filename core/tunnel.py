"""Cloudflare Tunnel integration.

Replaces ngrok. The tunnel is a child process owned by this app: started
when the app starts, stopped when it exits. Routing lives in the
cloudflared config file, so adding a hostname never requires a code
change.

One-time setup (outside this app):

    cloudflared tunnel login
    cloudflared tunnel create notion-sync
    cloudflared tunnel route dns notion-sync mcp-files.wolroom.store
    cloudflared tunnel route dns notion-sync mcp-term.wolroom.store

Then point ingress at the local ports, keeping http_status:404 last.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from core import logs
from core.config import settings
from core.processes import ManagedProcess, registry

PROCESS_NAME = "tunnel"


def _config() -> dict:
    return settings.get("tunnel", default={}) or {}


def compute_hostnames(domain: str, user_slug: str = "") -> tuple[str, str]:
    """Compute (files_hostname, terminal_hostname) based on domain and optional user slug."""
    clean_domain = str(domain or "").strip().lower().lstrip(".").rstrip("/")
    if not clean_domain:
        clean_domain = "wolroom.store"
    clean_user = str(user_slug or "").strip().lower().strip("-.")
    if clean_user:
        return f"{clean_user}-files.{clean_domain}", f"{clean_user}-term.{clean_domain}"
    return f"mcp-files.{clean_domain}", f"mcp-term.{clean_domain}"


def is_configured() -> tuple:
    """Return (ok, reason). `ok` is False when the tunnel cannot start."""
    config = _config()
    binary = config.get("binary") or "cloudflared"
    if not shutil.which(binary) and not Path(binary).is_file():
        return False, f"'{binary}' was not found on PATH."
    if not config.get("tunnel_name"):
        return False, "No tunnel name is configured."
    config_file = config.get("config_file") or ""
    if config_file and not Path(config_file).is_file():
        return False, f"Tunnel config file not found: {config_file}"
    return True, ""


def build_command() -> list:
    """Assemble the cloudflared command line from the settings."""
    config = _config()
    command = [config.get("binary") or "cloudflared", "tunnel"]
    config_file = config.get("config_file") or ""
    if config_file:
        command += ["--config", config_file]
    command += ["run", config["tunnel_name"]]
    return command


def public_urls() -> dict:
    """Return the public MCP endpoint URLs, for the GUI and for the user."""
    config = _config()
    path = str(settings.get("servers", "http_path", default="/mcp"))
    urls = {}
    files_h = config.get("files_hostname")
    term_h = config.get("terminal_hostname")
    if not files_h and config.get("domain"):
        files_h, term_h = compute_hostnames(
            config.get("domain", ""), config.get("user_slug", "")
        )
    if files_h:
        urls["files"] = f"https://{files_h}{path}"
    if term_h:
        urls["terminal"] = f"https://{term_h}{path}"
    return urls


def sync_config_yaml(
    config_file: str | Path | None,
    files_hostname: str,
    terminal_hostname: str,
) -> tuple[bool, str]:
    """Update ingress rules in the cloudflared config.yml to match new hostnames.

    Preserves other services and the terminal 404 rule.
    Creates a backup copy with .bak extension before modifying.
    """
    if not config_file:
        return False, "No config file specified"
    path = Path(config_file)
    if not path.is_file():
        return False, f"Config file not found: {path}"

    try:
        content = path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            return False, "Config file does not contain a valid YAML dictionary"
    except Exception as exc:
        return False, f"Failed to read config YAML: {exc}"

    ingress = data.get("ingress")
    if not isinstance(ingress, list):
        ingress = []
        data["ingress"] = ingress

    files_port = int(settings.get("servers", "files_port", default=9500))
    term_port = int(settings.get("servers", "terminal_port", default=9501))

    files_matched = False
    term_matched = False

    for item in ingress:
        if not isinstance(item, dict):
            continue
        service = str(item.get("service", ""))
        if f":{files_port}" in service:
            item["hostname"] = files_hostname
            files_matched = True
        elif f":{term_port}" in service:
            item["hostname"] = terminal_hostname
            term_matched = True

    # If any were not found in existing ingress, insert before the catch-all
    insert_idx = len(ingress)
    for idx, item in enumerate(ingress):
        if isinstance(item, dict) and "http_status" in str(item.get("service", "")):
            insert_idx = idx
            break

    if not term_matched:
        ingress.insert(
            insert_idx,
            {
                "hostname": terminal_hostname,
                "service": f"http://localhost:{term_port}",
            },
        )
    if not files_matched:
        ingress.insert(
            insert_idx,
            {
                "hostname": files_hostname,
                "service": f"http://localhost:{files_port}",
            },
        )

    # Backup original before overwriting
    try:
        bak_path = path.with_suffix(".yml.bak")
        bak_path.write_text(content, encoding="utf-8")
    except OSError:
        pass

    try:
        new_yaml = yaml.safe_dump(data, sort_keys=False)
        path.write_text(new_yaml, encoding="utf-8")
        return True, "Config file synchronized successfully"
    except Exception as exc:
        return False, f"Failed to write updated YAML: {exc}"


def apply_settings(
    domain: str,
    user_slug: str = "",
    restart_tunnel_if_running: bool = True,
) -> tuple[bool, str]:
    """Save domain and user_slug, sync config.yml, and restart tunnel if running."""
    clean_domain = str(domain or "").strip().lower().lstrip(".").rstrip("/")
    clean_user = str(user_slug or "").strip().lower().strip("-.")
    files_h, term_h = compute_hostnames(clean_domain, clean_user)

    was_running = bool(status().get("running"))
    if was_running and restart_tunnel_if_running:
        logs.log(PROCESS_NAME, "Stopping tunnel to apply new configuration...")
        stop()

    def mutate(draft: dict) -> None:
        t = draft.setdefault("tunnel", {})
        t["domain"] = clean_domain
        t["user_slug"] = clean_user
        t["files_hostname"] = files_h
        t["terminal_hostname"] = term_h

    settings.update(mutate)

    config_file = _config().get("config_file")
    sync_ok, sync_msg = sync_config_yaml(config_file, files_h, term_h)
    if not sync_ok:
        logs.log(PROCESS_NAME, f"Config file sync warning: {sync_msg}", level="warn")

    if was_running and restart_tunnel_if_running:
        logs.log(PROCESS_NAME, "Starting tunnel with new hostnames...")
        start()

    return True, f"Hostnames updated: {files_h}, {term_h}"


def start() -> ManagedProcess | None:
    """Start the tunnel if it is enabled and properly configured."""
    if not _config().get("enabled"):
        logs.log(PROCESS_NAME, "Tunnel is disabled in settings; staying local.")
        return None

    ok, reason = is_configured()
    if not ok:
        logs.log(PROCESS_NAME, f"Not starting tunnel: {reason}", level="error")
        return None

    process = registry.register(ManagedProcess(PROCESS_NAME, build_command()))
    process.start()
    for label, url in public_urls().items():
        logs.log(PROCESS_NAME, f"{label} endpoint: {url}")
    return process


def stop() -> None:
    process = registry.get(PROCESS_NAME)
    if process is not None:
        process.stop()


def status() -> dict:
    process = registry.get(PROCESS_NAME)
    if process is None:
        return {"name": PROCESS_NAME, "running": False, "pid": None}
    return process.status()
