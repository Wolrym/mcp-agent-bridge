"""Main control panel window.

The window is a thin shell over the core: it starts and stops the same
`ServerSupervisor` the CLI uses, switches the active project through
`core.projects`, and mirrors `core.logs` into a live view. No business
logic lives here, so the headless mode stays fully usable on its own.

Layout: our own title bar (see `gui.widgets.chrome`) over a sidebar and a
content panel. The sidebar holds the one action that runs the whole
stack, the pages, and the active project - the three things you reach for
most. Each page is a column of groups in the style of a settings screen.

Two status layers are deliberately kept apart:
  * the badges on the pages say whether a process was started by us;
  * the pill in the title bar says whether the endpoints actually answer,
    which is the only thing that tells you a client can reach the machine.

Button convention, kept narrow so nothing looks random:
  * default     - the one obvious action on screen (light)
  * secondary   - every other action
  * destructive - anything that throws work away
  * ghost       - quiet extras
"""
from __future__ import annotations

import html
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core import backups, health, logs, notifier, projects, tunnel
from core.config import settings
from gui.widgets.chrome import install_frameless
from gui.widgets.primitives import (
    Backdrop,
    Badge,
    CopyRow,
    ElidedLabel,
    GlyphButton,
    Group,
    NavButton,
    Page,
    Segmented,
    SettingRow,
    Switch,
    button,
    label,
    repolish,
)
from gui.widgets.setup_guide import SetupGuideDialog
from gui.widgets.tokens import COLORS
from run_core import ServerSupervisor

APP_TITLE = "MCP Agent Bridge"
SIDEBAR_WIDTH = 228

# How a readiness state is presented.
HEALTH_TONES = {
    health.READY: "success",
    health.LOCAL: "warning",
    health.STARTING: "warning",
    health.OFFLINE: "danger",
}

# Sidebar pages: key, label, icon.
PAGES = (
    ("overview", "Overview", "overview"),
    ("projects", "Projects", "projects"),
    ("tunnel", "Tunnel", "tunnel"),
    ("security", "Security", "security"),
    ("notifications", "Notifications", "notifications"),
    ("activity", "Activity", "activity"),
)

LOG_FILTERS = (("all", "All"), ("calls", "Calls"), ("problems", "Problems"))


class _Bridge(QObject):
    """Moves callbacks from worker threads onto the Qt event loop."""

    log_arrived = Signal(dict)
    settings_changed = Signal(dict)
    health_checked = Signal(dict)


class _ProjectChip(QFrame):
    """The active project at the bottom of the sidebar; click to manage."""

    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("projectChip")
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 10)
        layout.setSpacing(1)
        self.name = ElidedLabel("", "chipName", Qt.ElideRight)
        self.name.setTextInteractionFlags(Qt.NoTextInteraction)
        self.path = ElidedLabel("", "chipPath", Qt.ElideMiddle)
        self.path.setTextInteractionFlags(Qt.NoTextInteraction)
        layout.addWidget(self.name)
        layout.addWidget(self.path)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


