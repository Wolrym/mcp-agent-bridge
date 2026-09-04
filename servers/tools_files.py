"""Files System MCP tools.

Everything that touches files lives here: listing, reading, writing,
editing, moving, deleting and searching. Paths are resolved against the
active project on every call, so switching projects needs no restart.

Two behaviours worth knowing about:

* Reads are paged. A long file comes back in one chunk of lines with a
  header saying which part you got and how to ask for the rest, instead of
  flooding the conversation.
* Changes are reversible. write_file, edit_file, move_file and delete_file
  snapshot the previous state first, so undo_change can put it back.
"""
from __future__ import annotations

import fnmatch
import os
import shutil
from datetime import datetime
from pathlib import Path

from core import backups, logs, paths, projects
from core.config import settings

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".idea", ".vscode", "dist", "build",
    backups.DIR_NAME,
}


def _limit(name: str, fallback: int) -> int:
    return int(settings.get("limits", name, default=fallback) or fallback)


def _error(exc: Exception) -> str:
    return f"Error: {exc}"


def _read_text(path: Path) -> str:
    max_bytes = _limit("max_read_bytes", 5_000_000)
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(
            f"File is {size} bytes, larger than the {max_bytes} byte limit. "
            "Read it in parts with a shell command instead."
        )
    return path.read_text(encoding="utf-8", errors="replace")


def _page(text: str, path: Path, offset: int, limit: int) -> str:
    """Return a slice of `text` by line, with a header when it is partial.

    Offsets are 1-based because every editor, traceback and grep result
    the agent will compare against counts lines that way.
    """
    lines = text.splitlines()
    total = len(lines)
    cap = limit if limit > 0 else _limit("max_read_lines", 900)
    start = max(offset, 1)

    if start > total and total:
        return (
            f"{path}: offset {start} is past the end of the file "
            f"({total} lines)."
        )

    chunk = lines[start - 1 : start - 1 + cap]
    end = start - 1 + len(chunk)
    body = "\n".join(chunk)

    partial = start > 1 or end < total
    if not partial:
        return text

    header = f"[{path}: lines {start}-{end} of {total}]"
    footer = ""
    if end < total:
        footer = (
            f"\n[truncated - continue with offset={end + 1}, "
            f"{total - end} lines left]"
        )
    return header + "\n" + body + footer


