"""Export dialog: pick skills, write one zip or one zip per skill.

One zip holds a `<name>/` folder per skill - unpack it into any
`.agents/skills` folder to install them all at once. One zip per skill
suits upload forms that take a single skill (Notion, claude.ai).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core import skills as skills_module
from gui.widgets.primitives import Segmented, button
from gui.widgets.tokens import COLORS


def downloads_folder() -> Path:
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else Path.home()


class SkillExportDialog(QDialog):
    def __init__(self, found: list, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export skills")
        # The theme keeps QDialog transparent for frameless windows; this
        # one is a native window, so it paints its own page background.
        self.setObjectName("skillExport")
        self.setStyleSheet(
            f"QDialog#skillExport {{ background-color: {COLORS['shell']}; }}"
            "QCheckBox { spacing: 8px; padding: 3px 0; }"
            f"QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 4px;"
            f" border: 1px solid {COLORS['prim_edge']}; background: transparent; }}"
            f"QCheckBox::indicator:checked {{ background: {COLORS['accent']};"
            f" border-color: {COLORS['accent']}; }}"
        )
        self.resize(520, 560)
        self.written: list = []
        self._boxes: list = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        intro = QLabel(
            "Choose skills to export into Downloads. One zip: a folder per skill, "
            "unpack it into any .agents/skills. One zip per skill: for upload "
            "forms (Skills > Upload skill)."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        top = QHBoxLayout()
        all_btn = button("Select all", "ghost")
        all_btn.clicked.connect(lambda: self._set_all(True))
        none_btn = button("Select none", "ghost")
        none_btn.clicked.connect(lambda: self._set_all(False))
        top.addWidget(all_btn)
        top.addWidget(none_btn)
        top.addStretch(1)
        self.mode = Segmented([("one", "One zip"), ("separate", "Zip per skill")], "one")
        top.addWidget(self.mode)
        layout.addLayout(top)

        holder = QWidget()
        rows = QVBoxLayout(holder)
        rows.setContentsMargins(4, 4, 4, 4)
        rows.setSpacing(4)
        for skill in sorted(found, key=lambda s: (s["origin"] != "bridge", skills_module.qualified(s).lower())):
            where = {"installed": "installed", "core": "core", "project": "project"}.get(
                skill.get("source", ""), skill.get("group") or "folder"
            )
            text = f"{skills_module.qualified(skill)}   ({where})"
            box = QCheckBox(text)
            box.setProperty("skill_dir", skill["dir"])
            box.toggled.connect(self._update)
            rows.addWidget(box)
            self._boxes.append(box)
        rows.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        layout.addWidget(scroll, 1)

        bottom = QHBoxLayout()
        self.status = QLabel("")
        bottom.addWidget(self.status, 1)
        cancel = button("Cancel", "ghost")
        cancel.clicked.connect(self.reject)
        self.export_btn = button("Export", "default")
        self.export_btn.clicked.connect(self._export)
        bottom.addWidget(cancel)
        bottom.addWidget(self.export_btn)
        layout.addLayout(bottom)
        self._update()

    def chosen(self) -> list:
        return [b.property("skill_dir") for b in self._boxes if b.isChecked()]

    def _set_all(self, checked: bool) -> None:
        for box in self._boxes:
            box.setChecked(checked)

    def _update(self, *_args) -> None:
        count = len(self.chosen())
        self.status.setText(f"{count} selected")
        self.export_btn.setEnabled(count > 0)

    def _export(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        try:
            self.written = skills_module.export(
                self.chosen(), downloads_folder(), separate=self.mode.value() == "separate"
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Could not export", str(exc))
            return
        self.accept()
