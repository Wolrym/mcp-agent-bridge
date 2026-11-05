"""Checks how cloudflared output is turned into log lines.

Run it directly:

    python tests\\tunnel_lines_test.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.processes import tidy_line  # noqa: E402

CASES = [
    ("client hang-up is dropped",
     '2026-11-05T14:39:31Z ERR error="stream 161 canceled by remote with error code 0" connIndex=0 event=1',
     None),
    ("failed request after hang-up is dropped",
     '2026-11-05T14:39:31Z ERR Request failed error="stream 161 canceled by remote with error code 0" dest=https://x/mcp',
     None),
    ("context canceled is dropped",
     "2026-11-05T14:39:31Z ERR Incoming request ended abruptly: context canceled", None),
    ("real error is a warning without the prefix",
     '2026-11-05T14:39:31Z ERR Request failed error="dial tcp: refused" dest=https://x',
     ("warn", 'Request failed error="dial tcp: refused" dest=https://x')),
    ("diagnostics table is debug",
     "2026-11-05T14:32:36Z INF | DNS Resolution region1 PASS |", ("debug", "| DNS Resolution region1 PASS |")),
    ("failed precheck is a warning",
     '2026-11-05T14:32:36Z INF precheck component="UDP" status=fail',
     ("warn", 'precheck component="UDP" status=fail')),
    ("registered connection is short",
     "2026-11-05T14:32:36Z INF Registered tunnel connection connIndex=0 connection=27ba event=0 "
     "ip=198.41.192.77 location=tll01 protocol=quic",
     ("info", "Tunnel connection 1 registered (tll01, quic)")),
    ("fatal is an error", "2026-11-05T14:32:36Z FTL failed to start", ("error", "failed to start")),
    ("other lines pass through", "Starting tunnel", ("info", "Starting tunnel")),
    ("blank line is dropped", "   ", None),
]


def main() -> int:
    failures = []
    for name, line, expected in CASES:
        got = tidy_line(line)
        ok = got == expected
        print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  got {got!r}"))
        if not ok:
            failures.append(name)
    print("")
    print("FAILED: " + ", ".join(failures) if failures else "all checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
