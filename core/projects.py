"""Project registry and the notion of an "active project".

Every tool call resolves paths against the active project, read at call
time, so switching projects in the GUI takes effect immediately without
restarting the servers.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from core import logs
from core.config import settings


class ProjectError(Exception):
    """Raised when a project cannot be found, added or activated."""


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "project"


def _unique_id(base: str, taken: set) -> str:
    if base not in taken:
        return base
    index = 2
    while f"{base}-{index}" in taken:
        index += 1
    return f"{base}-{index}"


def list_projects() -> list:
    """Return every registered project."""
    return list(settings.get("projects", default=[]) or [])


def active_project() -> dict:
    """Return the currently active project.

    Raises:
        ProjectError: if the registry is empty or the active id is dangling.
    """
    projects = list_projects()
    if not projects:
        raise ProjectError(
            "No project is configured. Add one in the control panel."
        )
    active_id = settings.get("active_project_id")
    for project in projects:
        if project["id"] == active_id:
            return project
    raise ProjectError(
        "No active project is selected. Choose one in the control panel."
    )


def active_root() -> Path:
    """Return the absolute root directory of the active project."""
    return Path(active_project()["root"]).resolve()


def add_project(root: str, name: str = "") -> dict:
    """Register a folder as a project.

    Args:
        root: Absolute path to the project folder. It must already exist.
        name: Display name. Defaults to the folder name.
    """
    path = Path(root).expanduser()
    if not path.is_absolute():
        raise ProjectError(f"Project root must be an absolute path: {root}")
    path = path.resolve()
    if not path.is_dir():
        raise ProjectError(f"Project root does not exist: {path}")

    existing = list_projects()
    for project in existing:
        if Path(project["root"]).resolve() == path:
            return project

    label = name.strip() or path.name
    project = {
        "id": _unique_id(_slugify(label), {p["id"] for p in existing}),
        "name": label,
        "root": str(path),
        "selected_at": None,
    }

    def mutate(draft: dict) -> None:
        draft["projects"].append(project)

    settings.update(mutate)
    logs.log("projects", f"Added project '{project['name']}' at {path}")
    return project


def remove_project(project_id: str) -> None:
    """Unregister a project. The folder itself is never touched."""
    if not any(p["id"] == project_id for p in list_projects()):
        raise ProjectError(f"Unknown project: {project_id}")

    def mutate(draft: dict) -> None:
        draft["projects"] = [p for p in draft["projects"] if p["id"] != project_id]
        if draft.get("active_project_id") == project_id:
            draft["active_project_id"] = None

    settings.update(mutate)
    logs.log("projects", f"Removed project '{project_id}'")


def set_active_project(project_id: str) -> dict:
    """Switch the active project. Takes effect on the next tool call."""
    if not any(p["id"] == project_id for p in list_projects()):
        raise ProjectError(f"Unknown project: {project_id}")

    stamp = time.time()

    def mutate(draft: dict) -> None:
        draft["active_project_id"] = project_id
        for project in draft["projects"]:
            if project["id"] == project_id:
                project["selected_at"] = stamp

    settings.update(mutate)
    project = active_project()
    logs.log("projects", f"Active project switched to '{project['name']}'")
    return project