def _is_probably_binary(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return b"\0" in fh.read(4096)
    except OSError:
        return False


def _walk(root: Path):
    """Yield files under `root`, skipping noisy directories."""
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for filename in filenames:
            yield Path(current) / filename


def _undo_hint(change_id: str) -> str:
    return f" (undo id {change_id})" if change_id else ""


def register(mcp) -> None:
    """Attach every file tool to the given FastMCP instance."""

    @mcp.tool()
    def list_directory(path: str = ".") -> str:
        """List the files and folders inside a directory.

        Args:
            path: Directory to list, absolute or relative to the active
                project. Defaults to the project root.
        """
        try:
            target = paths.resolve(path, must_exist=True)
        except Exception as exc:  # noqa: BLE001
            return _error(exc)
        if not target.is_dir():
            return f"Error: not a directory: {target}"

        entries = []
        for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if child.is_dir():
                entries.append(f"[DIR ] {child.name}")
            else:
                try:
                    size = child.stat().st_size
                except OSError:
                    size = 0
                entries.append(f"[FILE] {child.name} ({size} bytes)")
        header = f"{target}"
        return header + "\n" + ("\n".join(entries) if entries else "(empty)")

    @mcp.tool()
    def read_file(path: str, offset: int = 0, limit: int = 0) -> str:
        """Read a text file, in parts when it is long.

        Short files come back whole. Longer ones are cut to a line budget
        and the result says which lines you got and where to continue.

        Args:
            path: File to read, absolute or relative to the active project.
            offset: First line to return, 1-based. 0 or 1 starts at the top.
            limit: How many lines to return. 0 uses the configured default.
        """
        try:
            target = paths.resolve(path, must_exist=True)
            if target.is_dir():
                return f"Error: '{target}' is a directory. Use list_directory."
            if _is_probably_binary(target):
                return f"Error: '{target}' looks like a binary file."
            return _page(_read_text(target), target, offset, limit)
        except Exception as exc:  # noqa: BLE001
            return _error(exc)

    @mcp.tool()
    def read_multiple_files(paths_to_read: list, limit: int = 0) -> str:
        """Read several text files in one call.

        Each file is paged the same way read_file pages a single one, so a
        batch of long files cannot blow up the reply.

        Args:
            paths_to_read: List of file paths, absolute or project-relative.
            limit: Line budget per file. 0 uses the configured default.
        """
        if not paths_to_read:
            return "Error: provide at least one path."
        chunks = []
        for raw in paths_to_read:
            try:
                target = paths.resolve(str(raw), must_exist=True)
                if _is_probably_binary(target):
                    body = "(binary file skipped)"
                else:
                    body = _page(_read_text(target), target, 1, limit)
                chunks.append(f"===== {target} =====\n{body}")
            except Exception as exc:  # noqa: BLE001
                chunks.append(f"===== {raw} =====\nError: {exc}")
        return "\n\n".join(chunks)

    @mcp.tool()
    def write_file(path: str, content: str) -> str:
        """Create a file or replace its entire contents.

        Use edit_file for changing part of an existing file. The previous
        contents are kept for undo_change.

        Args:
            path: File to write, absolute or relative to the active project.
            content: The full new contents of the file.
        """
        try:
            target = paths.resolve(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            existed = target.exists()
            entry = backups.record_before(backups.WRITE, target)
            target.write_text(content, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            return _error(exc)

        verb = "Overwrote" if existed else "Created"
        change_id = backups.record_after(entry, f"{verb} {target}")
        logs.log("files", f"{verb} {target}")
        return f"{verb} {target} ({len(content)} chars){_undo_hint(change_id)}"

    @mcp.tool()
    def edit_file(
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
        dry_run: bool = False,
    ) -> str:
        """Replace an exact snippet inside an existing file.

        The preferred way to change code: it fails loudly instead of
        silently rewriting the wrong place, and the previous version is
        kept for undo_change.

        Args:
            path: File to edit, absolute or relative to the active project.
            old_string: Exact text to find. Must be unique unless replace_all.
            new_string: Replacement text.
            replace_all: Replace every occurrence instead of requiring one.
            dry_run: Report what would change without writing.
        """
        if not old_string:
            return "Error: old_string must not be empty."
        try:
            target = paths.resolve(path, must_exist=True)
            original = _read_text(target)
        except Exception as exc:  # noqa: BLE001
            return _error(exc)

        occurrences = original.count(old_string)
        if occurrences == 0:
            return (
                "Error: old_string was not found. Read the file again and copy "
                "the snippet exactly, including whitespace and indentation."
            )
        if occurrences > 1 and not replace_all:
            return (
                f"Error: old_string appears {occurrences} times. Include more "
                "surrounding context to make it unique, or pass replace_all."
            )

        updated = original.replace(old_string, new_string)
        if dry_run:
            return (
                f"Dry run: would replace {occurrences} occurrence(s) in {target}. "
                f"Size {len(original)} -> {len(updated)} chars."
            )
        try:
            entry = backups.record_before(backups.EDIT, target)
            target.write_text(updated, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            return _error(exc)

        change_id = backups.record_after(
            entry, f"Edited {target} ({occurrences} replacement(s))"
        )
        logs.log("files", f"Edited {target} ({occurrences} replacement(s))")
        return (
            f"Replaced {occurrences} occurrence(s) in {target}."
            f"{_undo_hint(change_id)}"
        )

    @mcp.tool()
    def create_directory(path: str) -> str:
        """Create a directory, including any missing parents.

        Args:
            path: Directory to create, absolute or project-relative.
        """
        try:
            target = paths.resolve(path)
            target.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            return _error(exc)
        return f"Directory ready: {target}"

    @mcp.tool()
    def move_file(source: str, destination: str, overwrite: bool = False) -> str:
        """Move or rename a file or directory.

        Args:
            source: Existing path.
            destination: New path.
            overwrite: Allow replacing an existing destination.
        """
        try:
            src = paths.resolve(source, must_exist=True)
            dst = paths.resolve(destination)
            if dst.exists() and not overwrite:
                return f"Error: destination already exists: {dst}"
            dst.parent.mkdir(parents=True, exist_ok=True)
            entry = backups.record_before(backups.MOVE, src, destination=dst)
            shutil.move(str(src), str(dst))
        except Exception as exc:  # noqa: BLE001
            return _error(exc)

        change_id = backups.record_after(entry, f"Moved {src} -> {dst}")
        logs.log("files", f"Moved {src} -> {dst}")
        return f"Moved {src} -> {dst}{_undo_hint(change_id)}"

    @mcp.tool()
    def delete_file(path: str, recursive: bool = False) -> str:
        """Delete a file, or a directory when recursive is set.

        A copy is kept for undo_change, unless the target is larger than
        the backup size limit.

        Args:
            path: Path to remove.
            recursive: Required to delete a non-empty directory.
        """
        try:
            target = paths.resolve(path)
            if not target.exists() and not target.is_symlink():
                return f"Error: path does not exist: {target}"
            if target == projects.active_root():
                return "Error: refusing to delete the project root."

            if target.is_dir() and not target.is_symlink() and not recursive:
                try:
                    entry = backups.record_before(backups.DELETE, target)
                    target.rmdir()
                except OSError:
                    return (
                        f"Error: directory is not empty: {target}. "
                        "Pass recursive=true to delete it and its contents."
                    )
                result = f"Deleted empty directory: {target}"
            else:
                entry = backups.record_before(backups.DELETE, target)
                if target.is_dir() and not target.is_symlink():
                    shutil.rmtree(target)
                    result = f"Deleted directory and contents: {target}"
                else:
                    target.unlink()
                    result = f"Deleted file: {target}"
        except Exception as exc:  # noqa: BLE001
            return _error(exc)

        change_id = backups.record_after(entry, result)
        logs.log("files", result, level="warn")
        return result + _undo_hint(change_id)

    @mcp.tool()
    def list_changes(limit: int = 15) -> str:
        """Show recent file changes made through these tools, newest first.

        Args:
            limit: How many entries to show.
        """
        try:
            items = backups.history(limit=limit)
        except Exception as exc:  # noqa: BLE001
            return _error(exc)
        if not items:
            if not backups.is_enabled():
                return "File backups are disabled in settings (no recorded changes)."
            return "No recorded changes in this project yet."

        lines = []
        if not backups.is_enabled():
            lines.append("[Notice: File backups are currently disabled in settings]")
        for item in items:
            flag = " [undone]" if item.get("undone") else ""
            note = item.get("note") or ""
            lines.append(
                f"{item.get('id')}  {item.get('time')}  {item.get('action')}  "
                f"{item.get('summary') or item.get('path')}{flag}"
                + (f"  ({note})" if note else "")
            )
        return "\n".join(lines)

    @mcp.tool()
    def undo_change(change_id: str = "", force: bool = False) -> str:
        """Undo a file change recorded by these tools.

        Restores the previous contents of a written or edited file, brings
        back a deleted one, or moves a moved one back. Refuses when the
        file changed again afterwards, so newer work is not thrown away.

        Args:
            change_id: Id from list_changes. Empty undoes the most recent
                change that has not been undone yet.
            force: Undo even when the file changed after that operation.
        """
        if not backups.is_enabled() and not backups.root().exists():
            return "Error: File backups are disabled in settings and no undo history exists."
        try:
            result = backups.undo(change_id=change_id, force=force)
        except Exception as exc:  # noqa: BLE001
            return _error(exc)
        logs.log("files", "Undo: " + result, level="warn")
        return result

    @mcp.tool()
    def search_files(pattern: str, path: str = ".", max_results: int = 0) -> str:
        """Find files whose name matches a glob pattern.

        Args:
            pattern: Glob such as "*.py" or "test_*".
            path: Directory to search in. Defaults to the project root.
            max_results: Result cap. 0 uses the configured default.
        """
        if not pattern:
            return "Error: pattern is required."
        cap = max_results or _limit("max_results", 300)
        try:
            root = paths.resolve(path, must_exist=True)
        except Exception as exc:  # noqa: BLE001
            return _error(exc)

        hits = []
        for file in _walk(root):
            if fnmatch.fnmatch(file.name, pattern):
                hits.append(str(file))
                if len(hits) >= cap:
                    break
        if not hits:
            return f"No files matching '{pattern}' under {root}"
        header = f"{len(hits)} match(es) for '{pattern}' under {root}:"
        return header + "\n" + "\n".join(hits)

    @mcp.tool()
    def grep(
        pattern: str,
        path: str = ".",
        file_glob: str = "",
        ignore_case: bool = False,
        max_results: int = 0,
    ) -> str:
        """Search file contents for a regular expression.

        Args:
            pattern: Regular expression to look for.
            path: File or directory to search. Defaults to the project root.
            file_glob: Optional filename filter such as "*.py".
            ignore_case: Case-insensitive matching.
            max_results: Result cap. 0 uses the configured default.
        """
        import re

        if not pattern:
            return "Error: pattern is required."
        cap = max_results or _limit("max_results", 300)
        try:
            root = paths.resolve(path, must_exist=True)
            regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
        except Exception as exc:  # noqa: BLE001
            return _error(exc)

        candidates = [root] if root.is_file() else _walk(root)
        max_bytes = _limit("max_read_bytes", 5_000_000)
        hits = []
        truncated = False

        for file in candidates:
            if file_glob and not fnmatch.fnmatch(file.name, file_glob):
                continue
            try:
                if file.stat().st_size > max_bytes or _is_probably_binary(file):
                    continue
                with file.open("r", encoding="utf-8", errors="replace") as fh:
                    for number, line in enumerate(fh, start=1):
                        if regex.search(line):
                            hits.append(f"{file}:{number}: {line.rstrip()}")
                            if len(hits) >= cap:
                                truncated = True
                                break
            except OSError:
                continue
            if truncated:
                break

        if not hits:
            return f"No matches for '{pattern}' under {root}"
        header = f"{len(hits)} match(es) for '{pattern}' under {root}:"
        if truncated:
            header += f" (stopped at the {cap} result limit)"
        return header + "\n" + "\n".join(hits)

    @mcp.tool()
    def get_file_info(path: str) -> str:
        """Report size, type and timestamps for a file or directory.

        Args:
            path: Path to inspect.
        """
        try:
            target = paths.resolve(path, must_exist=True)
            info = target.stat()
        except Exception as exc:  # noqa: BLE001
            return _error(exc)

        def stamp(value: float) -> str:
            return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")

        kind = "directory" if target.is_dir() else "file"
        lines = [
            f"path: {target}",
            f"relative: {paths.display(target)}",
            f"type: {kind}",
            f"size: {info.st_size} bytes",
            f"modified: {stamp(info.st_mtime)}",
            f"created: {stamp(info.st_ctime)}",
        ]
        if target.is_dir():
            try:
                lines.append(f"entries: {len(list(target.iterdir()))}")
            except OSError:
                pass
        if not target.is_dir():
            try:
                text_lines = sum(1 for _ in target.open("r", encoding="utf-8", errors="replace"))
                lines.append(f"lines: {text_lines}")
            except OSError:
                pass
        return "\n".join(lines)
