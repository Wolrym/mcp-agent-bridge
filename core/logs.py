"""Application log: a ring buffer, live subscribers and optional sinks.

The servers log here instead of printing, so the GUI can show the same
stream without capturing stdout. Records are plain dicts to keep them
trivially serialisable.

Two optional sinks mirror every record:

* the console, for the debug launcher and the headless CLI;
* a size-rotated file under logs/, so a windowless panel still leaves a
  trail to read after something went wrong.
"""
from __future__ import annotations

import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable

MAX_RECORDS = 2000
FILE_MAX_BYTES = 1_000_000
FILE_KEEP = 3

_lock = threading.RLock()
_records: deque = deque(maxlen=MAX_RECORDS)
_subscribers: list = []
_console = False
_file: Path | None = None


def format_record(record: dict) -> str:
    """One aligned line: time, level, source, message."""
    stamp = time.strftime("%H:%M:%S", time.localtime(record["time"]))
    level = record.get("level", "info").upper()
    return f"{stamp}  {level:<5}  {record['source']:<8}  {record['message']}"


def log(source: str, message: str, level: str = "info", kind: str = "") -> dict:
    """Append a record and push it to every subscriber and sink.

    Args:
        source: Short origin tag, e.g. "files", "terminal", "tunnel".
        message: Human readable text.
        level: One of "debug", "info", "warn", "error".
        kind: Optional category; "call" marks one finished tool call.
    """
    record = {
        "time": time.time(),
        "source": source,
        "level": level,
        "message": message,
        "kind": kind,
    }
    with _lock:
        _records.append(record)
        listeners = list(_subscribers)
        _write_sinks(record)
    for listener in listeners:
        try:
            listener(record)
        except Exception:  # noqa: BLE001 - logging must never raise
            pass
    return record


def _write_sinks(record: dict) -> None:
    if not (_console or _file):
        return
    line = format_record(record)
    if _console and sys.stdout is not None:
        try:
            print(line, flush=True)
        except Exception:  # noqa: BLE001 - e.g. a closed or non-UTF-8 console
            pass
    if _file is not None:
        try:
            if _file.exists() and _file.stat().st_size > FILE_MAX_BYTES:
                _rotate(_file)
            with _file.open("a", encoding="utf-8") as fh:
                fh.write(time.strftime("%Y-%m-%d ", time.localtime(record["time"])) + line + "\n")
        except OSError:
            pass


def _rotate(path: Path) -> None:
    for index in range(FILE_KEEP - 1, 0, -1):
        older = path.with_name(f"{path.name}.{index}")
        if older.exists():
            newer = path.with_name(f"{path.name}.{index + 1}")
            older.replace(newer)
    path.replace(path.with_name(path.name + ".1"))


def enable_console() -> bool:
    """Mirror records to stdout. Returns False when there is no console."""
    global _console
    if sys.stdout is None:
        return False
    _console = True
    return True


def enable_file(path: Path) -> None:
    """Mirror records to `path`, rotating it at about a megabyte."""
    global _file
    path.parent.mkdir(parents=True, exist_ok=True)
    _file = path


def file_path() -> Path | None:
    return _file


def history(limit: int = MAX_RECORDS) -> list:
    """Return the most recent records, oldest first."""
    with _lock:
        items = list(_records)
    return items[-limit:]


def subscribe(listener: Callable[[dict], None]) -> Callable[[], None]:
    """Register a live log listener. Returns an unsubscribe callable."""
    with _lock:
        _subscribers.append(listener)

    def unsubscribe() -> None:
        with _lock:
            if listener in _subscribers:
                _subscribers.remove(listener)

    return unsubscribe


def clear() -> None:
    with _lock:
        _records.clear()
