"""Main control panel window.

The window is a thin shell over the core: it starts and stops the same
`ServerSupervisor` the CLI uses, switches the active project through
`core.projects`, and mirrors `core.logs` into a live view. No business
logic lives here, so the headless mode stays fully usable on its own.

The native Windows frame is replaced by our own title bar (see
`gui.widgets.chrome`), so the whole window follows the same dark theme.

Two status layers are deliberately kept apart:
  * the per-card badges say whether a process was started by us;
  * the pill in the title bar says whether the endpoints actually answer,
    which is the only thing that tells you Notion can reach the machine.

Button convention, kept narrow so nothing looks random:
  * default     - the one obvious action of a card
  * secondary   - every other action next to it
  * destructive - anything that throws work away
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core import backups, health, logs, projects, tunnel
from core.config import settings
from gui.widgets.chrome import install_frameless
from gui.widgets.primitives import (
    Badge,
    Card,
    CopyField,
    Switch,
    button,
    label,
    row,
    separator,
)
from gui.widgets.setup_guide import SetupGuideDialog
from run_core import ServerSupervisor

# How a readiness state is presented.
HEALTH_TONES = {
    health.READY: "success",
    health.LOCAL: "warning",
    health.STARTING: "warning",
    health.OFFLINE: "danger",
}


class _Bridge(QObject):
    """Moves callbacks from worker threads onto the Qt event loop."""

    log_arrived = Signal(dict)
    settings_changed = Signal(dict)
    health_checked = Signal(dict)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.resize(940, 860)
        self._chrome = install_frameless(self, "MCP Control Panel")

        self._supervisor = ServerSupervisor()
        self._bridge = _Bridge()
        self._bridge.log_arrived.connect(self._append_log)
        self._bridge.settings_changed.connect(lambda _s: self.refresh())
        self._bridge.health_checked.connect(self._apply_health)

        # Readiness probes are HTTP calls, so they run off the UI thread.
        self._probe_pool = ThreadPoolExecutor(max_workers=1)
        self._probe_busy = False
        self._health_state = ""

        self._build_ui()

        for record in logs.history(200):
            self._append_log(record)
        logs.subscribe(self._bridge.log_arrived.emit)
        settings.subscribe(self._bridge.settings_changed.emit)

        # Process and tunnel state has no change notification, so poll it.
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._refresh_status)
        self._poll.start(1500)

        self._health_poll = QTimer(self)
        self._health_poll.timeout.connect(self._check_health)
        self._health_poll.start(2500)

        self.refresh()
        self._check_health()

    # --- layout ----------------------------------------------------------

    def _build_ui(self) -> None:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 22, 16, 24)
        layout.setSpacing(16)

        layout.addWidget(self._header())
        layout.addWidget(self._servers_card())
        layout.addWidget(self._tunnel_card())
        layout.addWidget(self._projects_card())
        layout.addWidget(self._connection_card())
        layout.addWidget(self._logs_card(), 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        scroll.setWidget(content)
        # Without this the viewport fills itself from the palette and paints
        # a square over the shell's rounded bottom-left corner.
        scroll.viewport().setAutoFillBackground(False)
        content.setAutoFillBackground(False)

        # The title bar carries the two things worth seeing without
        # scrolling: the one button that runs the whole stack, and whether
        # Notion can actually reach it.
        self._master_button = button(
            "Start everything",
            "default",
            "Start or stop the servers and the tunnel together",
        )
        self._master_button.setObjectName("titleAction")
        self._master_button.clicked.connect(self._toggle_everything)
        self._chrome.title_bar.add_widget(self._master_button)

        self._health_pill = Badge("Checking...", "neutral")
        self._chrome.title_bar.add_widget(self._health_pill)

        # The shell paints the window border now that there is no native
        # one. The 1px margin keeps children from covering that border.
        self._shell = QWidget()
        self._shell.setObjectName("windowShell")
        self._shell.setFocusPolicy(Qt.StrongFocus)
        shell_layout = QVBoxLayout(self._shell)
        shell_layout.setContentsMargins(1, 1, 1, 1)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(self._chrome.title_bar)
        shell_layout.addWidget(scroll, 1)

        self.setCentralWidget(self._shell)

    def _header(self) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("MCP Control Panel", "title"))
        titles.addWidget(
            label(
                "Local coding servers for Notion, running on this machine.",
                "subtitle",
            )
        )
        layout.addLayout(titles, 1)

        guide_button = button("Notion setup guide", "secondary")
        guide_button.clicked.connect(self._open_guide)
        layout.addWidget(guide_button, 0, Qt.AlignTop)
        return container

    def _controls(self, *widgets: QWidget, align_right: bool = False) -> QWidget:
        """A horizontal strip of buttons."""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        if align_right:
            layout.addStretch(1)
        for widget in widgets:
            layout.addWidget(widget)
        if not align_right:
            layout.addStretch(1)
        return container

    def _servers_card(self) -> Card:
        card = Card(
            "Servers",
            "Files System and Terminal, served over streamable HTTP.",
        )
        self._servers_badge = Badge("Stopped", "danger")
        card.header_extra(self._servers_badge)

        self._files_local = CopyField("Files System (local)")
        self._terminal_local = CopyField("Terminal (local)")
        card.add(self._files_local)
        card.add(self._terminal_local)
        card.add(separator())

        self._reachability = label("Checking endpoints...", "muted")
        card.add(self._reachability)

        self._start_button = button("Start")
        self._start_button.clicked.connect(self._start_servers)
        self._stop_button = button("Stop", "secondary")
        self._stop_button.clicked.connect(self._stop_servers)
        self._restart_button = button("Restart", "secondary")
        self._restart_button.clicked.connect(self._restart_servers)

        card.add(
            self._controls(
                self._start_button, self._stop_button, self._restart_button
            )
        )
        card.add(separator())

        # Autostart covers the whole stack, the same as the title-bar button.
        self._autostart = Switch()
        self._autostart.toggled.connect(self._set_autostart)
        card.add(
            row(
                self._autostart,
                label(
                    "Start the servers and the tunnel as soon as the panel "
                    "opens",
                    "muted",
                ),
            )
        )
        return card

    def _tunnel_card(self) -> Card:
        card = Card(
            "Cloudflare tunnel",
            "Publishes both servers on your own domain.",
        )
        self._tunnel_badge = Badge("Stopped", "danger")
        card.header_extra(self._tunnel_badge)

        # Domain & user prefix
        cfg_row = QHBoxLayout()
        cfg_row.setContentsMargins(0, 0, 0, 0)
        cfg_row.setSpacing(8)

        domain_col = QVBoxLayout()
        domain_col.setContentsMargins(0, 0, 0, 0)
        domain_col.setSpacing(4)
        domain_col.addWidget(label("Base domain", "label"))
        self._domain_input = QLineEdit()
        self._domain_input.setPlaceholderText("e.g. wolroom.store")
        self._domain_input.textChanged.connect(self._on_tunnel_inputs_changed)
        domain_col.addWidget(self._domain_input)
        cfg_row.addLayout(domain_col, 3)

        user_col = QVBoxLayout()
        user_col.setContentsMargins(0, 0, 0, 0)
        user_col.setSpacing(4)
        user_col.addWidget(label("User prefix (optional)", "label"))
        self._user_slug_input = QLineEdit()
        self._user_slug_input.setPlaceholderText("e.g. dima")
        self._user_slug_input.textChanged.connect(self._on_tunnel_inputs_changed)
        user_col.addWidget(self._user_slug_input)
        cfg_row.addLayout(user_col, 2)

        btn_col = QVBoxLayout()
        btn_col.setContentsMargins(0, 0, 0, 0)
        btn_col.setSpacing(4)
        btn_col.addWidget(label(" ", "label"))
        self._apply_tunnel_btn = button("Apply", "default")
        self._apply_tunnel_btn.setEnabled(False)
        self._apply_tunnel_btn.clicked.connect(self._apply_tunnel_settings)
        btn_col.addWidget(self._apply_tunnel_btn)
        cfg_row.addLayout(btn_col, 0)

        card.add_layout(cfg_row)

        self._tunnel_preview = label("", "muted")
        card.add(self._tunnel_preview)
        card.add(separator())

        self._files_public = CopyField("Files System (public)")
        self._terminal_public = CopyField("Terminal (public)")
        card.add(self._files_public)
        card.add(self._terminal_public)
        card.add(separator())

        self._tunnel_config = CopyField("cloudflared config")
        card.add(self._tunnel_config)

        self._tunnel_start = button("Start tunnel")
        self._tunnel_start.clicked.connect(self._start_tunnel)
        self._tunnel_stop = button("Stop tunnel", "secondary")
        self._tunnel_stop.clicked.connect(self._stop_tunnel)
        pick_config = button("Choose config", "secondary")
        pick_config.clicked.connect(self._pick_tunnel_config)

        card.add(self._controls(self._tunnel_start, self._tunnel_stop, pick_config))
        card.add(
            label(
                "A freshly started tunnel needs a few seconds to register "
                "before the public URLs answer.",
                "muted",
            )
        )
        return card

    def _projects_card(self) -> Card:
        card = Card(
            "Projects",
            "The active project is the working directory every tool uses.",
        )
        self._project_badge = Badge("None", "neutral")
        card.header_extra(self._project_badge)

        self._project_list = QListWidget()
        self._project_list.setMinimumHeight(132)
        self._project_list.setFocusPolicy(Qt.ClickFocus)
        self._project_list.itemDoubleClicked.connect(
            lambda _item: self._activate_selected()
        )
        card.add(self._project_list)

        activate = button("Set active")
        activate.clicked.connect(self._activate_selected)
        add = button("Add folder", "secondary")
        add.clicked.connect(self._add_project)
        remove = button("Remove", "destructive")
        remove.clicked.connect(self._remove_selected)

        card.add(self._controls(activate, add, remove))
        card.add(
            label(
                "Switching projects applies immediately, including to chats "
                "that are already open.",
                "muted",
            )
        )
        card.add(separator())

        self._allow_outside = Switch()
        self._allow_outside.toggled.connect(self._set_allow_outside)
        card.add(
            row(
                self._allow_outside,
                label(
                    "Let tools read and write outside the active project "
                    "folder too",
                    "muted",
                ),
            )
        )
        card.add(
            label(
                "Off by default so a path mistake cannot touch the rest of "
                "the machine. Turning this on applies everywhere, not just "
                "to this one project.",
                "muted",
            )
        )
        card.add(separator())

        self._backups_switch = Switch()
        self._backups_switch.toggled.connect(self._set_backups_enabled)

        clean_backups_btn = button(
            "Clean .mcp-backups",
            "secondary",
            "Delete the .mcp-backups folder from the active project",
        )
        clean_backups_btn.clicked.connect(self._clean_active_project_backups)

        card.add(
            row(
                self._backups_switch,
                label(
                    "Create file backups (.mcp-backups) in project folders",
                    "muted",
                ),
                clean_backups_btn,
                spacing=10,
            )
        )
        card.add(
            label(
                "Keeps previous versions of edited and deleted files for undo_change. "
                "Turn off if you want clean project folders with zero background files.",
                "muted",
            )
        )
        return card

    def _connection_card(self) -> Card:
        card = Card(
            "Authentication",
            "Notion sends this token as a Bearer header on every request.",
        )
        self._token_field = CopyField("Auth token", secret=True)
        card.add(self._token_field)

        regenerate = button("Regenerate token", "destructive")
        regenerate.clicked.connect(self._regenerate_token)
        card.add(self._controls(regenerate))

        card.add(
            label(
                "The token survives restarts. Regenerating it invalidates the "
                "connections already added in Notion.",
                "muted",
            )
        )
        return card

    def _logs_card(self) -> Card:
        card = Card("Activity", "Live output from the servers and the tunnel.")
        self._log_view = QPlainTextEdit()
        self._log_view.setObjectName("logView")
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(2000)
        self._log_view.setMinimumHeight(190)
        self._log_view.setFocusPolicy(Qt.ClickFocus)
        card.add(self._log_view)

        clear = button("Clear", "secondary")
        clear.clicked.connect(self._clear_logs)
        card.add(self._controls(clear, align_right=True))
        return card

    # --- actions ---------------------------------------------------------

    def _start_servers(self) -> None:
        self._supervisor.start()
        QTimer.singleShot(400, self._refresh_status)
        QTimer.singleShot(600, self._check_health)

    def _stop_servers(self) -> None:
        self._supervisor.stop()
        self._refresh_status()
        self._check_health()

    def _restart_servers(self) -> None:
        self._supervisor.stop()
        self._supervisor.start()
        QTimer.singleShot(400, self._refresh_status)
        QTimer.singleShot(600, self._check_health)

    # --- the whole stack at once -----------------------------------------

    def _anything_running(self) -> bool:
        return self._supervisor.running or bool(tunnel.status().get("running"))

    def start_everything(self) -> None:
        """Start the servers and, when it is configured, the tunnel.

        A missing or misconfigured tunnel is not an error here: the servers
        still come up and stay usable locally, so this only says so in the
        log instead of interrupting with a dialog.
        """
        if not self._supervisor.running:
            self._supervisor.start()

        ok, reason = tunnel.is_configured()
        if ok:
            if not settings.get("tunnel", "enabled", default=False):
                settings.set("tunnel", "enabled", True)
            if not tunnel.status().get("running"):
                tunnel.start()
        else:
            logs.log("tunnel", "Staying local: " + reason, level="warn")

        QTimer.singleShot(400, self._refresh_status)
        QTimer.singleShot(600, self._check_health)

    def stop_everything(self) -> None:
        """Stop the tunnel first, then the servers it points at."""
        tunnel.stop()
        self._supervisor.stop()
        self._refresh_status()
        self._check_health()

    def _toggle_everything(self) -> None:
        if self._anything_running():
            self.stop_everything()
        else:
            self.start_everything()

    def _set_autostart(self, enabled: bool) -> None:
        settings.set("gui", "autostart", bool(enabled))
        logs.log(
            "gui",
            "Autostart " + ("enabled" if enabled else "disabled"),
        )

    def _set_allow_outside(self, enabled: bool) -> None:
        settings.set("security", "allow_outside_project", bool(enabled))
        logs.log(
            "gui",
            "Access outside the active project "
            + ("enabled" if enabled else "disabled"),
            level="warn" if enabled else "info",
        )

    def _set_backups_enabled(self, enabled: bool) -> None:
        settings.set("backups", "enabled", bool(enabled))
        logs.log(
            "gui",
            "File backups (.mcp-backups) "
            + ("enabled" if enabled else "disabled"),
            level="info",
        )

    def _clean_active_project_backups(self) -> None:
        try:
            active = projects.active_project()
        except Exception:
            active = None

        proj_name = active["name"] if active else "active project"
        confirm = QMessageBox.question(
            self,
            "Clean .mcp-backups?",
            f"Delete the .mcp-backups folder from '{proj_name}'?\n\n"
            "This will permanently remove all previous undo history and backups for this project.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if confirm != QMessageBox.Yes:
            return

        ok, msg = backups.delete_backups()
        logs.log("backups", msg, level="info" if ok else "warn")
        if ok:
            QMessageBox.information(self, "Cleaned", msg)
        else:
            QMessageBox.warning(self, "Error", msg)

    def _on_tunnel_inputs_changed(self) -> None:
        cfg = settings.get("tunnel", default={}) or {}
        curr_domain = str(cfg.get("domain", "wolroom.store")).strip().lower()
        curr_user = str(cfg.get("user_slug", "")).strip().lower()

        new_domain = self._domain_input.text().strip().lower().lstrip(".").rstrip("/")
        new_user = self._user_slug_input.text().strip().lower().strip("-.")

        changed = (new_domain != curr_domain) or (new_user != curr_user)
        self._apply_tunnel_btn.setEnabled(changed and bool(new_domain))

        if new_domain:
            files_h, term_h = tunnel.compute_hostnames(new_domain, new_user)
            self._tunnel_preview.setText(f"Preview: {files_h}  |  {term_h}")
        else:
            self._tunnel_preview.setText("Base domain cannot be empty.")

    def _apply_tunnel_settings(self) -> None:
        new_domain = self._domain_input.text().strip().lower().lstrip(".").rstrip("/")
        new_user = self._user_slug_input.text().strip().lower().strip("-.")
        if not new_domain:
            QMessageBox.warning(self, "Invalid Domain", "Base domain cannot be empty.")
            return

        is_running = bool(tunnel.status().get("running"))
        restart_now = False

        if is_running:
            confirm = QMessageBox.question(
                self,
                "Restart Tunnel?",
                "The Cloudflare tunnel is currently running.\n\n"
                "Applying a new domain or user prefix requires restarting the tunnel "
                "to update Cloudflare ingress routes. Existing Notion chats will need "
                "the updated URLs.\n\n"
                "Do you want to restart the tunnel now with the new settings?",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Yes,
            )
            if confirm != QMessageBox.Yes:
                return
            restart_now = True

        ok, msg = tunnel.apply_settings(
            new_domain, new_user, restart_tunnel_if_running=restart_now
        )
        if not ok:
            QMessageBox.warning(self, "Failed to Apply Settings", msg)
            return

        logs.log("tunnel", msg)
        self._apply_tunnel_btn.setEnabled(False)
        self.refresh()
        if restart_now:
            QTimer.singleShot(400, self._refresh_status)
            QTimer.singleShot(1000, self._check_health)

    def _start_tunnel(self) -> None:
        ok, reason = tunnel.is_configured()
        if not ok:
            QMessageBox.warning(self, "Tunnel not configured", reason)
            return
        # Starting from the panel implies the tunnel should be on.
        if not settings.get("tunnel", "enabled", default=False):
            settings.set("tunnel", "enabled", True)
        tunnel.start()
        QTimer.singleShot(400, self._refresh_status)

    def _stop_tunnel(self) -> None:
        tunnel.stop()
        self._refresh_status()
        self._check_health()

    def _pick_tunnel_config(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "Choose the cloudflared config file",
            "",
            "YAML files (*.yml *.yaml);;All files (*)",
        )
        if not path:
            return
        settings.set("tunnel", "config_file", path)
        logs.log("tunnel", "Config file set to " + path)
        self.refresh()

    def _add_project(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a project folder")
        if not folder:
            return
        try:
            project = projects.add_project(folder)
        except projects.ProjectError as exc:
            QMessageBox.warning(self, "Could not add project", str(exc))
            return
        self.refresh()
        self._offer_activation(project)

    def _offer_activation(self, project: dict) -> None:
        """Adding a folder usually means you want to work in it - but
        switching redirects every open chat, so only silently activate when
        there is nothing to redirect away from, and otherwise ask.
        """
        try:
            active = projects.active_project()
        except projects.ProjectError:
            active = None

        if active is not None and active["id"] == project["id"]:
            return
        if active is None:
            self._activate(project["id"])
            return

        confirm = QMessageBox.question(
            self,
            "Make it active?",
            "Added '" + project["name"] + "'.\n\nMake it the active project "
            "now? Every open Notion chat starts working in this folder "
            "immediately. '" + active["name"] + "' stays in the list either "
            "way.",
        )
        if confirm == QMessageBox.Yes:
            self._activate(project["id"])

    def _selected_project_id(self) -> str:
        item = self._project_list.currentItem()
        return item.data(Qt.UserRole) if item else ""

    def _activate(self, project_id: str) -> None:
        try:
            projects.set_active_project(project_id)
        except projects.ProjectError as exc:
            QMessageBox.warning(self, "Could not switch project", str(exc))
            return
        self.refresh()

    def _activate_selected(self) -> None:
        project_id = self._selected_project_id()
        if project_id:
            self._activate(project_id)

    def _remove_selected(self) -> None:
        project_id = self._selected_project_id()
        if not project_id:
            return
        confirm = QMessageBox.question(
            self,
            "Remove project",
            "Remove this project from the list? The folder itself stays on disk.",
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            projects.remove_project(project_id)
        except projects.ProjectError as exc:
            QMessageBox.warning(self, "Could not remove project", str(exc))
            return
        self.refresh()

    def _regenerate_token(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Regenerate token",
            "Every Notion connection using the current token will stop "
            "working until you re-add it. Continue?",
        )
        if confirm != QMessageBox.Yes:
            return
        settings.regenerate_token()
        logs.log("core", "Auth token regenerated")
        self.refresh()

    def _clear_logs(self) -> None:
        logs.clear()
        self._log_view.clear()

    def _open_guide(self) -> None:
        SetupGuideDialog(self).exec()

    # --- readiness -------------------------------------------------------

    def _check_health(self) -> None:
        """Probe the endpoints in the background, at most one probe at a time."""
        if self._probe_busy:
            return
        self._probe_busy = True

        def work() -> None:
            try:
                result = health.snapshot(timeout=1.5)
            except Exception as exc:  # noqa: BLE001 - never kill the worker
                result = {
                    "state": health.OFFLINE,
                    "label": "Check failed",
                    "local": {},
                    "public": {},
                    "error": str(exc),
                }
            self._bridge.health_checked.emit(result)

        self._probe_pool.submit(work)

    def _apply_health(self, result: dict) -> None:
        self._probe_busy = False
        state = str(result.get("state", health.OFFLINE))
        text = str(result.get("label", ""))
        detail = health.describe(result)

        self._health_pill.set_state(text, HEALTH_TONES.get(state, "neutral"))
        self._health_pill.setToolTip(detail or "No endpoint answered.")

        if state == health.READY:
            summary = "Notion can reach both servers through the tunnel."
        elif state == health.LOCAL:
            summary = "Both servers answer locally. Start the tunnel for Notion."
        elif state == health.STARTING:
            summary = "Some endpoints are still coming up: " + detail
        else:
            summary = "No endpoint is answering yet."
        self._reachability.setText(summary)

        # One log line per transition, so the activity view shows when the
        # stack actually became usable instead of only when it was started.
        if state != self._health_state:
            self._health_state = state
            logs.log("health", text + " - " + (detail or "no response"))

    # --- rendering -------------------------------------------------------

    def _append_log(self, record: dict) -> None:
        prefix = "[" + str(record.get("source", "")) + "] "
        self._log_view.appendPlainText(prefix + str(record.get("message", "")))

    def refresh(self) -> None:
        data = settings.all()
        servers = data["servers"]
        path = servers["http_path"]
        host = servers["host"]

        self._files_local.set_value(
            "http://" + host + ":" + str(servers["files_port"]) + path
        )
        self._terminal_local.set_value(
            "http://" + host + ":" + str(servers["terminal_port"]) + path
        )

        urls = tunnel.public_urls()
        self._files_public.set_value(urls.get("files", "") or "(hostname not set)")
        self._terminal_public.set_value(
            urls.get("terminal", "") or "(hostname not set)"
        )
        self._tunnel_config.set_value(data["tunnel"]["config_file"] or "(not set)")

        tunnel_cfg = data.get("tunnel", {}) or {}
        curr_domain = str(tunnel_cfg.get("domain") or "wolroom.store")
        curr_user = str(tunnel_cfg.get("user_slug") or "")

        input_domain = self._domain_input.text().strip().lower().lstrip(".").rstrip("/")
        input_user = self._user_slug_input.text().strip().lower().strip("-.")
        if input_domain == curr_domain and input_user == curr_user:
            self._apply_tunnel_btn.setEnabled(False)
        elif not self._apply_tunnel_btn.isEnabled():
            self._domain_input.blockSignals(True)
            self._user_slug_input.blockSignals(True)
            self._domain_input.setText(curr_domain)
            self._user_slug_input.setText(curr_user)
            self._domain_input.blockSignals(False)
            self._user_slug_input.blockSignals(False)

        files_h, term_h = tunnel.compute_hostnames(curr_domain, curr_user)
        self._tunnel_preview.setText(f"Active hostnames: {files_h}  |  {term_h}")

        self._token_field.set_value(data["auth"]["token"])

        # Signals are blocked while syncing: refresh() also runs as a
        # settings listener, and writing the value back would loop.
        autostart = bool(data.get("gui", {}).get("autostart", False))
        self._autostart.blockSignals(True)
        self._autostart.setChecked(autostart)
        self._autostart.blockSignals(False)

        allow_outside = bool(data.get("security", {}).get("allow_outside_project", False))
        self._allow_outside.blockSignals(True)
        self._allow_outside.setChecked(allow_outside)
        self._allow_outside.blockSignals(False)

        backups_enabled = bool(data.get("backups", {}).get("enabled", False))
        self._backups_switch.blockSignals(True)
        self._backups_switch.setChecked(backups_enabled)
        self._backups_switch.blockSignals(False)

        self._render_projects(data)
        self._refresh_status()

    def _render_projects(self, data: dict) -> None:
        active_id = data.get("active_project_id")
        selected = self._selected_project_id()

        self._project_list.clear()
        for project in data.get("projects", []):
            is_active = project["id"] == active_id
            marker = "\u2713 " if is_active else ""
            item = QListWidgetItem(marker + project["name"] + "\n" + project["root"])
            item.setData(Qt.UserRole, project["id"])
            self._project_list.addItem(item)
            if project["id"] == selected:
                self._project_list.setCurrentItem(item)

        try:
            active = projects.active_project()
            self._project_badge.set_state(active["name"], "success")
        except projects.ProjectError:
            self._project_badge.set_state("None", "danger")

    def _refresh_status(self) -> None:
        running = self._supervisor.running
        self._servers_badge.set_state(
            "Running" if running else "Stopped", "success" if running else "danger"
        )
        self._start_button.setEnabled(not running)
        self._stop_button.setEnabled(running)
        self._restart_button.setEnabled(running)

        status = tunnel.status()
        tunnel_running = bool(status.get("running"))
        self._tunnel_badge.set_state(
            "Running" if tunnel_running else "Stopped",
            "success" if tunnel_running else "danger",
        )
        self._tunnel_start.setEnabled(not tunnel_running)
        self._tunnel_stop.setEnabled(tunnel_running)

        self._sync_master(running or tunnel_running)

    def _sync_master(self, anything_running: bool) -> None:
        """The title-bar button flips between starting and stopping.

        Style follows meaning: starting is the primary action, stopping is
        a quiet one, so it never becomes the brightest thing on screen.
        """
        text = "Stop everything" if anything_running else "Start everything"
        variant = "secondary" if anything_running else "default"
        if self._master_button.text() != text:
            self._master_button.setText(text)
        if self._master_button.property("variant") != variant:
            self._master_button.setProperty("variant", variant)
            self._master_button.style().unpolish(self._master_button)
            self._master_button.style().polish(self._master_button)

    # --- lifecycle -------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        # Park the initial focus on the shell so no text field opens with a
        # blinking cursor in it.
        self._shell.setFocus(Qt.OtherFocusReason)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._poll.stop()
        self._health_poll.stop()
        self._probe_pool.shutdown(wait=False)
        self._supervisor.stop()
        tunnel.stop()
        super().closeEvent(event)
