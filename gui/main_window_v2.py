"""Redesigned control panel window (v2).

A modern, decluttered desktop interface inspired by Antigravity, ChatGPT,
and shadcn/zinc design.

Key improvements over v1:
- Clear visual hierarchy: Hero Status -> Active Workspace -> Endpoints -> Collapsible Sections.
- Collapsible cards for advanced/secondary features (Tunnel configuration, Live Logs).
- Generic AI agent terminology ("MCP Agent Bridge", "Ready for Agents", "Active Workspace").
- Quick "Open in Explorer" action for the active workspace.
- Complete feature parity with v1 without touching or modifying v1 files.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
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

from core import backups, health, logs, notifier, projects, tunnel
from core.config import settings
from gui.widgets.chrome import install_frameless
from gui.widgets.primitives import (
    Badge,
    Card,
    CollapsibleCard,
    CopyField,
    Switch,
    button,
    label,
    row,
    separator,
)
from gui.widgets.setup_guide_v2 import SetupGuideV2Dialog
from run_core import ServerSupervisor

HEALTH_TONES = {
    health.READY: "success",
    health.LOCAL: "warning",
    health.STARTING: "warning",
    health.OFFLINE: "danger",
}


class _Bridge(QObject):
    """Bridges worker thread events onto the Qt event loop."""

    log_arrived = Signal(dict)
    settings_changed = Signal(dict)
    health_checked = Signal(dict)


class MainWindowV2(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.resize(960, 880)
        self._chrome = install_frameless(self, "MCP Agent Bridge")

        self._supervisor = ServerSupervisor()
        self._bridge = _Bridge()
        self._bridge.log_arrived.connect(self._append_log)
        self._bridge.settings_changed.connect(lambda _s: self.refresh())
        self._bridge.health_checked.connect(self._apply_health)

        self._probe_pool = ThreadPoolExecutor(max_workers=1)
        self._probe_busy = False
        self._health_state = ""
        self._log_count = 0

        self._build_ui()

        for record in logs.history(200):
            self._append_log(record)
        logs.subscribe(self._bridge.log_arrived.emit)
        settings.subscribe(self._bridge.settings_changed.emit)

        self._poll = QTimer(self)
        self._poll.timeout.connect(self._refresh_status)
        self._poll.start(1500)

        self._health_poll = QTimer(self)
        self._health_poll.timeout.connect(self._check_health)
        self._health_poll.start(4000)

        self.refresh()
        self._check_health()

    # --- layout ----------------------------------------------------------

    def _build_ui(self) -> None:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 20, 20, 24)
        layout.setSpacing(14)

        layout.addWidget(self._header())
        layout.addWidget(self._hero_status_card())
        layout.addWidget(self._workspace_card())
        layout.addWidget(self._endpoints_card())
        layout.addWidget(self._tunnel_collapsible_card())
        layout.addWidget(self._notifications_collapsible_card())
        layout.addWidget(self._logs_collapsible_card(), 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        scroll.setWidget(content)
        scroll.viewport().setAutoFillBackground(False)
        content.setAutoFillBackground(False)

        # Chrome title bar quick items
        self._title_health = Badge("Checking...", "neutral")
        self._chrome.title_bar.add_widget(self._title_health)

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
        titles.addWidget(label("MCP Agent Bridge", "title"))
        titles.addWidget(
            label(
                "Local coding runtime & secure tools bridge for autonomous AI agents.",
                "subtitle",
            )
        )
        layout.addLayout(titles, 1)

        guide_button = button("Agent Setup Guide", "secondary")
        guide_button.clicked.connect(self._open_guide)
        layout.addWidget(guide_button, 0, Qt.AlignVCenter)
        return container

    def _hero_status_card(self) -> Card:
        """Unified hero card showing system readiness, master toggle, and quick actions."""
        card = Card(
            "System Control",
            "Manage local MCP servers and remote Cloudflare ingress together.",
        )

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(12)

        # Status pills group
        status_col = QVBoxLayout()
        status_col.setSpacing(6)

        pills_layout = QHBoxLayout()
        pills_layout.setSpacing(8)
        self._health_badge = Badge("Checking...", "neutral")
        self._servers_badge = Badge("Servers: Stopped", "danger")
        self._tunnel_badge = Badge("Tunnel: Stopped", "danger")

        pills_layout.addWidget(self._health_badge)
        pills_layout.addWidget(self._servers_badge)
        pills_layout.addWidget(self._tunnel_badge)
        pills_layout.addStretch(1)
        status_col.addLayout(pills_layout)

        self._reachability_lbl = label("Checking endpoints...", "muted")
        status_col.addWidget(self._reachability_lbl)
        top_row.addLayout(status_col, 1)

        # Master button
        btn_col = QVBoxLayout()
        btn_col.setSpacing(4)
        btn_col.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._master_button = button("Start All Services", "default")
        self._master_button.setMinimumWidth(160)
        self._master_button.setMinimumHeight(32)
        self._master_button.clicked.connect(self._toggle_everything)
        btn_col.addWidget(self._master_button)

        top_row.addLayout(btn_col, 0)
        card.add_layout(top_row)
        card.add(separator())

        # Sub-controls: individual server buttons + autostart
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(8)

        self._start_srv_btn = button("Start Servers", "secondary")
        self._start_srv_btn.clicked.connect(self._start_servers)
        self._stop_srv_btn = button("Stop", "secondary")
        self._stop_srv_btn.clicked.connect(self._stop_servers)
        self._restart_srv_btn = button("Restart", "secondary")
        self._restart_srv_btn.clicked.connect(self._restart_servers)

        bottom_row.addWidget(self._start_srv_btn)
        bottom_row.addWidget(self._stop_srv_btn)
        bottom_row.addWidget(self._restart_srv_btn)
        bottom_row.addSpacing(16)

        self._autostart = Switch()
        self._autostart.toggled.connect(self._set_autostart)
        bottom_row.addWidget(self._autostart)
        bottom_row.addWidget(label("Autostart all on app launch", "muted"))
        bottom_row.addStretch(1)

        card.add_layout(bottom_row)
        return card

    def _workspace_card(self) -> Card:
        """Card for managing active project folder, sandbox permissions, and backups."""
        card = Card(
            "Workspace & Active Project",
            "The active folder is the workspace directory where connected agents perform tasks.",
        )
        self._project_badge = Badge("No Active Project", "neutral")
        card.header_extra(self._project_badge)

        # Active project indicator with Open Folder button
        active_box = QWidget()
        active_box.setStyleSheet(
            "background-color: #141418; border: 1px solid #27272a; border-radius: 8px; padding: 6px 12px;"
        )
        active_layout = QHBoxLayout(active_box)
        active_layout.setContentsMargins(4, 2, 4, 2)
        active_layout.setSpacing(10)

        active_info = QVBoxLayout()
        active_info.setSpacing(2)
        self._active_proj_name = label("None", "cardTitle")
        self._active_proj_path = label("(No folder selected)", "mono")
        active_info.addWidget(self._active_proj_name)
        active_info.addWidget(self._active_proj_path)
        active_layout.addLayout(active_info, 1)

        self._open_folder_btn = button("Open Folder", "secondary")
        self._open_folder_btn.clicked.connect(self._open_active_in_explorer)
        active_layout.addWidget(self._open_folder_btn, 0, Qt.AlignVCenter)
        card.add(active_box)

        # Projects list
        self._project_list = QListWidget()
        self._project_list.setMinimumHeight(110)
        self._project_list.setMaximumHeight(160)
        self._project_list.setFocusPolicy(Qt.ClickFocus)
        self._project_list.itemDoubleClicked.connect(
            lambda _item: self._activate_selected()
        )
        card.add(self._project_list)

        # List actions
        btn_strip = QHBoxLayout()
        btn_strip.setContentsMargins(0, 0, 0, 0)
        btn_strip.setSpacing(8)

        activate_btn = button("Set as Active", "default")
        activate_btn.clicked.connect(self._activate_selected)
        add_btn = button("Add Folder", "secondary")
        add_btn.clicked.connect(self._add_project)
        remove_btn = button("Remove", "destructive")
        remove_btn.clicked.connect(self._remove_selected)

        btn_strip.addWidget(activate_btn)
        btn_strip.addWidget(add_btn)
        btn_strip.addWidget(remove_btn)
        btn_strip.addStretch(1)
        card.add_layout(btn_strip)
        card.add(separator())

        # Security & Safety options
        safety_layout = QVBoxLayout()
        safety_layout.setSpacing(8)

        # Boundary switch
        self._allow_outside = Switch()
        self._allow_outside.toggled.connect(self._set_allow_outside)
        safety_layout.addWidget(
            row(
                self._allow_outside,
                label("Allow workspace boundary escape (read & write outside active folder)", "muted"),
            )
        )

        # Backups switch & clean button
        self._backups_switch = Switch()
        self._backups_switch.toggled.connect(self._set_backups_enabled)

        clean_backups_btn = button(
            "Clean .mcp-backups",
            "secondary",
            "Permanently delete .mcp-backups from the active project",
        )
        clean_backups_btn.clicked.connect(self._clean_active_project_backups)

        safety_layout.addWidget(
            row(
                self._backups_switch,
                label("Create automated file backups (.mcp-backups) in projects", "muted"),
                clean_backups_btn,
                spacing=10,
            )
        )
        card.add_layout(safety_layout)
        return card

    def _endpoints_card(self) -> Card:
        """Card showing public & local endpoints and Bearer authentication."""
        card = Card(
            "Agent Connection Endpoints",
            "Live endpoints and authentication token for connecting AI agents.",
        )

        self._files_public = CopyField("Files System Endpoint (Public / Remote)")
        self._terminal_public = CopyField("Terminal Endpoint (Public / Remote)")
        card.add(self._files_public)
        card.add(self._terminal_public)
        card.add(separator())

        self._files_local = CopyField("Files System (Local LAN / Localhost)")
        self._terminal_local = CopyField("Terminal (Local LAN / Localhost)")
        card.add(self._files_local)
        card.add(self._terminal_local)
        card.add(separator())

        auth_row = QHBoxLayout()
        auth_row.setContentsMargins(0, 0, 0, 0)
        auth_row.setSpacing(10)

        self._token_field = CopyField("Agent Auth Token (Bearer)", secret=True)
        auth_row.addWidget(self._token_field, 1)

        regen_btn = button("Regenerate Token", "destructive")
        regen_btn.clicked.connect(self._regenerate_token)
        auth_row.addWidget(regen_btn, 0, Qt.AlignBottom)
        card.add_layout(auth_row)

        return card

    def _tunnel_collapsible_card(self) -> CollapsibleCard:
        """Collapsible drawer for Cloudflare tunnel configuration."""
        card = CollapsibleCard(
            "Cloudflare Tunnel & Domain Routing",
            "Configure base domain, user subdomains, and ingress tunnels.",
            collapsed=True,
        )
        self._tunnel_drawer_badge = Badge("Stopped", "danger")
        card.header_extra(self._tunnel_drawer_badge)

        cfg_row = QHBoxLayout()
        cfg_row.setContentsMargins(0, 0, 0, 0)
        cfg_row.setSpacing(8)

        domain_col = QVBoxLayout()
        domain_col.setContentsMargins(0, 0, 0, 0)
        domain_col.setSpacing(4)
        domain_col.addWidget(label("Base Domain", "label"))
        self._domain_input = QLineEdit()
        self._domain_input.setPlaceholderText("e.g. wolroom.store")
        self._domain_input.textChanged.connect(self._on_tunnel_inputs_changed)
        domain_col.addWidget(self._domain_input)
        cfg_row.addLayout(domain_col, 3)

        user_col = QVBoxLayout()
        user_col.setContentsMargins(0, 0, 0, 0)
        user_col.setSpacing(4)
        user_col.addWidget(label("User Prefix (optional)", "label"))
        self._user_slug_input = QLineEdit()
        self._user_slug_input.setPlaceholderText("e.g. dima")
        self._user_slug_input.textChanged.connect(self._on_tunnel_inputs_changed)
        user_col.addWidget(self._user_slug_input)
        cfg_row.addLayout(user_col, 2)

        btn_col = QVBoxLayout()
        btn_col.setContentsMargins(0, 0, 0, 0)
        btn_col.setSpacing(4)
        btn_col.addWidget(label(" ", "label"))
        self._apply_tunnel_btn = button("Apply Settings", "default")
        self._apply_tunnel_btn.setEnabled(False)
        self._apply_tunnel_btn.clicked.connect(self._apply_tunnel_settings)
        btn_col.addWidget(self._apply_tunnel_btn)
        cfg_row.addLayout(btn_col, 0)

        card.add_layout(cfg_row)

        self._tunnel_preview = label("", "muted")
        card.add(self._tunnel_preview)
        card.add(separator())

        self._tunnel_config = CopyField("cloudflared config path")
        card.add(self._tunnel_config)

        t_ctrls = QHBoxLayout()
        t_ctrls.setContentsMargins(0, 0, 0, 0)
        t_ctrls.setSpacing(8)

        self._tunnel_start = button("Start Tunnel", "secondary")
        self._tunnel_start.clicked.connect(self._start_tunnel)
        self._tunnel_stop = button("Stop Tunnel", "secondary")
        self._tunnel_stop.clicked.connect(self._stop_tunnel)
        pick_cfg = button("Choose Config File", "secondary")
        pick_cfg.clicked.connect(self._pick_tunnel_config)

        t_ctrls.addWidget(self._tunnel_start)
        t_ctrls.addWidget(self._tunnel_stop)
        t_ctrls.addWidget(pick_cfg)
        t_ctrls.addStretch(1)
        card.add_layout(t_ctrls)
        return card

    def _notifications_collapsible_card(self) -> CollapsibleCard:
        """Collapsible card for Telegram notification configuration."""
        card = CollapsibleCard(
            "Telegram Notifications",
            "Get alerted when an AI agent finishes its work or goes idle.",
            collapsed=True,
        )
        self._notify_badge = Badge("Disabled", "neutral")
        card.header_extra(self._notify_badge)

        self._notify_enabled = Switch()
        self._notify_enabled.toggled.connect(self._set_notifications_enabled)
        card.add(
            row(
                self._notify_enabled,
                label("Enable Telegram completion notifications", "muted"),
            )
        )
        card.add(separator())

        fields_row = QHBoxLayout()
        fields_row.setContentsMargins(0, 0, 0, 0)
        fields_row.setSpacing(8)

        token_col = QVBoxLayout()
        token_col.setContentsMargins(0, 0, 0, 0)
        token_col.setSpacing(4)
        token_col.addWidget(label("Bot Token", "label"))
        self._bot_token_input = QLineEdit()
        self._bot_token_input.setEchoMode(QLineEdit.Password)
        self._bot_token_input.setPlaceholderText("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
        self._bot_token_input.textChanged.connect(self._on_notification_fields_changed)
        token_col.addWidget(self._bot_token_input)
        fields_row.addLayout(token_col, 3)

        chat_col = QVBoxLayout()
        chat_col.setContentsMargins(0, 0, 0, 0)
        chat_col.setSpacing(4)
        chat_col.addWidget(label("Chat ID", "label"))
        self._chat_id_input = QLineEdit()
        self._chat_id_input.setPlaceholderText("e.g. 123456789 or @channel")
        self._chat_id_input.textChanged.connect(self._on_notification_fields_changed)
        chat_col.addWidget(self._chat_id_input)
        fields_row.addLayout(chat_col, 2)

        card.add_layout(fields_row)

        options_row = QHBoxLayout()
        options_row.setContentsMargins(0, 0, 0, 0)
        options_row.setSpacing(8)

        self._idle_switch = Switch()
        self._idle_switch.toggled.connect(self._set_notify_on_idle)
        options_row.addWidget(self._idle_switch)
        options_row.addWidget(label("Auto-notify after inactivity (seconds):", "muted"))

        self._idle_timeout_input = QLineEdit()
        self._idle_timeout_input.setFixedWidth(60)
        self._idle_timeout_input.setPlaceholderText("60")
        self._idle_timeout_input.textChanged.connect(self._on_notification_fields_changed)
        options_row.addWidget(self._idle_timeout_input)
        options_row.addStretch(1)

        card.add_layout(options_row)

        tool_row = QHBoxLayout()
        tool_row.setContentsMargins(0, 0, 0, 0)
        tool_row.setSpacing(8)

        self._notify_tool_switch = Switch()
        self._notify_tool_switch.toggled.connect(self._set_notify_tool_enabled)
        tool_row.addWidget(self._notify_tool_switch)
        tool_row.addWidget(label("Enable notify_user tool for agents to send custom notes", "muted"))
        tool_row.addStretch(1)

        card.add_layout(tool_row)
        card.add(separator())

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(8)

        self._save_notify_btn = button("Save Settings", "default")
        self._save_notify_btn.setEnabled(False)
        self._save_notify_btn.clicked.connect(self._save_notification_settings)

        self._test_notify_btn = button("Send Test Message", "secondary")
        self._test_notify_btn.clicked.connect(self._send_test_notification)

        btn_row.addWidget(self._save_notify_btn)
        btn_row.addWidget(self._test_notify_btn)
        btn_row.addStretch(1)

        card.add_layout(btn_row)
        return card

    def _logs_collapsible_card(self) -> CollapsibleCard:
        """Collapsible drawer for live server and tunnel logs."""
        card = CollapsibleCard(
            "Live Activity Logs",
            "Real-time event stream from servers, tunnel, and agents.",
            collapsed=True,
        )
        self._logs_badge = Badge("0 events", "neutral")
        card.header_extra(self._logs_badge)

        self._log_view = QPlainTextEdit()
        self._log_view.setObjectName("logView")
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(2000)
        self._log_view.setMinimumHeight(180)
        self._log_view.setFocusPolicy(Qt.ClickFocus)
        card.add(self._log_view)

        log_actions = QHBoxLayout()
        log_actions.setContentsMargins(0, 0, 0, 0)
        log_actions.setSpacing(8)

        copy_logs_btn = button("Copy All Logs", "secondary")
        copy_logs_btn.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(self._log_view.toPlainText())
        )
        clear_logs_btn = button("Clear", "secondary")
        clear_logs_btn.clicked.connect(self._clear_logs)

        log_actions.addStretch(1)
        log_actions.addWidget(copy_logs_btn)
        log_actions.addWidget(clear_logs_btn)
        card.add_layout(log_actions)
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

    def _anything_running(self) -> bool:
        return self._supervisor.running or bool(tunnel.status().get("running"))

    def start_everything(self) -> None:
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
        logs.log("gui", f"Autostart {'enabled' if enabled else 'disabled'}")

    def _set_allow_outside(self, enabled: bool) -> None:
        settings.set("security", "allow_outside_project", bool(enabled))
        logs.log(
            "gui",
            f"Access outside active project {'enabled' if enabled else 'disabled'}",
            level="warn" if enabled else "info",
        )

    def _set_backups_enabled(self, enabled: bool) -> None:
        settings.set("backups", "enabled", bool(enabled))
        logs.log(
            "gui",
            f"File backups (.mcp-backups) {'enabled' if enabled else 'disabled'}",
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
            f"Permanently delete .mcp-backups folder from '{proj_name}'?\n\n"
            "This removes all undo history and snapshots for this project.",
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

    def _set_notifications_enabled(self, enabled: bool) -> None:
        settings.set("notifications", "enabled", bool(enabled))
        logs.log("notify", f"Telegram notifications {'enabled' if enabled else 'disabled'}")
        self.refresh()

    def _set_notify_on_idle(self, enabled: bool) -> None:
        settings.set("notifications", "notify_on_idle", bool(enabled))
        logs.log("notify", f"Inactivity auto-notification {'enabled' if enabled else 'disabled'}")

    def _set_notify_tool_enabled(self, enabled: bool) -> None:
        settings.set("notifications", "notify_tool_enabled", bool(enabled))
        logs.log("notify", f"notify_user tool {'enabled' if enabled else 'disabled'}")

    def _on_notification_fields_changed(self) -> None:
        cfg = settings.get("notifications", default={}) or {}
        curr_token = str(cfg.get("bot_token") or "")
        curr_chat = str(cfg.get("chat_id") or "")
        curr_idle = str(cfg.get("idle_timeout_seconds") or 60)

        new_token = self._bot_token_input.text().strip()
        new_chat = self._chat_id_input.text().strip()
        new_idle = self._idle_timeout_input.text().strip()

        changed = (new_token != curr_token) or (new_chat != curr_chat) or (new_idle != curr_idle)
        self._save_notify_btn.setEnabled(changed)

    def _save_notification_settings(self) -> None:
        token = self._bot_token_input.text().strip()
        chat_id = self._chat_id_input.text().strip()
        raw_idle = self._idle_timeout_input.text().strip()
        try:
            idle_secs = max(5, int(raw_idle))
        except ValueError:
            idle_secs = 60
            self._idle_timeout_input.setText("60")

        settings.set("notifications", "bot_token", token)
        settings.set("notifications", "chat_id", chat_id)
        settings.set("notifications", "idle_timeout_seconds", idle_secs)
        logs.log("notify", "Notification settings saved")
        self._save_notify_btn.setEnabled(False)
        self.refresh()

    def _send_test_notification(self) -> None:
        token = self._bot_token_input.text().strip()
        chat_id = self._chat_id_input.text().strip()

        ok, msg = notifier.send_test_message(token=token, chat_id=chat_id)
        if ok:
            QMessageBox.information(self, "Success", "Telegram test message sent successfully!")
            logs.log("notify", "Telegram test message delivered successfully")
        else:
            QMessageBox.warning(self, "Failed to Send", f"Telegram API error: {msg}")
            logs.log("notify", f"Telegram test message failed: {msg}", level="warn")

    def _open_active_in_explorer(self) -> None:
        try:
            active = projects.active_project()
            if active and active.get("root"):
                os.startfile(active["root"])
        except Exception as exc:
            logs.log("gui", f"Could not open explorer: {exc}", level="warn")

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
                "Applying new domain routing requires restarting the tunnel.\n"
                "Connected agents will need the updated URLs.\n\n"
                "Restart now?",
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
            QMessageBox.warning(self, "Tunnel Not Configured", reason)
            return
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
            "Choose cloudflared config file",
            "",
            "YAML files (*.yml *.yaml);;All files (*)",
        )
        if not path:
            return
        settings.set("tunnel", "config_file", path)
        logs.log("tunnel", f"Config file set to {path}")
        self.refresh()

    def _add_project(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Project Folder")
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
            "Activate Workspace?",
            f"Added '{project['name']}'.\n\n"
            "Make this the active workspace now? Connected AI agents "
            "will begin targeting this folder immediately.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
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
        pid = self._selected_project_id()
        if pid:
            self._activate(pid)

    def _remove_selected(self) -> None:
        pid = self._selected_project_id()
        if not pid:
            return
        confirm = QMessageBox.question(
            self,
            "Remove Project",
            "Remove this project from the workspace list? The files on disk stay untouched.",
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            projects.remove_project(pid)
        except projects.ProjectError as exc:
            QMessageBox.warning(self, "Could not remove project", str(exc))
            return
        self.refresh()

    def _regenerate_token(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Regenerate Token?",
            "Every agent connection currently using this token will stop working "
            "until you update the token in your agent config. Continue?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if confirm != QMessageBox.Yes:
            return
        settings.regenerate_token()
        logs.log("core", "Agent auth token regenerated")
        self.refresh()

    def _clear_logs(self) -> None:
        logs.clear()
        self._log_view.clear()
        self._log_count = 0
        self._logs_badge.set_state("0 events", "neutral")

    def _open_guide(self) -> None:
        SetupGuideV2Dialog(self).exec()

    # --- readiness & health -----------------------------------------------

    def _check_health(self) -> None:
        if self._probe_busy:
            return
        self._probe_busy = True

        def work() -> None:
            try:
                result = health.snapshot(timeout=3.5)
            except Exception as exc:
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
        detail = health.describe(result)

        if state == health.READY:
            text = "Ready for Agents"
            summary = "All systems operational. External agents can connect via Cloudflare Tunnel."
        elif state == health.LOCAL:
            text = "Local Only"
            summary = "Servers answering locally. Start Cloudflare tunnel for remote agents."
        elif state == health.STARTING:
            text = "Starting..."
            summary = f"Endpoints initializing: {detail}"
        else:
            text = "Offline"
            summary = "No endpoints answering yet. Press 'Start All Services' to begin."

        tone = HEALTH_TONES.get(state, "neutral")
        self._health_badge.set_state(text, tone)
        self._title_health.set_state(text, tone)
        self._title_health.setToolTip(detail or "No endpoint answered.")
        self._reachability_lbl.setText(summary)

        if state != self._health_state:
            self._health_state = state
            logs.log("health", f"{text} - {detail or 'no response'}")

    # --- rendering & sync ------------------------------------------------

    def _append_log(self, record: dict) -> None:
        prefix = "[" + str(record.get("source", "")) + "] "
        self._log_view.appendPlainText(prefix + str(record.get("message", "")))
        self._log_count += 1
        self._logs_badge.set_state(f"{self._log_count} events", "neutral")

    def refresh(self) -> None:
        data = settings.all()
        servers = data.get("servers", {})
        path = servers.get("http_path", "/sse")
        host = servers.get("host", "127.0.0.1")

        self._files_local.set_value(f"http://{host}:{servers.get('files_port', 9500)}{path}")
        self._terminal_local.set_value(f"http://{host}:{servers.get('terminal_port', 9501)}{path}")

        urls = tunnel.public_urls()
        self._files_public.set_value(urls.get("files", "") or "(tunnel stopped or hostname not set)")
        self._terminal_public.set_value(urls.get("terminal", "") or "(tunnel stopped or hostname not set)")
        self._tunnel_config.set_value(data.get("tunnel", {}).get("config_file") or "(not set)")

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

        self._token_field.set_value(data.get("auth", {}).get("token", ""))

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

        # Sync notifications
        notify_cfg = data.get("notifications", {}) or {}
        notify_enabled = bool(notify_cfg.get("enabled", False))
        self._notify_enabled.blockSignals(True)
        self._notify_enabled.setChecked(notify_enabled)
        self._notify_enabled.blockSignals(False)

        is_cfg = notifier.is_configured()
        if notify_enabled and is_cfg:
            self._notify_badge.set_state("Active", "success")
        elif notify_enabled:
            self._notify_badge.set_state("No Credentials", "warning")
        else:
            self._notify_badge.set_state("Disabled", "neutral")

        resolved_token, resolved_chat = notifier.get_credentials()
        raw_token = str(notify_cfg.get("bot_token") or "")
        raw_chat = str(notify_cfg.get("chat_id") or "")
        raw_idle = str(notify_cfg.get("idle_timeout_seconds") or 60)

        if not self._save_notify_btn.isEnabled():
            self._bot_token_input.blockSignals(True)
            self._chat_id_input.blockSignals(True)
            self._idle_timeout_input.blockSignals(True)
            self._bot_token_input.setText(raw_token or (resolved_token if resolved_token else ""))
            self._chat_id_input.setText(raw_chat or (resolved_chat if resolved_chat else ""))
            self._idle_timeout_input.setText(raw_idle)
            self._bot_token_input.blockSignals(False)
            self._chat_id_input.blockSignals(False)
            self._idle_timeout_input.blockSignals(False)

        idle_enabled = bool(notify_cfg.get("notify_on_idle", True))
        self._idle_switch.blockSignals(True)
        self._idle_switch.setChecked(idle_enabled)
        self._idle_switch.blockSignals(False)

        tool_enabled = bool(notify_cfg.get("notify_tool_enabled", True))
        self._notify_tool_switch.blockSignals(True)
        self._notify_tool_switch.setChecked(tool_enabled)
        self._notify_tool_switch.blockSignals(False)

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
            self._active_proj_name.setText(active["name"])
            self._active_proj_path.setText(active["root"])
            self._open_folder_btn.setEnabled(True)
        except projects.ProjectError:
            self._project_badge.set_state("No Active Project", "danger")
            self._active_proj_name.setText("None")
            self._active_proj_path.setText("(Select or add a folder below)")
            self._open_folder_btn.setEnabled(False)

    def _refresh_status(self) -> None:
        running = self._supervisor.running
        self._servers_badge.set_state(
            "Servers: Running" if running else "Servers: Stopped",
            "success" if running else "danger",
        )
        self._start_srv_btn.setEnabled(not running)
        self._stop_srv_btn.setEnabled(running)
        self._restart_srv_btn.setEnabled(running)

        status = tunnel.status()
        tunnel_running = bool(status.get("running"))
        self._tunnel_badge.set_state(
            "Tunnel: Running" if tunnel_running else "Tunnel: Stopped",
            "success" if tunnel_running else "danger",
        )
        self._tunnel_drawer_badge.set_state(
            "Running" if tunnel_running else "Stopped",
            "success" if tunnel_running else "danger",
        )
        self._tunnel_start.setEnabled(not tunnel_running)
        self._tunnel_stop.setEnabled(tunnel_running)

        anything = running or tunnel_running
        self._master_button.setText("Stop All Services" if anything else "Start All Services")
        self._master_button.setProperty("variant", "secondary" if anything else "default")
        self._master_button.style().unpolish(self._master_button)
        self._master_button.style().polish(self._master_button)

    # --- lifecycle -------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._shell.setFocus(Qt.OtherFocusReason)

    def closeEvent(self, event) -> None:
        self._poll.stop()
        self._health_poll.stop()
        self._probe_pool.shutdown(wait=False)
        self._supervisor.stop()
        tunnel.stop()
        super().closeEvent(event)
