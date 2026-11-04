"""Accident guard for agent shell commands.

This is not a security boundary. Anyone holding the token can run any
code, and a determined command can always be phrased so that no pattern
catches it - keeping strangers out is the token's job. The guard exists
to stop a confused agent from doing something catastrophic, or from
cutting its own connection by killing this app or the tunnel.

Switch it off with `security.block_dangerous_commands: false`.
"""
from __future__ import annotations

import os
import re

from core.config import settings

# Start of a command: line start, after a chaining operator, a bracket or
# an opening quote (powershell -Command "..."). Keeps commit messages that
# merely mention "shutdown" from tripping the rule.
_AT = r"(?:^|[&|;(\"']\s*)"

_RULES = [
    (_AT + r"format(?:\.com)?\s+[a-z]:", "formats a drive"),
    (_AT + r"diskpart\b", "edits disk partitions"),
    (_AT + r"(?:bcdedit|bootrec)\b", "changes the boot configuration"),
    (_AT + r"vssadmin\b.*\bdelete\b", "deletes shadow copies"),
    (_AT + r"wbadmin\b.*\bdelete\b", "deletes system backups"),
    (_AT + r"cipher\b.*\s/w", "wipes free disk space"),
    (_AT + r"(?:shutdown(?:\.exe)?|restart-computer|stop-computer)\b",
     "shuts down or restarts the PC"),
    (_AT + r"reg(?:\.exe)?\s+delete\s+\"?hklm", "deletes machine-wide registry keys"),
    (_AT + r"(?:rd|rmdir)\b[^&|]*\s/s\b[^&|]*\s\"?[a-z]:\\?\"?\s*(?:$|[&|])",
     "deletes a whole drive"),
    (_AT + r"del\b[^&|]*\s/s\b[^&|]*\s\"?[a-z]:\\\*?(?:\.\*)?\"?\s*(?:$|[&|])",
     "deletes everything on a drive"),
    (r"remove-item\b[^;|]*-recurse[^;|]*\s\"?[a-z]:\\\*?\"?\s*(?:$|[;|\"])",
     "deletes a whole drive"),
    # Self-protection: the agent talks to this PC through these processes.
    (_AT + r"taskkill\b[^&|]*/im\s+\"?(?:python|pythonw|py|cloudflared)(?:\.exe)?\b",
     "kills this bridge or its tunnel, which would cut the agent's own connection"),
    (r"(?:stop-process|spps|kill)\b[^;|]*-name\s+\"?(?:python|pythonw|py|cloudflared)\b",
     "kills this bridge or its tunnel, which would cut the agent's own connection"),
    (r"get-process\b[^;|]*\b(?:python|pythonw|py|cloudflared)\b[^;]*\|\s*(?:stop-process|spps|kill)\b",
     "kills this bridge or its tunnel, which would cut the agent's own connection"),
    (_AT + r"wmic\b[^&|]*(?:python|cloudflared)[^&|]*\bdelete\b",
     "kills this bridge or its tunnel, which would cut the agent's own connection"),
    (r"cloudflared\b[^&|]*\btunnel\b[^&|]*\b(?:delete|cleanup)\b",
     "deletes the Cloudflare tunnel"),
]
_COMPILED = [(re.compile(rule, re.IGNORECASE), why) for rule, why in _RULES]


def enabled() -> bool:
    return bool(settings.get("security", "block_dangerous_commands", default=True))


def check(command: str) -> str:
    """Return why `command` is blocked, or "" when it may run."""
    if not enabled():
        return ""
    text = " ".join(command.split())
    for pattern, why in _COMPILED:
        if pattern.search(text):
            return _refusal(why)
    own = {os.getpid(), os.getppid()}
    for match in re.finditer(r"/pid\s+(\d+)|-id\s+(\d+)", text, re.IGNORECASE):
        pid = int(match.group(1) or match.group(2))
        if pid in own:
            return _refusal("stops the process this bridge runs in")
    return ""


def _refusal(why: str) -> str:
    return (
        f"blocked by the bridge's safety guard: this command {why}. "
        "If it is really intended, ask the user to run it themselves."
    )
