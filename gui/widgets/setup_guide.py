"""Notion setup guide - a separate screen, opened as a modal dialog.

Everything needed to wire this machine into Notion lives here: the two
endpoint URLs, the auth token, the ready-to-paste skill text, and the
exact wording to use when asking the chat to add an MCP connection.
Every value has a copy button, because all of this ends up pasted into
Notion by hand.

The dialog uses the same custom chrome as the main window, so it looks
like part of the app rather than a Windows dialog.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core import skills as skills_module
from core import tunnel
from core.config import settings
from gui.widgets.chrome import install_frameless
from gui.widgets.primitives import Badge, Card, CopyField, button, label, separator

SKILL_NAME = "mcp-coding-agent"

CONNECT_PROMPT = (
    "Connect an MCP server for me.\n"
    "Name: Files System\n"
    "URL: {files_url}\n"
    "Authentication: Bearer Token"
)


def _page() -> tuple:
    """Return (scroll area, vertical layout) for one guide tab.

    Margins are symmetric: the scrollbar is always visible and lives in
    the tab panel's own padding, so the content does not shift sideways
    depending on whether a tab happens to scroll.
    """
    inner = QWidget()
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(4, 4, 4, 4)
    layout.setSpacing(14)

    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.NoFrame)
    area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setWidget(inner)
    # A scroll viewport is its own widget and fills itself with the palette
    # colour unless told not to, which is what put a grey slab behind the
    # cards. Here the cards are the only surfaces.
    area.viewport().setAutoFillBackground(False)
    inner.setAutoFillBackground(False)
    return area, layout


def _step(number: int, text: str) -> QWidget:
    """A numbered instruction line."""
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)

    badge = Badge(str(number), "neutral")
    badge.setFixedWidth(26)
    layout.addWidget(badge, 0, Qt.AlignTop)

    body = label(text, "step")
    body.setTextInteractionFlags(Qt.TextSelectableByMouse)
    layout.addWidget(body, 1)
    return container


class SetupGuideDialog(QDialog):
    """Step-by-step "how do I plug this into Notion" companion."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.resize(800, 760)
        chrome = install_frameless(self, "Notion setup guide", show_maximize=False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        shell = QWidget()
        shell.setObjectName("windowShell")
        shell_layout = QVBoxLayout(shell)
        # 1px so children never paint over the shell's own border.
        shell_layout.setContentsMargins(1, 1, 1, 1)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(chrome.title_bar)
        outer.addWidget(shell)

        layout = QVBoxLayout()
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(14)
        shell_layout.addLayout(layout, 1)

        header = QVBoxLayout()
        header.setSpacing(3)
        header.addWidget(label("Notion setup guide", "title"))
        header.addWidget(
            label(
                "Everything needed to connect this machine to a Notion chat. "
                "Values update automatically when settings change.",
                "subtitle",
            )
        )
        layout.addLayout(header)

        tabs = QTabWidget()
        tabs.setDocumentMode(False)
        tabs.addTab(self._connection_tab(), "1. Connect MCP")
        tabs.addTab(self._skill_tab(), "2. Add the skill")
        tabs.addTab(self._usage_tab(), "3. Daily use")
        layout.addWidget(tabs, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close_button = button("Close", "secondary")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        layout.addLayout(footer)

        self.refresh()
        self._unsubscribe = settings.subscribe(lambda _snapshot: self.refresh())

    # --- tabs ------------------------------------------------------------

    def _connection_tab(self) -> QWidget:
        page, layout = _page()

        endpoints = Card(
            "Endpoints and token",
            "Paste these into Notion when adding an MCP connection.",
        )
        self._files_url = CopyField("Files System URL")
        self._terminal_url = CopyField("Terminal URL")
        self._token = CopyField("Auth token (Bearer)", secret=True)
        endpoints.add(self._files_url)
        endpoints.add(self._terminal_url)
        endpoints.add(self._token)
        endpoints.add(separator())
        endpoints.add(
            label(
                "The token stays the same across restarts. It only changes if "
                "you regenerate it on the main screen - and then both Notion "
                "connections have to be added again.",
                "muted",
            )
        )
        layout.addWidget(endpoints)

        steps = Card(
            "How to add a connection",
            "Notion asks for MCP connections inside the chat itself.",
        )
        steps.add(
            _step(
                1,
                "Press 'Start everything' in the title bar and wait for the "
                "pill next to it to read 'Ready in Notion'. Turn on autostart "
                "on the main screen to skip this step in future.",
            )
        )
        steps.add(
            _step(
                2,
                "In a Notion chat, ask the assistant to connect an MCP server. "
                "Copy the ready-made request below and send it.",
            )
        )
        steps.add(
            _step(
                3,
                "In the dialog that appears, choose Bearer Token as the "
                "authentication method and paste the token above.",
            )
        )
        steps.add(
            _step(
                4,
                "Repeat for the second server: change the name to Terminal and "
                "use the Terminal URL. Two connections, same token.",
            )
        )
        steps.add(separator())

        steps.add(label("Ready-made request", "label"))
        self._prompt_box = QPlainTextEdit()
        self._prompt_box.setReadOnly(True)
        self._prompt_box.setFixedHeight(90)
        steps.add(self._prompt_box)

        copy_prompt = button("Copy request", "secondary")
        copy_prompt.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(self._prompt_box.toPlainText())
        )
        steps.add(copy_prompt)
        layout.addWidget(steps)

        multiuser = Card(
            "Multi-user and custom domains",
            "Multiple team members can share the same domain with user prefixes.",
        )
        multiuser.add(
            label(
                "Each user should set a unique User Prefix (e.g. 'dima', 'alex') "
                "in the Tunnel card on the main screen. This gives each machine its "
                "own isolated endpoints (<user>-files.<domain> and <user>-term.<domain>).\n\n"
                "Tip: In Cloudflare DNS, add a single Wildcard CNAME record (* -> your-tunnel.cfargotunnel.com) "
                "to automatically route any prefix without manual DNS setup.",
                "muted",
            )
        )
        layout.addWidget(multiuser)

        layout.addStretch(1)
        return page

    def _skill_tab(self) -> QWidget:
        page, layout = _page()

        instructions = Card(
            "Skills for Notion AI",
            "Custom instructions that tell Notion AI how to use tools and libraries.",
        )
        instructions.add(
            _step(
                1,
                "In Notion, open Settings -> Skills and click 'Add a skill'.",
            )
        )
        instructions.add(
            _step(
                2,
                "Click 'Copy skill text' on any skill below and paste it as the skill content.",
            )
        )
        instructions.add(
            _step(
                3,
                "Name the skill in Notion using the title or slug shown on the card.",
            )
        )
        instructions.add(
            _step(
                4,
                "In any Notion chat, mention the skill to activate it for your session.",
            )
        )
        layout.addWidget(instructions)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)

        self._skills_count_label = label("Discovered skills", "label")
        header_row.addWidget(self._skills_count_label, 1)

        open_folder_btn = button("Open skills folder", "secondary")
        open_folder_btn.clicked.connect(self._open_skills_folder)
        header_row.addWidget(open_folder_btn)

        reload_btn = button("Reload skills", "secondary")
        reload_btn.clicked.connect(self._load_skills)
        header_row.addWidget(reload_btn)

        layout.addLayout(header_row)

        self._skills_list_layout = QVBoxLayout()
        self._skills_list_layout.setContentsMargins(0, 0, 0, 0)
        self._skills_list_layout.setSpacing(10)
        layout.addLayout(self._skills_list_layout)

        layout.addStretch(1)
        return page

    def _usage_tab(self) -> QWidget:
        page, layout = _page()

        habits = Card(
            "Working day to day",
            "Small habits that keep sessions predictable.",
        )
        habits.add(
            _step(
                1,
                "Pick the project on the main screen before starting a chat. "
                "Tools resolve paths against the active project root.",
            )
        )
        habits.add(
            _step(
                2,
                "Ask the assistant to call get_active_project first if you are "
                "unsure which folder a chat is pointed at.",
            )
        )
        habits.add(
            _step(
                3,
                "Switching the active project affects every open chat at once, "
                "since they all talk to the same machine.",
            )
        )
        habits.add(
            _step(
                4,
                "Closing the app stops the servers and the tunnel. Notion will "
                "report the connection as unavailable - that is expected, just "
                "start the app again.",
            )
        )
        layout.addWidget(habits)

        trouble = Card("If something breaks", "The usual suspects, in order.")
        trouble.add(
            _step(
                1,
                "Notion cannot connect: check the badges here first. Nine times "
                "out of ten the app simply is not running.",
            )
        )
        trouble.add(
            _step(
                2,
                "401 responses mean the token in Notion no longer matches the "
                "one on this screen. Add the connection again with the current "
                "token.",
            )
        )
        trouble.add(
            _step(
                3,
                "Port already in use: another copy of the app, or the old "
                "gateway, is still listening on the same port.",
            )
        )
        trouble.add(
            _step(
                4,
                "The tunnel exits immediately: the cloudflared config path is "
                "wrong, or its ingress hostnames point at different ports than "
                "the ones configured here.",
            )
        )
        layout.addWidget(trouble)

        layout.addStretch(1)
        return page

    # --- data ------------------------------------------------------------

    def refresh(self) -> None:
        data = settings.all()
        servers = data["servers"]
        tunnel_cfg = data["tunnel"]
        path = servers["http_path"]

        urls = tunnel.public_urls()
        local_base = "http://" + str(servers["host"]) + ":"
        if tunnel_cfg.get("enabled"):
            files_url = urls.get("files") or (local_base + str(servers["files_port"]) + path)
            terminal_url = urls.get("terminal") or (local_base + str(servers["terminal_port"]) + path)
        else:
            files_url = local_base + str(servers["files_port"]) + path
            terminal_url = local_base + str(servers["terminal_port"]) + path

        self._files_url.set_value(files_url)
        self._terminal_url.set_value(terminal_url)
        self._token.set_value(data["auth"]["token"])
        self._prompt_box.setPlainText(CONNECT_PROMPT.format(files_url=files_url))

        self._load_skills()

    def _open_skills_folder(self) -> None:
        root = skills_module.skills_root()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(root)))

    def _load_skills(self) -> None:
        from PySide6.QtCore import QTimer

        while self._skills_list_layout.count():
            item = self._skills_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        all_skills = skills_module.discover()
        self._skills_count_label.setText(f"Discovered skills ({len(all_skills)})")

        if not all_skills:
            empty_card = Card(
                "No skills found",
                f"Place skill folders or .md files in {skills_module.skills_root()}",
            )
            self._skills_list_layout.addWidget(empty_card)
            return

        for s in all_skills:
            desc = s.get("description") or f"Skill slug: {s['slug']}"
            card = Card(s["name"], desc)
            card.header_extra(Badge(s["slug"], "neutral"))

            btn_row = QHBoxLayout()
            btn_row.setContentsMargins(0, 0, 0, 0)
            btn_row.setSpacing(8)

            copy_btn = button("Copy skill text", "default")
            skill_file = s["file"]

            def make_copy_handler(path_to_file: str, btn: QPushButton):
                def handler() -> None:
                    try:
                        content = Path(path_to_file).read_text(encoding="utf-8")
                        QGuiApplication.clipboard().setText(content)
                        btn.setText("Copied!")
                        btn.setEnabled(False)
                        QTimer.singleShot(
                            1200,
                            lambda: (btn.setText("Copy skill text"), btn.setEnabled(True)),
                        )
                    except Exception:
                        btn.setText("Failed to read")
                return handler

            copy_btn.clicked.connect(make_copy_handler(skill_file, copy_btn))
            btn_row.addWidget(copy_btn)

            open_file_btn = button("Open file", "secondary")
            open_file_btn.clicked.connect(
                lambda _checked=False, f=skill_file: QDesktopServices.openUrl(
                    QUrl.fromLocalFile(f)
                )
            )
            btn_row.addWidget(open_file_btn)
            btn_row.addStretch(1)

            card.add_layout(btn_row)
            self._skills_list_layout.addWidget(card)

    # --- lifecycle -------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        # Stop listening once the dialog goes away, otherwise the settings
        # store keeps a reference to a deleted widget.
        self._unsubscribe()
        super().closeEvent(event)
