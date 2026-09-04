"""Application log: a ring buffer plus live subscribers.

The servers log here instead of printing, so the GUI can show the same
stream without capturing stdout. Records are plain dicts to keep them
trivially serialisable.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable

MAX_RECORDS = 2000

_lock = threading.RLock()
_records: deque = deque(maxlen=MAX_RECORDS)
_subscribers: list = []


def log(source: str, message: str, level: str = "info") -> dict:
    """Append a record and push it to every subscriber.

    Args:
        source: Short origin tag, e.g. "files", "terminal", "tunnel".
        message: Human readable text.
        level: One of "debug", "info", "warn", "error".
    """
    record = {
        "time": time.time(),
        "source": source,
        "level": level,
        "message": message,
    }
    with _lock:
        _records.append(record)
        listeners = list(_subscribers)
    for listener in listeners:
        try:
            listener(record)
        except Exception:  # noqa: BLE001 - logging must never raise
            pass
    return record


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
