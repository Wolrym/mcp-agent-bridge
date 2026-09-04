"""Path resolution and sandboxing for every file and command tool.

Relative paths are resolved against the active project root, so an agent
can simply say "src/main.py" and stay inside the right project even after
the user switches projects in the GUI.
"""
from __future__ import annotations

from pathlib import Path

from core import projects
from core.config import settings


class PathError(Exception):
    """Raised when a path is unusable or outside the allowed root."""


def _allow_outside() -> bool:
    return bool(settings.get("security", "allow_outside_project", default=False))


def is_inside(root: Path, target: Path) -> bool:
    """Return True if `target` is `root` itself or lives under it."""
    try:
        target.relative_to(root)
    except ValueError:
        return False
    return True


def resolve(path: str | None, *, must_exist: bool = False) -> Path:
    """Resolve a user supplied path against the active project.

    Args:
        path: Absolute or project-relative path. Empty or None means the
            project root itself.
        must_exist: Fail if the resulting path does not exist.

    Raises:
        PathError: if the path escapes the project root while sandboxing is
            enabled, or if `must_exist` is set and nothing is there.
    """
    root = projects.active_root()
    candidate = Path(path).expanduser() if path else root
    if not candidate.is_absolute():
        candidate = root / candidate

    # resolve() also collapses any ".." segments, so the check below cannot
    # be bypassed with traversal.
    resolved = candidate.resolve()

    if not _allow_outside() and not is_inside(root, resolved):
        raise PathError(
            f"'{resolved}' is outside the active project root '{root}'. "
            "Switch project in the control panel, or enable access outside "
            "the project in the settings."
        )
    if must_exist and not resolved.exists():
        raise PathError(f"Path does not exist: {resolved}")
    return resolved


def display(path: Path) -> str:
    """Render a path relative to the project root when possible."""
    try:
        root = projects.active_root()
    except Exception:  # noqa: BLE001 - display must never fail
        return str(path)
    if is_inside(root, path):
        relative = path.relative_to(root)
        return str(relative) if str(relative) != "." else "."
    return str(path)
