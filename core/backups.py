"""Undo history for file changes.

Every destructive file operation copies the previous state aside before
touching anything, and appends one line to an append-only journal. That
makes "put it back the way it was" a normal operation instead of a rescue
mission, which matters a lot when the agent edits the wrong file.

Design decisions, all chosen for safety over cleverness:

* Append-only journal. Undoing does not rewrite history; it appends an
  "undo" record. A crash mid-way can never corrupt earlier entries.
* The backup is taken before the change, and the resulting file is
  fingerprinted after it. If the fingerprint no longer matches at undo
  time, someone else edited the file in the meantime, so the undo refuses
  unless it is forced. Silently discarding a human's work would be far
  worse than a failed undo.
* Everything lives inside the project, in .mcp-backups, so moving or
  deleting a project takes its history with it and nothing leaks between
  projects.
* Storage is plain copies of files, not diffs. Diffs would be smaller and
  much easier to get subtly wrong.
* Backups are never taken of files inside .mcp-backups itself, and files
  above a size limit are recorded as "too large to back up" rather than
  silently duplicating gigabytes.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path

from core import projects
from core.config import settings

DIR_NAME = ".mcp-backups"
JOURNAL_NAME = "journal.jsonl"
BLOBS_NAME = "blobs"

# Actions we can undo.
WRITE = "write"      # file created or fully overwritten
EDIT = "edit"        # snippet replaced
DELETE = "delete"    # file or directory removed
MOVE = "move"        # file or directory moved / renamed
UNDO = "undo"        # marker appended when an entry is rolled back


class BackupError(Exception):
    """Raised when a change cannot be recorded or undone."""


def _limit(name: str, fallback: int) -> int:
    return int(settings.get("limits", name, default=fallback) or fallback)


def is_enabled() -> bool:
    """Return True if file backups are enabled in settings."""
    return bool(settings.get("backups", "enabled", default=False))


def delete_backups(project_root: Path | str | None = None) -> tuple[bool, str]:
    """Delete .mcp-backups directory from the specified or active project root."""
    target_root = Path(project_root or projects.active_root()) / DIR_NAME
    if not target_root.exists():
        return True, "No .mcp-backups folder found in active project."
    try:
        shutil.rmtree(target_root)
        return True, f"Removed {DIR_NAME} from active project."
    except OSError as exc:
        return False, f"Failed to delete {DIR_NAME}: {exc}"


def root() -> Path:
    return projects.active_root() / DIR_NAME


def journal_path() -> Path:
    return root() / JOURNAL_NAME


def is_backup_path(path: Path) -> bool:
    """True for anything inside the backup folder of any project."""
    return DIR_NAME in Path(path).parts


def _fingerprint(path: Path) -> str:
    """Content hash of a file, or a marker for missing paths / directories."""
    if not path.exists():
        return "absent"
    if path.is_dir():
        return "dir"
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except OSError as exc:
        raise BackupError(str(exc)) from exc
    return digest.hexdigest()


def _store(path: Path, change_id: str) -> str:
    """Copy the current state of `path` aside. Returns the blob name."""
    if not path.exists():
        return ""
    blobs = root() / BLOBS_NAME
    blobs.mkdir(parents=True, exist_ok=True)

    if path.is_dir():
        target = blobs / (change_id + "__" + path.name)
        shutil.copytree(path, target, dirs_exist_ok=False)
        return target.name

    max_bytes = _limit("max_backup_bytes", 20_000_000)
    if path.stat().st_size > max_bytes:
        return ""
    target = blobs / (change_id + "__" + path.name)
    shutil.copy2(path, target)
    return target.name


def _append(record: dict) -> None:
    path = journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load() -> list:
    path = journal_path()
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                continue  # a torn line must not break the whole history
    return records


def record_before(action: str, path: Path, destination: Path | None = None) -> dict:
    """Snapshot the current state before a change. Returns a pending entry.

    Never raises for ordinary problems: a failed backup must not stop the
    user's actual work, it just means that change cannot be undone.
    """
    entry = {
        "id": uuid.uuid4().hex[:8],
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "path": str(path),
        "destination": str(destination) if destination else "",
        "existed": path.exists(),
        "was_dir": path.is_dir(),
        "blob": "",
        "note": "",
    }
    if not is_enabled():
        entry["note"] = "backups disabled in settings"
        return entry
    if is_backup_path(path):
        entry["note"] = "inside the backup folder, not tracked"
        return entry
    if action == MOVE:
        # A move is reversed by moving it back, so copying the whole tree
        # aside first would double the work for no benefit.
        entry["note"] = "reversed by moving it back"
        return entry
    try:
        entry["blob"] = _store(path, entry["id"])
        if entry["existed"] and not entry["blob"]:
            entry["note"] = "too large to back up"
    except (OSError, shutil.Error, BackupError) as exc:
        entry["note"] = "backup failed: " + str(exc)
    return entry


def record_after(entry: dict, summary: str = "") -> str:
    """Finish an entry after the change succeeded and write it down."""
    if not is_enabled() or entry.get("note") in (
        "inside the backup folder, not tracked",
        "backups disabled in settings",
    ):
        return ""
    try:
        result_path = Path(entry["destination"] or entry["path"])
        entry["result_fingerprint"] = _fingerprint(result_path)
    except BackupError:
        entry["result_fingerprint"] = ""
    entry["summary"] = summary
    try:
        _append(entry)
    except OSError:
        return ""
    _prune()
    return str(entry["id"])


def _prune() -> None:
    """Keep the history small: drop blobs older than the retention window."""
    max_age_days = _limit("backup_retention_days", 14)
    cutoff = time.time() - max_age_days * 86400
    blobs = root() / BLOBS_NAME
    if not blobs.is_dir():
        return
    for child in blobs.iterdir():
        try:
            if child.stat().st_mtime >= cutoff:
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink()
        except OSError:
            continue


def history(limit: int = 20) -> list:
    """Recent changes, newest first, with undone entries marked."""
    records = _load()
    undone = {r.get("target") for r in records if r.get("action") == UNDO}
    items = [r for r in records if r.get("action") != UNDO]
    for item in items:
        item["undone"] = item.get("id") in undone
    items.reverse()
    return items[: max(limit, 1)]


def find(change_id: str = "") -> dict:
    """Look up one change, or the most recent undoable one."""
    items = history(limit=500)
    if change_id:
        for item in items:
            if item.get("id") == change_id:
                return item
        raise BackupError("No change with id '" + change_id + "'.")
    for item in items:
        if not item.get("undone"):
            return item
    raise BackupError("There is nothing to undo in this project.")


def undo(change_id: str = "", force: bool = False) -> str:
    """Roll one change back. Returns a human readable description."""
    entry = find(change_id)
    if entry.get("undone"):
        raise BackupError("Change " + entry["id"] + " was already undone.")

    action = entry.get("action")
    path = Path(entry["path"])
    destination = Path(entry["destination"]) if entry.get("destination") else None
    blob_name = entry.get("blob") or ""
    blob = (root() / BLOBS_NAME / blob_name) if blob_name else None

    # Refuse to clobber work done after the change we are undoing.
    current = destination or path
    expected = entry.get("result_fingerprint") or ""
    if expected and not force:
        actual = _fingerprint(current)
        if actual != expected:
            raise BackupError(
                str(current) + " changed after that operation, so undoing it "
                "would discard newer work. Check the file, then pass force "
                "if you still want the old version back."
            )

    if action == MOVE:
        if destination is None:
            raise BackupError("Move entry has no destination recorded.")
        if not destination.exists():
            raise BackupError("Nothing at " + str(destination) + " to move back.")
        if path.exists() and not force:
            raise BackupError(str(path) + " exists again; not overwriting it.")
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(destination), str(path))
        result = "Moved " + str(destination) + " back to " + str(path)

    elif action in (WRITE, EDIT):
        if not entry.get("existed"):
            if path.exists():
                if path.is_dir():
                    raise BackupError(str(path) + " is a directory now; not removing it.")
                path.unlink()
            result = "Removed " + str(path) + " (it did not exist before)"
        else:
            if blob is None or not blob.exists():
                raise BackupError("The backup copy for this change is gone.")
            shutil.copy2(blob, path)
            result = "Restored the previous contents of " + str(path)

    elif action == DELETE:
        if blob is None or not blob.exists():
            raise BackupError("The backup copy for this change is gone.")
        if path.exists() and not force:
            raise BackupError(str(path) + " exists again; not overwriting it.")
        path.parent.mkdir(parents=True, exist_ok=True)
        if blob.is_dir():
            shutil.copytree(blob, path, dirs_exist_ok=force)
        else:
            shutil.copy2(blob, path)
        result = "Restored " + str(path)

    else:
        raise BackupError("Cannot undo action '" + str(action) + "'.")

    _append({
        "id": uuid.uuid4().hex[:8],
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": UNDO,
        "target": entry["id"],
        "summary": result,
    })
    return result
