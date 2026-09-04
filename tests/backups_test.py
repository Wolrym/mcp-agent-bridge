"""Checks for the undo history and for paged reads.

Undo touches real files, so it gets a real test rather than a hopeful
read-through. Everything happens in a scratch folder inside the active
project, which is removed at the end.

    python tests\\backups_test.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import backups, projects  # noqa: E402
from servers.tools_files import _page  # noqa: E402

failures = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "ok  " if condition else "FAIL"
    print(status, name, ("- " + detail) if detail and not condition else "")
    if not condition:
        failures.append(name)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def change(action: str, path: Path, apply, destination: Path | None = None) -> str:
    """Do what a file tool does: snapshot, act, record."""
    entry = backups.record_before(action, path, destination=destination)
    apply()
    return backups.record_after(entry, action + " " + str(path))


def main() -> int:
    scratch = projects.active_root() / "_undo_scratch"
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True)

    target = scratch / "note.txt"

    # 1. Overwrite, then undo -> old contents come back.
    write(target, "first\n")
    change(backups.WRITE, target, lambda: write(target, "second\n"))
    backups.undo()
    check("overwrite is reverted", target.read_text(encoding="utf-8") == "first\n")

    # 2. Creating a new file, undone, removes it again.
    created = scratch / "fresh.txt"
    change(backups.WRITE, created, lambda: write(created, "hello\n"))
    backups.undo()
    check("created file is removed", not created.exists())

    # 3. Undo refuses when the file moved on since the change.
    change(backups.EDIT, target, lambda: write(target, "edited\n"))
    write(target, "edited by hand\n")
    refused = False
    try:
        backups.undo()
    except backups.BackupError:
        refused = True
    check("refuses to discard newer work", refused)
    check("file untouched after refusal",
          target.read_text(encoding="utf-8") == "edited by hand\n")

    # 4. ...but force gets the old version back.
    backups.undo(force=True)
    check("force restores the old version",
          target.read_text(encoding="utf-8") == "first\n")

    # 5. Delete, then undo -> file is back with its contents.
    change(backups.DELETE, target, target.unlink)
    check("file is gone after delete", not target.exists())
    backups.undo()
    check("deleted file is restored",
          target.exists() and target.read_text(encoding="utf-8") == "first\n")

    # 6. Move, then undo -> back at the original path.
    moved = scratch / "renamed.txt"
    change(backups.MOVE, target, lambda: shutil.move(str(target), str(moved)), destination=moved)
    backups.undo()
    check("move is reverted", target.exists() and not moved.exists())

    # 7. Undoing twice is refused, and history reflects it.
    twice_refused = False
    try:
        backups.undo(change_id=backups.history(limit=1)[0]["id"])
    except backups.BackupError:
        twice_refused = True
    check("an undone change cannot be undone again", twice_refused)

    # 8. Paged reads.
    body = "\n".join("line " + str(n) for n in range(1, 51))
    whole = _page(body, Path("x.txt"), 0, 0)
    check("short file is returned whole", whole == body)

    part = _page(body, Path("x.txt"), 1, 10)
    check("first page has a header", part.startswith("[x.txt: lines 1-10 of 50]"))
    check("first page stops at the budget", "line 10" in part and "line 11" not in part)
    check("first page says how to continue", "offset=11" in part)

    tail = _page(body, Path("x.txt"), 45, 10)
    check("last page has no continuation", "truncated" not in tail and "line 50" in tail)

    past = _page(body, Path("x.txt"), 500, 10)
    check("offset past the end is explained", "past the end" in past)

    shutil.rmtree(scratch, ignore_errors=True)

    print()
    if failures:
        print(str(len(failures)) + " failed:", ", ".join(failures))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
