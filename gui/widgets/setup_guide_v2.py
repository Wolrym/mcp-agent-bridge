"""Agent setup guide - modern multi-agent companion dialog.

Provides connection details, endpoint URLs, authentication tokens,
and copy-ready configurations for Notion AI, Claude Desktop, Cursor,
and autonomous agent frameworks.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPlainTextEdit,
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


def _page() -> tuple[QScrollArea, QVBoxLayout]:
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
    area.viewport().setAutoFillBackground(False)
    inner.setAutoFillBackground(False)
    return area, layout


def _step(number: int, text: str) -> QWidget:
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


class SetupGuideV2Dialog(QDialog):
    """Modern step-by-step connection guide for AI Agents."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.resize(840, 780)
        chrome = install_frameless(self, "Agent Setup Guide", show_maximize=False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        shell = QWidget()
        shell.setObjectName("windowShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(1, 1, 1, 1)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(chrome.title_bar)
        outer.addWidget(shell)

        layout = QVBoxLayout()
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(14)
        shell_layout.addLayout(layout, 1)

        header = QVBoxLayout()
        header.setSpacing(3)
        header.addWidget(label("Agent Setup Guide", "title"))
        header.addWidget(
            label(
                "Connect external or local AI agents (Notion, Claude Desktop, Cursor, ChatGPT) "
                "to your local workspace via MCP.",
                "subtitle",
            )
        )
        layout.addLayout(header)

        tabs = QTabWidget()
        tabs.setDocumentMode(False)
        tabs.addTab(self._connection_tab(), "1. Endpoints & Token")
        tabs.addTab(self._notion_tab(), "2. Notion AI")
        tabs.addTab(self._claude_ide_tab(), "3. Claude & IDEs")
        tabs.addTab(self._skills_tab(), "4. Skills")
        tabs.addTab(self._tunnel_tab(), "5. Tunnel & DNS")
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
            "Connection Endpoints",
            "Use these streamable HTTP/SSE endpoints to connect any MCP-compatible agent.",
        )
        self._files_pub = CopyField("Files System (Public URL - Cloudflare)")
        self._terminal_pub = CopyField("Terminal (Public URL - Cloudflare)")
        self._files_loc = CopyField("Files System (Local URL)")
        self._terminal_loc = CopyField("Terminal (Local URL)")
        self._token = CopyField("Bearer Auth Token", secret=True)

        endpoints.add(self._files_pub)
        endpoints.add(self._terminal_pub)
        endpoints.add(separator())
        endpoints.add(self._files_loc)
        endpoints.add(self._terminal_loc)
        endpoints.add(separator())
        endpoints.add(self._token)
        layout.addWidget(endpoints)

        prompt_card = Card(
            "Ready-made Agent Connect Request",
            "Copy and paste this into any chat agent that supports interactive MCP configuration.",
        )
        self._prompt_box = QPlainTextEdit()
        self._prompt_box.setReadOnly(True)
        self._prompt_box.setFixedHeight(95)
        prompt_card.add(self._prompt_box)

        copy_prompt = button("Copy Request", "secondary")
        copy_prompt.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(self._prompt_box.toPlainText())
        )
        prompt_card.add(copy_prompt)
        layout.addWidget(prompt_card)

        layout.addStretch(1)
        return page

    def _notion_tab(self) -> QWidget:
        page, layout = _page()

        steps = Card(
            "Connecting to Notion AI",
            "Notion AI can invoke local tools via the Cloudflare tunnel.",
        )
        steps.add(
            _step(
                1,
                "Ensure servers and tunnel are running (Health pill shows 'Ready for Agents').",
            )
        )
        steps.add(
            _step(
                2,
                "In Notion chat, ask the assistant to connect an MCP server, using the "
                "Public Files System URL and your Bearer Auth Token.",
            )
        )
        steps.add(
            _step(
                3,
                "Repeat for the Terminal server using the Public Terminal URL with the same token.",
            )
        )
        steps.add(
            _step(
                4,
                "Once connected, Notion AI can browse files, create edits, execute terminal "
                "commands, and run tests directly in your active workspace.",
            )
        )
        layout.addWidget(steps)
        layout.addStretch(1)
        return page

    def _claude_ide_tab(self) -> QWidget:
        page, layout = _page()

        claude_card = Card(
            "Claude Desktop Configuration",
            "Add this snippet to your claude_desktop_config.json (%APPDATA%\\Claude\\claude_desktop_config.json).",
        )
        self._claude_json_box = QPlainTextEdit()
        self._claude_json_box.setReadOnly(True)
        self._claude_json_box.setFixedHeight(160)
        claude_card.add(self._claude_json_box)

        copy_claude = button("Copy Claude Config JSON", "secondary")
        copy_claude.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(
                self._claude_json_box.toPlainText()
            )
        )
        claude_card.add(copy_claude)
        layout.addWidget(claude_card)

        ide_card = Card(
            "Cursor / Windsurf / Local IDE Agents",
            "Connect local AI coding assistants using the Local URLs directly.",
        )
        ide_card.add(
            label(
                "Local agents running on the same PC can connect directly to "
                "http://127.0.0.1:9500/sse and http://127.0.0.1:9501/sse without needing the tunnel. "
                "Authentication header: Authorization: Bearer <your-token>.",
                "muted",
            )
        )
        layout.addWidget(ide_card)
        layout.addStretch(1)
        return page

    def _skills_tab(self) -> QWidget:
        page, layout = _page()

        intro = Card(
            "Workspace Skills",
            "Specialized markdown prompts that instruct AI agents on project workflows and tools.",
        )
        intro.add(
            label(
                "Skills found in your 'skills/' directory are automatically listed below. "
                "Click 'Copy Skill Text' to paste instructions into your AI agent or workspace prompts.",
                "muted",
            )
        )
        layout.addWidget(intro)

        # Scan available skills
        skill_items = skills_module.discover()
        if not skill_items:
            empty_card = Card("No Skills Found", "Add .md files to your skills/ folder.")
            layout.addWidget(empty_card)
        else:
            for item in skill_items:
                title = item.get("title") or item.get("slug") or "Untitled Skill"
                desc = item.get("description") or "No description provided."
                body = item.get("body") or ""

                scard = Card(title, desc)
                if body:
                    copy_btn = button(f"Copy {title}", "secondary")
                    copy_btn.clicked.connect(
                        (lambda text=body: lambda: QGuiApplication.clipboard().setText(text))()
                    )
                    scard.add(copy_btn)
                layout.addWidget(scard)

        layout.addStretch(1)
        return page

    def _tunnel_tab(self) -> QWidget:
        page, layout = _page()

        tunnel_card = Card(
            "Cloudflare Tunnel Architecture",
            "Secure, encrypted ingress without port forwarding or exposing your home IP.",
        )
        tunnel_card.add(
            label(
                "1. Multi-User Subdomains:\n"
                "   Set a unique 'User prefix' (e.g. 'dima', 'alex') on the main panel. "
                "This isolates endpoints as <prefix>-files.<domain> and <prefix>-term.<domain>.\n\n"
                "2. Wildcard DNS Setup:\n"
                "   In Cloudflare DNS, add a single CNAME record (* -> your-tunnel-id.cfargotunnel.com). "
                "This routes all user subdomains automatically without manual DNS edits.\n\n"
                "3. Re-applying Settings:\n"
                "   Changing domain or prefix updates local config and re-routes Cloudflare ingress seamlessly.",
                "muted",
            )
        )
        layout.addWidget(tunnel_card)
        layout.addStretch(1)
        return page

    # --- state sync ------------------------------------------------------

    def refresh(self) -> None:
        data = settings.all()
        servers = data.get("servers", {})
        path = servers.get("http_path", "/sse")
        host = servers.get("host", "127.0.0.1")

        loc_files = f"http://{host}:{servers.get('files_port', 9500)}{path}"
        loc_term = f"http://{host}:{servers.get('terminal_port', 9501)}{path}"
        self._files_loc.set_value(loc_files)
        self._terminal_loc.set_value(loc_term)

        urls = tunnel.public_urls()
        pub_files = urls.get("files", "") or "(tunnel stopped or hostname not configured)"
        pub_term = urls.get("terminal", "") or "(tunnel stopped or hostname not configured)"
        self._files_pub.set_value(pub_files)
        self._terminal_pub.set_value(pub_term)

        token = data.get("auth", {}).get("token", "")
        self._token.set_value(token)

        active_url = pub_files if "https://" in pub_files else loc_files
        self._prompt_box.setPlainText(
            f"Connect an MCP server for me.\n"
            f"Name: Files System\n"
            f"URL: {active_url}\n"
            f"Authentication: Bearer Token\n"
            f"Token: {token}"
        )

        claude_config = {
            "mcpServers": {
                "workspace-files": {
                    "url": pub_files if "https://" in pub_files else loc_files,
                    "headers": {"Authorization": f"Bearer {token}"},
                },
                "workspace-terminal": {
                    "url": pub_term if "https://" in pub_term else loc_term,
                    "headers": {"Authorization": f"Bearer {token}"},
                },
            }
        }
        self._claude_json_box.setPlainText(json.dumps(claude_config, indent=2))