def _input(placeholder: str, width: int = 260) -> QLineEdit:
    field = QLineEdit()
    field.setPlaceholderText(placeholder)
    field.setFixedWidth(width)
    return field


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.resize(1120, 780)
        self.setMinimumSize(820, 560)
        self._chrome = install_frameless(self, APP_TITLE)

        self._supervisor = ServerSupervisor()
        self._bridge = _Bridge()
        self._bridge.log_arrived.connect(self._append_log)
        self._bridge.settings_changed.connect(lambda _s: self.refresh())
        self._bridge.health_checked.connect(self._apply_health)

        # Readiness probes are HTTP calls, so they run off the UI thread.
        self._probe_pool = ThreadPoolExecutor(max_workers=1)
        self._probe_busy = False
        self._health_state = ""

        self._records: deque = deque(maxlen=2000)
        self._log_filter = "all"
        # The overview shows public URLs when there are any, until the user
        # picks a side himself.
        self._endpoint_mode_touched = False

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
        self._health_poll.start(4000)

        self.refresh()
        self._check_health()

    # --- layout ----------------------------------------------------------

    def _build_ui(self) -> None:
        # Whether a client can reach the machine, visible from every page.
        self._health_pill = Badge("Checking...", "neutral")
        self._chrome.title_bar.add_widget(self._health_pill)

        self._pages = QStackedWidget()
        self._page_index: dict = {}
        for key, builder in (
            ("overview", self._overview_page),
            ("projects", self._projects_page),
            ("tunnel", self._tunnel_page),
            ("security", self._security_page),
            ("notifications", self._notifications_page),
            ("activity", self._activity_page),
        ):
            self._page_index[key] = self._pages.addWidget(builder())

        backdrop = Backdrop()
        backdrop_layout = QVBoxLayout(backdrop)
        backdrop_layout.setContentsMargins(1, 1, 1, 1)
        backdrop_layout.addWidget(self._pages)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 8, 8)
        body.setSpacing(0)
        body.addWidget(self._sidebar())
        body.addWidget(backdrop, 1)

        # The shell paints the window border now that there is no native
        # one. The 1px margin keeps children from covering that border.
        self._shell = QWidget()
        self._shell.setObjectName("windowShell")
        self._shell.setFocusPolicy(Qt.StrongFocus)
        shell_layout = QVBoxLayout(self._shell)
        shell_layout.setContentsMargins(1, 1, 1, 1)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(self._chrome.title_bar)
        shell_layout.addLayout(body, 1)
        self.setCentralWidget(self._shell)

        for number, (key, _text, _icon) in enumerate(PAGES, start=1):
            shortcut = QShortcut(QKeySequence("Ctrl+" + str(number)), self)
            shortcut.activated.connect(lambda k=key: self.show_page(k))
        self.show_page("overview")

    def _sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(SIDEBAR_WIDTH)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 6, 10, 10)
        layout.setSpacing(2)

        # The one button that runs the whole stack. Light while there is
        # something to start, quiet once it runs.
        self._master_button = GlyphButton(
            "Start everything", "play", "default",
            "Start or stop the servers and the tunnel together",
        )
        self._master_button.setObjectName("masterAction")
        self._master_button.clicked.connect(self._toggle_everything)
        layout.addWidget(self._master_button)
        layout.addSpacing(14)

        self._nav = QButtonGroup(self)
        self._nav.setExclusive(True)
        self._nav_buttons: dict = {}
        for key, text, icon in PAGES:
            item = NavButton(text, icon)
            item.clicked.connect(lambda _checked=False, k=key: self.show_page(k))
            self._nav.addButton(item)
            self._nav_buttons[key] = item
            layout.addWidget(item)

        layout.addStretch(1)

        layout.addWidget(label("Active project", "sidebarCaption"))
        layout.addSpacing(4)
        self._project_chip = _ProjectChip()
        self._project_chip.clicked.connect(lambda: self.show_page("projects"))
        layout.addWidget(self._project_chip)
        layout.addSpacing(8)

        guide = NavButton("Setup guide", "guide")
        guide.setCheckable(False)
        guide.clicked.connect(self._open_guide)
        layout.addWidget(guide)
        return sidebar

    def show_page(self, key: str) -> None:
        index = self._page_index.get(key)
        if index is None:
            return
        self._pages.setCurrentIndex(index)
        self._nav_buttons[key].setChecked(True)

    def current_page(self) -> str:
        index = self._pages.currentIndex()
        for key, value in self._page_index.items():
            if value == index:
                return key
        return ""

    # --- pages -----------------------------------------------------------

    def _overview_page(self) -> Page:
        page = Page("Overview", "MCP servers for AI agents, running on this machine.")

        services = Group("Services")
        self._servers_row = SettingRow("Servers", "Files System and Terminal")
        self._servers_badge = Badge("Stopped", "danger")
        self._restart_button = button("Restart", "secondary")
        self._restart_button.clicked.connect(self._restart_servers)
        self._servers_toggle = button("Start", "secondary")
        self._servers_toggle.clicked.connect(self._toggle_servers)
        self._servers_row.add(self._servers_badge)
        self._servers_row.add(self._restart_button)
        self._servers_row.add(self._servers_toggle)
        services.add_row(self._servers_row)

        self._tunnel_row = SettingRow("Cloudflare tunnel", "")
        self._tunnel_badge = Badge("Stopped", "danger")
        self._tunnel_toggle = button("Start", "secondary")
        self._tunnel_toggle.clicked.connect(self._toggle_tunnel)
        self._tunnel_row.add(self._tunnel_badge)
        self._tunnel_row.add(self._tunnel_toggle)
        services.add_row(self._tunnel_row)

        # Autostart covers the whole stack, the same as the sidebar button.
        autostart_row = SettingRow(
            "Start with the panel",
            "Bring up the servers and the tunnel as soon as the panel opens.",
        )
        self._autostart = Switch()
        self._autostart.toggled.connect(self._set_autostart)
        autostart_row.add(self._autostart)
        services.add_row(autostart_row)
        self._reachability = services._caption
        services.set_caption("Checking endpoints...")
        page.add(services)

        connect = Group("Connect a client")
        self._endpoint_mode = Segmented([("public", "Public"), ("local", "Local")])
        self._endpoint_mode.changed.connect(self._on_endpoint_mode)
        connect.header_extra(self._endpoint_mode)
        self._files_endpoint = CopyRow("Files System")
        self._terminal_endpoint = CopyRow("Terminal")
        self._token_overview = CopyRow("Auth token", secret=True)
        connect.add_row(self._files_endpoint)
        connect.add_row(self._terminal_endpoint)
        connect.add_row(self._token_overview)
        connect.set_caption(
            "Add both servers to your MCP client: two connections, one Bearer "
            "token. The setup guide has a ready-made config snippet."
        )
        page.add(connect)

        project = Group("Active project")
        self._active_row = SettingRow("None", "", mono=True)
        open_folder = button("Open folder", "secondary")
        open_folder.clicked.connect(self._open_active_folder)
        change = button("Change", "secondary")
        change.clicked.connect(lambda: self.show_page("projects"))
        self._active_row.add(open_folder)
        self._active_row.add(change)
        project.add_row(self._active_row)
        page.add(project)

        page.finish()
        return page

    def _projects_page(self) -> Page:
        page = Page(
            "Projects",
            "The active project is the default working folder of every tool.",
        )
        add = GlyphButton("Add folder", "plus", "secondary")
        add.clicked.connect(self._add_project)
        page.header_extra(add)

        self._projects_group = Group(
            "Folders",
            "Switching applies immediately, including to chats that are "
            "already open.",
        )
        page.add(self._projects_group)

        files = Group("Files")
        backups_row = SettingRow(
            "File backups",
            "Keep previous versions of edited and deleted files in "
            ".mcp-backups, so undo_change can restore them. Turn off for "
            "project folders without background files.",
        )
        clean = button("Clean", "ghost", "Delete the .mcp-backups folder of the active project")
        clean.clicked.connect(self._clean_active_project_backups)
        self._backups_switch = Switch()
        self._backups_switch.toggled.connect(self._set_backups_enabled)
        backups_row.add(clean)
        backups_row.add(self._backups_switch)
        files.add_row(backups_row)
        page.add(files)

        page.finish()
        return page

    def _tunnel_page(self) -> Page:
        page = Page("Tunnel", "Cloudflare Tunnel publishes both servers on your own domain.")
        self._tunnel_page_badge = page.header_extra(Badge("Stopped", "danger"))
        self._tunnel_page_toggle = page.header_extra(button("Start tunnel", "secondary"))
        self._tunnel_page_toggle.clicked.connect(self._toggle_tunnel)

        domain = Group("Domain")
        domain_row = SettingRow("Base domain", "The zone the hostnames live in.")
        self._domain_input = _input("e.g. example.com")
        self._domain_input.textChanged.connect(self._on_tunnel_inputs_changed)
        domain_row.add(self._domain_input)
        domain.add_row(domain_row)

        user_row = SettingRow(
            "User prefix",
            "Optional. Gives each person their own hostnames on a shared domain.",
        )
        self._user_slug_input = _input("e.g. dima")
        self._user_slug_input.textChanged.connect(self._on_tunnel_inputs_changed)
        user_row.add(self._user_slug_input)
        domain.add_row(user_row)

        self._hostnames_row = SettingRow("Hostnames", "", mono=True)
        self._tunnel_preview = self._hostnames_row._description
        self._apply_tunnel_btn = button("Apply", "default")
        self._apply_tunnel_btn.setEnabled(False)
        self._apply_tunnel_btn.clicked.connect(self._apply_tunnel_settings)
        self._hostnames_row.add(self._apply_tunnel_btn)
        domain.add_row(self._hostnames_row)
        page.add(domain)

        public = Group(
            "Public endpoints",
            "A freshly started tunnel needs a few seconds to register before "
            "these answer.",
        )
        self._files_public = CopyRow("Files System")
        self._terminal_public = CopyRow("Terminal")
        public.add_row(self._files_public)
        public.add_row(self._terminal_public)
        page.add(public)

        config = Group("cloudflared")
        self._tunnel_config = CopyRow("Config file")
        pick_config = button("Choose...", "secondary")
        pick_config.clicked.connect(self._pick_tunnel_config)
        self._tunnel_config.insert(0, pick_config)
        config.add_row(self._tunnel_config)
        page.add(config)

        page.finish()
        return page

    def _security_page(self) -> Page:
        page = Page("Security", "Who may connect, and where the tools may go.")

        auth = Group(
            "Authentication",
            "The token survives restarts. Clients send it as a Bearer header "
            "on every request.",
        )
        self._token_field = CopyRow("Auth token", secret=True)
        auth.add_row(self._token_field)
        regenerate_row = SettingRow(
            "Regenerate token",
            "Every client that uses the old token stops working until it gets "
            "the new one.",
        )
        regenerate = button("Regenerate", "destructive")
        regenerate.clicked.connect(self._regenerate_token)
        regenerate_row.add(regenerate)
        auth.add_row(regenerate_row)
        page.add(auth)

        access = Group("Access")
        outside_row = SettingRow(
            "Work outside the active project",
            "Let tools read and write anywhere on this machine. Off by "
            "default, so a path mistake cannot touch the rest of the disk. "
            "Applies to every project.",
        )
        self._allow_outside = Switch()
        self._allow_outside.toggled.connect(self._set_allow_outside)
        outside_row.add(self._allow_outside)
        access.add_row(outside_row)
        page.add(access)

        page.finish()
        return page

    def _notifications_page(self) -> Page:
        page = Page("Notifications", "A Telegram message when an agent finishes its work.")
        self._notify_badge = page.header_extra(Badge("Disabled", "neutral"))

        telegram = Group(
            "Telegram",
            "Credentials can also come from TELEGRAM_BOT_TOKEN and "
            "TELEGRAM_CHAT_ID in the environment or a .env file.",
        )
        enabled_row = SettingRow("Send notifications", "Message me when an agent goes quiet or calls notify_user.")
        self._notify_enabled = Switch()
        self._notify_enabled.toggled.connect(self._set_notifications_enabled)
        enabled_row.add(self._notify_enabled)
        telegram.add_row(enabled_row)

        token_row = SettingRow("Bot token", "From @BotFather.")
        self._bot_token_input = _input("123456:ABC-DEF...", 300)
        self._bot_token_input.setEchoMode(QLineEdit.Password)
        self._bot_token_input.textChanged.connect(self._on_notification_fields_changed)
        token_row.add(self._bot_token_input)
        telegram.add_row(token_row)

        chat_row = SettingRow("Chat ID", "Your user ID, or @channel.")
        self._chat_id_input = _input("e.g. 123456789", 300)
        self._chat_id_input.textChanged.connect(self._on_notification_fields_changed)
        chat_row.add(self._chat_id_input)
        telegram.add_row(chat_row)

        actions_row = SettingRow(
            "Test message",
            "Sends a short message with the values above. Save keeps them.",
        )
        self._test_notify_btn = button("Send test", "secondary")
        self._test_notify_btn.clicked.connect(self._send_test_notification)
        self._save_notify_btn = button("Save", "default")
        self._save_notify_btn.setEnabled(False)
        self._save_notify_btn.clicked.connect(self._save_notification_settings)
        actions_row.add(self._test_notify_btn)
        actions_row.add(self._save_notify_btn)
        telegram.add_row(actions_row)
        page.add(telegram)

        when = Group("When to notify")
        idle_row = SettingRow(
            "After a quiet spell",
            "Notify when no tool has been called for this many seconds.",
        )
        self._idle_timeout_input = _input("60", 64)
        self._idle_timeout_input.setAlignment(Qt.AlignRight)
        self._idle_timeout_input.textChanged.connect(self._on_notification_fields_changed)
        self._idle_switch = Switch()
        self._idle_switch.toggled.connect(self._set_notify_on_idle)
        idle_row.add(self._idle_timeout_input)
        idle_row.add(label("s", "caption"))
        idle_row.add(self._idle_switch)
        when.add_row(idle_row)

        tool_row = SettingRow(
            "notify_user tool",
            "Let agents send you a short note themselves.",
        )
        self._notify_tool_switch = Switch()
        self._notify_tool_switch.toggled.connect(self._set_notify_tool_enabled)
        tool_row.add(self._notify_tool_switch)
        when.add_row(tool_row)
        page.add(when)

        page.finish()
        return page

    def _activity_page(self) -> Page:
        page = Page("Activity", "Live output from the servers and the tunnel.", scroll=False)
        self._log_filter_control = Segmented(list(LOG_FILTERS), "all")
        self._log_filter_control.changed.connect(self._set_log_filter)
        page.header_extra(self._log_filter_control)
        clear = button("Clear", "ghost")
        clear.clicked.connect(self._clear_logs)
        page.header_extra(clear)

        self._log_view = QPlainTextEdit()
        self._log_view.setObjectName("logView")
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(2000)
        self._log_view.setFocusPolicy(Qt.ClickFocus)
        self._log_view.setLineWrapMode(QPlainTextEdit.NoWrap)

        holder = Group()
        holder.add_row(self._log_view, 1)
        page.add(holder, 1)
        return page

    # --- actions ---------------------------------------------------------

    def _start_servers(self) -> None:
        self._supervisor.start()
        QTimer.singleShot(400, self._refresh_status)
        QTimer.singleShot(600, self._check_health)

    def _stop_servers(self) -> None:
        self._supervisor.stop()
        self._refresh_status()
        self._check_health()

    def _toggle_servers(self) -> None:
        if self._supervisor.running:
            self._stop_servers()
        else:
            self._start_servers()

    def _restart_servers(self) -> None:
        self._supervisor.stop()
        self._supervisor.start()
        QTimer.singleShot(400, self._refresh_status)
        QTimer.singleShot(600, self._check_health)

    def _toggle_tunnel(self) -> None:
        if tunnel.status().get("running"):
            self._stop_tunnel()
        else:
            self._start_tunnel()

    def _open_active_folder(self) -> None:
        try:
            active = projects.active_project()
        except projects.ProjectError:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(active["root"]))

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
            self._hostnames_row.set_description(files_h + "  \u00b7  " + term_h)
        else:
            self._hostnames_row.set_description("Base domain cannot be empty.")

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
                "to update Cloudflare ingress routes. Connected clients will need "
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
            "now? Every connected agent uses this folder as its default "
            "immediately. '" + active["name"] + "' stays in the list either "
            "way.",
        )
        if confirm == QMessageBox.Yes:
            self._activate(project["id"])

    def _activate(self, project_id: str) -> None:
        try:
            projects.set_active_project(project_id)
        except projects.ProjectError as exc:
            QMessageBox.warning(self, "Could not switch project", str(exc))
            return
        self.refresh()

    def _remove_project(self, project_id: str, name: str) -> None:
        confirm = QMessageBox.question(
            self,
            "Remove project",
            "Remove '" + name + "' from the list? The folder itself stays on disk.",
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
            "Every client connection using the current token will stop "
            "working until it gets the new one. Continue?",
        )
        if confirm != QMessageBox.Yes:
            return
        settings.regenerate_token()
        logs.log("core", "Auth token regenerated")
        self.refresh()

    def _clear_logs(self) -> None:
        logs.clear()
        self._records.clear()
        self._log_view.clear()

    def _set_log_filter(self, key: str) -> None:
        self._log_filter = key
        self._log_view.clear()
        for record in self._records:
            if self._log_matches(record):
                self._log_view.appendHtml(self._log_line(record))
        self._log_view.verticalScrollBar().setValue(
            self._log_view.verticalScrollBar().maximum()
        )

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
                result = health.snapshot(timeout=3.5)
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
            summary = "Both servers are reachable through the tunnel."
        elif state == health.LOCAL:
            summary = "Both servers answer locally. Start the tunnel for remote clients."
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

    def _log_matches(self, record: dict) -> bool:
        if self._log_filter == "calls":
            return record.get("kind") == "call"
        if self._log_filter == "problems":
            return record.get("level") in ("warn", "error")
        return True

    @staticmethod
    def _log_line(record: dict) -> str:
        """One coloured line: time, source, message."""
        stamp = time.strftime("%H:%M:%S", time.localtime(record.get("time", time.time())))
        source = html.escape(str(record.get("source", "")))
        message = html.escape(str(record.get("message", ""))).replace("\n", "<br>")
        level = record.get("level", "info")
        colour = {
            "warn": COLORS["warning_text"],
            "error": COLORS["danger_text"],
            "debug": COLORS["faint"],
        }.get(level, COLORS["text"] if record.get("kind") == "call" else COLORS["text_2"])
        pad = "&nbsp;" * max(2, 11 - len(source))
        return (
            '<span style="color:%s">%s</span>&nbsp;&nbsp;'
            '<span style="color:%s">%s</span>%s'
            '<span style="color:%s">%s</span>'
        ) % (COLORS["faint"], stamp, COLORS["muted"], source, pad, colour, message)

    def _append_log(self, record: dict) -> None:
        self._records.append(record)
        if self._log_matches(record):
            self._log_view.appendHtml(self._log_line(record))

    def refresh(self) -> None:
        data = settings.all()
        servers = data["servers"]
        path = servers["http_path"]
        host = servers["host"]

        self._local_urls = {
            "files": "http://" + host + ":" + str(servers["files_port"]) + path,
            "terminal": "http://" + host + ":" + str(servers["terminal_port"]) + path,
        }
        self._servers_row.set_description(
            "Files System :" + str(servers["files_port"]) + " and Terminal :"
            + str(servers["terminal_port"]) + " on " + host
        )

        urls = tunnel.public_urls()
        self._public_urls = {
            "files": urls.get("files", "") or "",
            "terminal": urls.get("terminal", "") or "",
        }
        self._files_public.set_value(self._public_urls["files"] or "(hostname not set)")
        self._terminal_public.set_value(self._public_urls["terminal"] or "(hostname not set)")
        self._files_public.set_copyable(bool(self._public_urls["files"]))
        self._terminal_public.set_copyable(bool(self._public_urls["terminal"]))
        self._tunnel_config.set_value(data["tunnel"]["config_file"] or "(not set)")
        self._tunnel_config.set_copyable(bool(data["tunnel"]["config_file"]))
        if not self._endpoint_mode_touched:
            self._endpoint_mode.set_value("public" if self._public_urls["files"] else "local")
        self._render_endpoints()

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
        if not self._apply_tunnel_btn.isEnabled():
            self._hostnames_row.set_description(files_h + "  \u00b7  " + term_h)
        configured, reason = tunnel.is_configured()
        self._tunnel_row.set_description(
            files_h + "  \u00b7  " + term_h if configured else reason
        )

        self._token_field.set_value(data["auth"]["token"])
        self._token_overview.set_value(data["auth"]["token"])

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
        group = self._projects_group
        group.clear_rows()
        items = data.get("projects", [])
        for project in items:
            is_active = project["id"] == active_id
            row = SettingRow(project["name"], project["root"], mono=True)
            if is_active:
                row.add(Badge("Active", "success"))
            else:
                activate = button("Set active", "secondary")
                activate.clicked.connect(
                    lambda _checked=False, pid=project["id"]: self._activate(pid)
                )
                row.add(activate)
            remove = button("Remove", "ghost", "Remove from the list; the folder stays on disk")
            remove.clicked.connect(
                lambda _checked=False, pid=project["id"], name=project["name"]:
                self._remove_project(pid, name)
            )
            row.add(remove)
            group.add_row(row)
        if not items:
            empty = SettingRow("No projects yet", "Add a folder to give the tools a home.")
            add = button("Add folder", "default")
            add.clicked.connect(self._add_project)
            empty.add(add)
            group.add_row(empty)

        try:
            active = projects.active_project()
        except projects.ProjectError:
            active = None
        if active:
            self._project_chip.name.setText(active["name"])
            self._project_chip.path.setText(active["root"])
            self._active_row.set_title(active["name"])
            self._active_row.set_description(active["root"])
        else:
            self._project_chip.name.setText("None")
            self._project_chip.path.setText("Pick a folder")
            self._active_row.set_title("No active project")
            self._active_row.set_description("Tools need a folder to work in.")

    def _on_endpoint_mode(self, _key: str) -> None:
        self._endpoint_mode_touched = True
        self._render_endpoints()

    def _render_endpoints(self) -> None:
        """Fill the overview's endpoint rows with the public or local URLs."""
        if not hasattr(self, "_local_urls"):
            return
        mode = self._endpoint_mode.value()
        source = self._public_urls if mode == "public" else self._local_urls
        for key, row in (("files", self._files_endpoint), ("terminal", self._terminal_endpoint)):
            value = source.get(key) or ""
            row.set_value(value or "Set a domain on the Tunnel page")
            row.set_copyable(bool(value))

    def _refresh_status(self) -> None:
        running = self._supervisor.running
        self._servers_badge.set_state(
            "Running" if running else "Stopped", "success" if running else "danger"
        )
        self._set_text(self._servers_toggle, "Stop" if running else "Start")
        self._restart_button.setVisible(running)

        status = tunnel.status()
        tunnel_running = bool(status.get("running"))
        for badge in (self._tunnel_badge, self._tunnel_page_badge):
            badge.set_state(
                "Running" if tunnel_running else "Stopped",
                "success" if tunnel_running else "danger",
            )
        self._set_text(self._tunnel_toggle, "Stop" if tunnel_running else "Start")
        self._set_text(
            self._tunnel_page_toggle, "Stop tunnel" if tunnel_running else "Start tunnel"
        )

        self._sync_master(running or tunnel_running)

    @staticmethod
    def _set_text(widget, text: str) -> None:
        if widget.text() != text:
            widget.setText(text)

    def _sync_master(self, anything_running: bool) -> None:
        """The sidebar button flips between starting and stopping.

        Style follows meaning: starting is the primary action, stopping is
        a quiet one, so it never becomes the brightest thing on screen.
        """
        text = "Stop everything" if anything_running else "Start everything"
        variant = "secondary" if anything_running else "default"
        self._set_text(self._master_button, text)
        self._master_button.set_glyph("stop" if anything_running else "play")
        if self._master_button.property("variant") != variant:
            self._master_button.setProperty("variant", variant)
            repolish(self._master_button)

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
