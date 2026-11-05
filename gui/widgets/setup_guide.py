"""Setup guide - a separate screen, opened as a modal dialog.

Everything needed to connect an MCP client to this machine lives here:
the two endpoint URLs, the auth token, a config snippet, a ready-made
request for chat-based assistants, and the skill texts. Every value has
a copy button, because all of this ends up pasted into a client by hand.

The dialog uses the same chrome and layout as the main window - a sidebar
of pages next to the content panel - so it looks like part of the app
rather than a Windows dialog.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core import projects as projects_module
from core import skills as skills_module
from core import tunnel
from core.config import settings
from gui.widgets.chrome import install_frameless
from gui.widgets.primitives import (
    Backdrop,
    Card,
    CopyRow,
    Group,
    NavButton,
    Page,
    Segmented,
    SettingRow,
    button,
    label,
    separator,
)

SKILL_NAME = "mcp-coding-agent-v2"

CONNECT_PROMPT = (
    "Connect an MCP server for me.\n"
    "Name: Files System\n"
    "URL: {files_url}\n"
    "Authentication: Bearer Token"
)

# For clients configured through a JSON file (mcp.json and the like). The
# token stays a placeholder so the snippet can be shown and shared safely.
CONFIG_SNIPPET = """{{
  "mcpServers": {{
    "files-system": {{
      "url": "{files_url}",
      "headers": {{ "Authorization": "Bearer <token>" }}
    }},
    "terminal": {{
      "url": "{terminal_url}",
      "headers": {{ "Authorization": "Bearer <token>" }}
    }}
  }}
}}"""


GUIDE_PAGES = (
    ("Connect", "tunnel"),
    ("Skills", "guide"),
    ("Daily use", "activity"),
)


def _step(number: int, text: str) -> QWidget:
    """A numbered instruction line."""
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)

    badge = QLabel(str(number))
    badge.setProperty("variant", "stepNumber")
    badge.setAlignment(Qt.AlignCenter)
    layout.addWidget(badge, 0, Qt.AlignTop)

    body = label(text, "step")
    body.setTextInteractionFlags(Qt.TextSelectableByMouse)
    layout.addWidget(body, 1)
    return container


class SetupGuideDialog(QDialog):
    """Step-by-step "how do I connect a client to this" companion."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.resize(940, 720)
        chrome = install_frameless(self, "Setup guide", show_maximize=False)

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

        self._stack = QStackedWidget()
        self._stack.addWidget(self._connection_tab())
        self._stack.addWidget(self._skill_tab())
        self._stack.addWidget(self._usage_tab())

        nav = QWidget()
        nav.setObjectName("sidebar")
        nav.setFixedWidth(190)
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(10, 6, 10, 10)
        nav_layout.setSpacing(2)
        self._nav = QButtonGroup(self)
        self._nav.setExclusive(True)
        self._nav_buttons = []
        for index, (text, icon) in enumerate(GUIDE_PAGES):
            item = NavButton(text, icon)
            item.clicked.connect(lambda _checked=False, i=index: self.show_page(i))
            self._nav.addButton(item)
            self._nav_buttons.append(item)
            nav_layout.addWidget(item)
        nav_layout.addStretch(1)
        note = label("Values update by themselves when settings change.", "caption")
        note.setContentsMargins(10, 0, 4, 0)
        nav_layout.addWidget(note)

        backdrop = Backdrop()
        backdrop_layout = QVBoxLayout(backdrop)
        backdrop_layout.setContentsMargins(1, 1, 1, 1)
        backdrop_layout.addWidget(self._stack)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 8, 8)
        body.setSpacing(0)
        body.addWidget(nav)
        body.addWidget(backdrop, 1)
        shell_layout.addLayout(body, 1)

        self.show_page(0)
        self.refresh()
        self._unsubscribe = settings.subscribe(lambda _snapshot: self.refresh())

    def page_count(self) -> int:
        return self._stack.count()

    def show_page(self, index: int) -> None:
        if 0 <= index < self._stack.count():
            self._stack.setCurrentIndex(index)
            self._nav_buttons[index].setChecked(True)

    # --- tabs ------------------------------------------------------------

    def _connection_tab(self) -> QWidget:
        page = Page(
            "Connect a client",
            "Everything an MCP client needs to reach this machine.",
        )

        endpoints = Group(
            "Endpoints and token",
            "The token stays the same across restarts. It only changes if you "
            "regenerate it on the Security page - and then every client "
            "connection needs the new one.",
        )
        self._files_url = CopyRow("Files System URL")
        self._terminal_url = CopyRow("Terminal URL")
        self._token = CopyRow("Auth token (Bearer)", secret=True)
        endpoints.add_row(self._files_url)
        endpoints.add_row(self._terminal_url)
        endpoints.add_row(self._token)
        page.add(endpoints)

        steps = Card(
            "How to add a connection",
            "Any client that supports remote (streamable HTTP) MCP servers "
            "with a Bearer token works.",
        )
        steps.add(
            _step(
                1,
                "Press 'Start everything' at the top of the sidebar and wait "
                "for the pill in the title bar to read 'Ready (public)'. Turn "
                "on 'Start with the panel' on the Overview page to skip this "
                "step in future.",
            )
        )
        steps.add(
            _step(
                2,
                "Add a remote MCP server named Files System with the Files System "
                "URL. Clients with a config file take the snippet below; chat "
                "assistants that add connections themselves take the request.",
            )
        )
        steps.add(
            _step(
                3,
                "Choose Bearer token authentication (the header is "
                "'Authorization: Bearer <token>') and paste the token above.",
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

        steps.add(label("Config file snippet", "label"))
        self._config_box = QPlainTextEdit()
        self._config_box.setReadOnly(True)
        self._config_box.setFixedHeight(190)
        steps.add(self._config_box)

        copy_config = button("Copy snippet", "secondary")
        copy_config.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(self._config_box.toPlainText())
        )
        steps.add(copy_config)
        page.add(steps)

        multiuser = Card(
            "Multi-user and custom domains",
            "Multiple team members can share the same domain with user prefixes.",
        )
        multiuser.add(
            label(
                "Each user should set a unique User Prefix (e.g. 'dima', 'alex') "
                "on the Tunnel page. This gives each machine its "
                "own isolated endpoints (<user>-files.<domain> and <user>-term.<domain>).\n\n"
                "Tip: In Cloudflare DNS, add a single Wildcard CNAME record (* -> your-tunnel.cfargotunnel.com) "
                "to automatically route any prefix without manual DNS setup.",
                "muted",
            )
        )
        page.add(multiuser)

        page.finish()
        return page

    def _skill_tab(self) -> QWidget:
        page = Page("Skills", "Instructions that tell an agent how to work with these tools.")

        instructions = Card(
            "How agents get them",
            "Loaded on demand, so they cost nothing until used.",
        )
        instructions.add(
            _step(
                1,
                "Agents connected to Terminal load skills themselves with "
                "list_skills and get_skill - just ask for one by name, e.g. "
                "'load the mcp-coding-agent-v2 skill'.",
            )
        )
        instructions.add(
            _step(
                2,
                "If your client has its own skills or custom-instructions "
                "feature, copy a skill's text below and paste it there.",
            )
        )
        instructions.add(
            _step(
                3,
                "Grouped skills (design/, animation/, ...) are listed "
                "collapsed; agents open a group with list_skills(group=...). "
                "Here, Show opens a group.",
            )
        )
        instructions.add(
            _step(
                4,
                "Project skills go into <project>/.agents/skills/<name>/SKILL.md. "
                "list_skills(project=...) shows them next to these global ones, "
                "together with the project's AGENTS.md / CLAUDE.md; on a name "
                "clash the project's skill wins. Pick a project below to see "
                "exactly what an agent gets there.",
            )
        )
        instructions.add(
            _step(
                5,
                "Skills you want to keep but switch off go into the bin/ folder: "
                "agents never see them. Pack turns a skill folder into a .zip "
                "in Downloads for uploading elsewhere (Notion: Library > "
                "Skills > More ways to add a skill > Upload skill).",
            )
        )
        page.add(instructions)

        # Which project's view to show: what an agent gets with
        # list_skills() or list_skills(project=...).
        self._scope = "global"
        self._scope_folder = ""
        self._expanded: set = set()

        scope_group = Group("Show skills for")
        self._scope_row = SettingRow("Global skills only", "")
        self._scope_picker = Segmented(
            [("global", "Global"), ("active", "Active project"), ("folder", "Other folder...")],
            "global",
        )
        self._scope_picker.changed.connect(self._pick_scope)
        self._scope_row.add(self._scope_picker)
        scope_group.add_row(self._scope_row)
        page.add(scope_group)

        self._project_group = Group("Project")
        page.add(self._project_group)

        self._skills_group = Group("Global skills")
        open_folder_btn = button("Open folder", "ghost")
        open_folder_btn.clicked.connect(self._open_skills_folder)
        self._skills_group.header_extra(open_folder_btn)
        reload_btn = button("Reload", "ghost")
        reload_btn.clicked.connect(self._load_skills)
        self._skills_group.header_extra(reload_btn)
        pack_btn = button("Pack folder...", "ghost", "Zip any skill folder for uploading to another agent")
        pack_btn.clicked.connect(lambda: self._pack_skill())
        self._skills_group.header_extra(pack_btn)
        page.add(self._skills_group)

        page.finish()
        return page

    def _usage_tab(self) -> QWidget:
        page = Page("Daily use", "Small habits that keep sessions predictable.")

        habits = Card("Working day to day")
        habits.add(
            _step(
                1,
                "Pick the project on the Projects page before starting a chat. "
                "It is the default for relative paths; agents should still "
                "use absolute paths.",
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
                "Closing the app stops the servers and the tunnel. Clients "
                "will report the connection as unavailable - that is expected, "
                "just start the app again.",
            )
        )
        page.add(habits)

        trouble = Card("If something breaks", "The usual suspects, in order.")
        trouble.add(
            _step(
                1,
                "A client cannot connect: check the pill in the title bar "
                "first. Nine times out of ten the app simply is not running.",
            )
        )
        trouble.add(
            _step(
                2,
                "401 responses mean the client's token no longer matches the "
                "one on this screen. Update the connection with the current "
                "token. 429 means too many wrong tokens: wait 15 minutes.",
            )
        )
        trouble.add(
            _step(
                3,
                "Port already in use: another copy of the app is still "
                "listening on the same port.",
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
        page.add(trouble)

        page.finish()
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
        self._config_box.setPlainText(
            CONFIG_SNIPPET.format(files_url=files_url, terminal_url=terminal_url)
        )

        self._load_skills()

    def _open_skills_folder(self) -> None:
        root = skills_module.skills_root()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(root)))

    def _pack_skill(self, folder: str = "") -> None:
        """Zip one skill folder into Downloads, ready for an upload form."""
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        if not folder:
            folder = QFileDialog.getExistingDirectory(
                self, "Choose a skill folder", str(skills_module.skills_root())
            )
        if not folder:
            return
        downloads = Path.home() / "Downloads"
        target_dir = downloads if downloads.is_dir() else Path.home()
        try:
            archive = skills_module.pack(folder, target_dir)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Could not pack the skill", str(exc))
            return
        box = QMessageBox(self)
        box.setWindowTitle("Skill packed")
        box.setText(f"Saved {archive.name} ({archive.stat().st_size / 1024:.0f} KB) to {archive.parent}.")
        box.setInformativeText(
            "Notion: Library > Skills > More ways to add a skill > Upload skill."
        )
        show = box.addButton("Show in folder", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if box.clickedButton() is show:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(archive.parent)))

    # --- skills list -----------------------------------------------------

    def _pick_scope(self, key: str) -> None:
        if key == "folder":
            from PySide6.QtWidgets import QFileDialog

            start = self._scope_folder or str(Path.home())
            folder = QFileDialog.getExistingDirectory(self, "Choose a project folder", start)
            if not folder:
                self._scope_picker.set_value(self._scope)
                return
            self._scope_folder = folder
        self.set_skill_scope(key, self._scope_folder)

    def set_skill_scope(self, scope: str, folder: str = "") -> None:
        """Show the global skills ("global"), or add a project's view
        ("active" project or any "folder")."""
        self._scope = scope if scope in ("global", "active", "folder") else "global"
        if self._scope == "folder":
            self._scope_folder = folder
        self._scope_picker.set_value(self._scope)
        self._load_skills()

    def _scope_project(self) -> tuple:
        """(title, folder) of the project being shown; folder "" = none."""
        if self._scope == "folder" and self._scope_folder:
            return Path(self._scope_folder).name or self._scope_folder, self._scope_folder
        if self._scope == "active":
            try:
                project = projects_module.active_project()
            except projects_module.ProjectError as exc:
                return str(exc), ""
            return str(project.get("name") or project.get("root")), str(project.get("root") or "")
        return "", ""

    def _copy_button(self, path_to_file: str) -> QPushButton:
        from PySide6.QtCore import QTimer

        btn = button("Copy text", "secondary", "Copy the file to the clipboard")

        def handler() -> None:
            try:
                content = Path(path_to_file).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                btn.setText("Failed to read")
                return
            QGuiApplication.clipboard().setText(content)
            btn.setText("Copied")
            btn.setEnabled(False)
            QTimer.singleShot(1200, lambda: (btn.setText("Copy text"), btn.setEnabled(True)))

        btn.clicked.connect(handler)
        return btn

    @staticmethod
    def _open_button(path: str, text: str = "Open") -> QPushButton:
        btn = button(text, "ghost")
        btn.clicked.connect(
            lambda _checked=False, f=path: QDesktopServices.openUrl(QUrl.fromLocalFile(f))
        )
        return btn

    def _skill_row(self, skill: dict, indent: bool = False, note: str = "") -> SettingRow:
        description = skill.get("description") or f"Skill slug: {skill['slug']}"
        if note:
            description = note + " " + description
        row = SettingRow(skill["name"], description)
        if indent:
            row.layout().setContentsMargins(40, 9, 14, 9)
        row.add(self._open_button(skill["file"]))
        pack = button("Pack", "ghost", "Zip this skill into Downloads")
        pack.clicked.connect(lambda _checked=False, d=skill["dir"]: self._pack_skill(d))
        row.add(pack)
        row.add(self._copy_button(skill["file"]))
        return row

    def _toggle_group(self, name: str) -> None:
        if name in self._expanded:
            self._expanded.discard(name)
        else:
            self._expanded.add(name)
        self._load_skills()

    def _load_skills(self) -> None:
        title, folder = self._scope_project()
        found = skills_module.discover(folder or None)
        global_skills = [s for s in found if s["origin"] == "bridge"]
        project_skills = [s for s in found if s["origin"] != "bridge"]

        # --- scope line
        if self._scope == "global":
            self._scope_row.set_title("Global skills only")
            self._scope_row.set_description("What list_skills() shows without a project.")
        else:
            self._scope_row.set_title(title or "No folder chosen")
            self._scope_row.set_description(
                f"What list_skills(project=...) shows for {folder}." if folder else ""
            )

        # --- project: instruction files, then its own skills
        project = self._project_group
        project.clear_rows()
        project.setVisible(bool(folder))
        if folder:
            names = set()
            for s in global_skills:
                names.update((s["slug"].lower(), s["name"].lower()))
            instructions = skills_module.project_instructions(folder)
            project.set_title(f"Project: {title}")
            project.set_caption(
                "Instruction files are read first; project skills win over a "
                "global skill with the same name."
            )
            for path, size in instructions:
                shown = f"{size} B" if size < 1024 else f"{size / 1024:.1f} KB"
                row = SettingRow(path.name, f"Instructions - {shown}")
                row.add(self._open_button(str(path)))
                row.add(self._copy_button(str(path)))
                project.add_row(row)
            for s in project_skills:
                clash = s["slug"].lower() in names or s["name"].lower() in names
                project.add_row(self._skill_row(s, note="[overrides the global one]" if clash else ""))
            if not instructions and not project_skills:
                project.add_row(SettingRow(
                    "Nothing project-specific",
                    "No AGENTS.md / CLAUDE.md / GEMINI.md and no "
                    ".agents/skills/<name>/SKILL.md in this folder.",
                ))

        # --- global: top-level skills, then groups (closed until shown)
        group = self._skills_group
        group.clear_rows()
        own = [s for s in global_skills if not s.get("group")]
        grouped: dict = {}
        for s in global_skills:
            if s.get("group"):
                grouped.setdefault(s["group"], []).append(s)
        group.set_title(f"Global skills ({len(own) + sum(len(v) for v in grouped.values())})")
        group.set_caption("Hidden from agents: the bin/ folder." if global_skills else "")

        if not global_skills:
            group.add_row(SettingRow(
                "No skills found",
                f"Place skill folders (each with a SKILL.md) in {skills_module.skills_root()}",
            ))
            return

        for s in own:
            group.add_row(self._skill_row(s))
        root = skills_module.skills_root()
        for name in sorted(grouped, key=str.lower):
            members = grouped[name]
            is_open = name in self._expanded
            preview = ", ".join(m["slug"] for m in members[:4]) + (", ..." if len(members) > 4 else "")
            row = SettingRow(f"{name}/", f"Group of {len(members)}: {preview}")
            row.add(self._open_button(str(root / name)))
            toggle = button("Hide" if is_open else "Show", "secondary")
            toggle.clicked.connect(lambda _checked=False, n=name: self._toggle_group(n))
            row.add(toggle)
            group.add_row(row)
            if is_open:
                for member in members:
                    group.add_row(self._skill_row(member, indent=True))

    # --- lifecycle -------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        # Stop listening once the dialog goes away, otherwise the settings
        # store keeps a reference to a deleted widget.
        self._unsubscribe()
        super().closeEvent(event)
