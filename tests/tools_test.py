"""Behaviour checks for the MCP tools, called through FastMCP itself.

Runs against a throwaway project folder and a throwaway settings file, so
it never touches real work or the real token. No ports are opened.

    python tests\\tools_test.py

Covered: results are sent once (no structured duplicate), line endings
and BOMs survive edits, non-UTF-8 files are refused instead of mangled,
long lines are clipped, images come back as images, pack/unpack round
trips and refuses zip-slip, the settings file is protected, run_command
backgrounds slow commands instead of killing them, wait_process returns
early on a match, the accident guard, the event loop stays free, skills
with groups and project folders.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEMP = Path(tempfile.mkdtemp(prefix="mcp-tools-"))
PROJECT = TEMP / "project"
SKILLS = TEMP / "skills"
PROJECT.mkdir()
# Inside the project on purpose: the settings guard, not the project
# boundary, has to be what stops an agent from overwriting it.
SETTINGS = PROJECT / "config" / "settings.json"
SETTINGS.parent.mkdir()
SETTINGS.write_text(json.dumps({
    "auth": {"enabled": True, "token": "tools-test"},
    "projects": [{"id": "t", "name": "t", "root": str(PROJECT), "selected_at": None}],
    "active_project_id": "t",
    "skills_root": str(SKILLS),
    "backups": {"enabled": True},
    "notifications": {"enabled": False},
}), encoding="utf-8")
os.environ["MCP_SETTINGS_PATH"] = str(SETTINGS)

from core import guard, jobs  # noqa: E402
from servers import files_server, terminal_server  # noqa: E402

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
failures: list = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(("ok   " if condition else "FAIL ") + label + (f"  ({detail})" if detail else ""))
    if not condition:
        failures.append(label)


def py(code: str) -> str:
    """One-line python command that survives cmd.exe quoting."""
    return '"' + sys.executable + '" -c "' + code + '"'


FILES = files_server.build_mcp()
TERM = terminal_server.build_mcp()


def call(mcp, tool: str, /, **arguments):
    """Call a tool the way a client would; return text, or the raw blocks."""
    blocks = asyncio.run(mcp.call_tool(tool, arguments))
    if isinstance(blocks, tuple):  # (content, structured) = structured output on
        return blocks
    texts = [b.text for b in blocks if getattr(b, "type", "") == "text"]
    return "\n".join(texts) if len(texts) == len(blocks) else blocks


def test_single_copy_results() -> None:
    for mcp in (FILES, TERM):
        tools = asyncio.run(mcp.list_tools())
        doubled = [t.name for t in tools if getattr(t, "outputSchema", None)]
        check(f"{mcp.name}: no tool sends a structured duplicate", not doubled, ", ".join(doubled))
    result = call(FILES, "get_file_info", path=str(PROJECT))
    check("a tool result is plain text", isinstance(result, str), type(result).__name__)


def test_line_endings() -> None:
    crlf = PROJECT / "crlf.txt"
    crlf.write_bytes(b"one\r\ntwo\r\nthree\r\n")
    call(FILES, "edit_file", path=str(crlf), old_string="two", new_string="TWO\nand a half")
    data = crlf.read_bytes()
    check("edit keeps CRLF", data == b"one\r\nTWO\r\nand a half\r\nthree\r\n", repr(data))
    check("and never writes \\r\\r\\n", b"\r\r\n" not in data)

    call(FILES, "write_file", path=str(crlf), content="a\nb\n")
    check("overwrite keeps CRLF", crlf.read_bytes() == b"a\r\nb\r\n", repr(crlf.read_bytes()))

    lf = PROJECT / "new_lf.txt"
    call(FILES, "write_file", path=str(lf), content="x\ny\n")
    check("a new file gets exactly the sent bytes", lf.read_bytes() == b"x\ny\n", repr(lf.read_bytes()))

    bom = PROJECT / "bom.txt"
    bom.write_bytes(b"\xef\xbb\xbfhello\n")
    call(FILES, "edit_file", path=str(bom), old_string="hello", new_string="hi")
    check("edit keeps the UTF-8 BOM", bom.read_bytes() == b"\xef\xbb\xbfhi\n", repr(bom.read_bytes()))


def test_non_utf8_refused() -> None:
    legacy = PROJECT / "cp1251.txt"
    original = "привіт світ\n".encode("cp1251")
    legacy.write_bytes(original)
    result = call(FILES, "edit_file", path=str(legacy), old_string="?", new_string="!")
    check("editing a non-UTF-8 file is refused", str(result).startswith("Error"), str(result)[:80])
    check("and the file is untouched", legacy.read_bytes() == original)


def test_undo() -> None:
    target = PROJECT / "undo.txt"
    target.write_bytes(b"before\n")
    call(FILES, "edit_file", path=str(target), old_string="before", new_string="after")
    result = call(FILES, "undo_change")
    check("undo restores the previous bytes", target.read_bytes() == b"before\n", str(result)[:80])


def test_reading() -> None:
    long_line = PROJECT / "minified.js"
    long_line.write_text("x" * 50000, encoding="utf-8")
    text = call(FILES, "read_file", path=str(long_line))
    check("a huge single line is clipped", len(text) < 5000, f"{len(text)} chars")

    picture = PROJECT / "dot.png"
    picture.write_bytes(PNG_1PX)
    blocks = call(FILES, "read_file", path=str(picture))
    kinds = [getattr(b, "type", "") for b in blocks] if isinstance(blocks, list) else [type(blocks).__name__]
    check("a PNG comes back as an image", kinds == ["image"], str(kinds))

    many = PROJECT / "many"
    many.mkdir()
    for i in range(320):
        (many / f"f{i:03}.txt").write_text("x", encoding="utf-8")
    listing = call(FILES, "list_directory", path=str(many))
    check("list_directory is capped", "more entries not shown" in listing)


def test_pack_unpack() -> None:
    source = PROJECT / "bundle"
    (source / "sub").mkdir(parents=True)
    (source / "sub" / "dot.png").write_bytes(PNG_1PX)
    (source / "notes.txt").write_bytes(b"line\r\n")
    packed = call(FILES, "pack_files", paths_to_pack=[str(source)])
    check("pack_files returns a marked block", "-----BEGIN BASE64 ZIP-----" in packed)

    out = PROJECT / "unpacked"
    result = call(FILES, "unpack_files", data=packed, destination=str(out))
    same = (out / "bundle" / "sub" / "dot.png").read_bytes() == PNG_1PX and \
        (out / "bundle" / "notes.txt").read_bytes() == b"line\r\n"
    check("unpack_files restores the exact bytes", same, str(result)[:80])

    again = call(FILES, "unpack_files", data=packed, destination=str(out))
    check("existing files are not replaced without overwrite", again.startswith("Error"), again[:60])

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../escape.txt", "nope")
    evil = base64.b64encode(buffer.getvalue()).decode()
    refused = call(FILES, "unpack_files", data=evil, destination=str(out))
    check("zip-slip paths are refused", refused.startswith("Error") and not (PROJECT / "escape.txt").exists())


def test_settings_protected() -> None:
    before = SETTINGS.read_bytes()
    result = call(FILES, "write_file", path=str(SETTINGS), content="{}")
    check("settings.json cannot be overwritten by an agent", str(result).startswith("Error"), str(result)[:80])
    check("and it is unchanged", SETTINGS.read_bytes() == before)


def test_run_command() -> None:
    quick = call(TERM, "run_command", command=py("print('hi')"), cwd=str(PROJECT))
    check("a quick command returns its output", "exit code: 0" in quick and "hi" in quick, quick[-80:])
    check("and leaves no job behind", jobs.registry.running_count() == 0)

    cyrillic = call(TERM, "run_command", command=py("print('\\u043f\\u0440\\u0438\\u0432\\u0456\\u0442')"), cwd=str(PROJECT))
    check("non-ASCII output is decoded", "привіт" in cyrillic, cyrillic[-60:])

    started = time.time()
    slow = call(TERM, "run_command", command=py("import time; time.sleep(6); print('done')"),
                cwd=str(PROJECT), timeout=2)
    waited = time.time() - started
    check("a slow command returns after the timeout", waited < 5, f"{waited:.1f}s")
    check("and says it keeps running", "left running in the background" in slow, slow[:120])
    job_id = slow.split("as job ", 1)[-1].split(" ", 1)[0]
    finished = call(TERM, "wait_process", job_id=job_id, seconds=30)
    check("wait_process sees it finish", "exit code: 0" in finished and "done" in finished, finished[:120])
    call(TERM, "stop_process", job_id=job_id)


def test_wait_until() -> None:
    started_text = call(TERM, "start_process", cwd=str(PROJECT), command=py(
        "import time; print('booting', flush=True); time.sleep(1); "
        "print('server ready on 8000', flush=True); time.sleep(40)"))
    job_id = started_text.split("Started job ", 1)[-1].split(" ", 1)[0]
    started = time.time()
    report = call(TERM, "wait_process", job_id=job_id, seconds=30, until="ready")
    waited = time.time() - started
    check("wait_process returns as soon as until matches", waited < 10, f"{waited:.1f}s")
    check("and says it matched", "matched until=" in report and "server ready" in report, report[:120])
    tail = call(TERM, "get_output", job_id=job_id, tail=1)
    body = tail.split("--- output ---", 1)[-1]
    check("get_output tail returns the last line", "server ready" in body and "booting" not in body, body[:80])
    stopped = call(TERM, "stop_process", job_id=job_id)
    check("stop_process stops it", "Stopped job" in stopped, stopped[:80])


def test_guard() -> None:
    blocked = [
        "format c:", "diskpart", "taskkill /f /im python.exe", "taskkill /IM pythonw.exe /F",
        'powershell -Command "Stop-Process -Name python"', "cloudflared tunnel delete x",
        "rd /s /q C:\\", "shutdown /s /t 0", "cd x && format d: /q",
    ]
    allowed = [
        "git status", "python -m pytest", "taskkill /pid 12345 /f", "echo format is fine",
        "rd /s /q build", "npm run format", "git log --format=%H", "taskkill /im node.exe /f",
    ]
    missed = [c for c in blocked if not guard.check(c)]
    wrong = [c for c in allowed if guard.check(c)]
    check("the guard blocks wrecking commands", not missed, "; ".join(missed))
    check("and lets normal ones through", not wrong, "; ".join(wrong))

    original = guard.check
    guard.check = lambda command: "blocked for the test" if "GUARD_PROBE" in command else ""
    try:
        result = call(TERM, "run_command", command="echo GUARD_PROBE", cwd=str(PROJECT))
        check("run_command honours the guard", result.startswith("Error: blocked"), result[:60])
        result = call(TERM, "start_process", command="echo GUARD_PROBE", cwd=str(PROJECT))
        check("start_process honours the guard", result.startswith("Error: blocked"), result[:60])
    finally:
        guard.check = original


def test_loop_stays_free() -> None:
    async def scenario() -> int:
        ticks = 0

        async def tick() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0.05)
                ticks += 1

        ticker = asyncio.create_task(tick())
        big = PROJECT / "big.txt"
        big.write_text("needle\n" * 200000, encoding="utf-8")
        await asyncio.gather(
            TERM.call_tool("run_command", {"command": py("import time; time.sleep(1.5)"),
                                           "cwd": str(PROJECT)}),
            FILES.call_tool("grep", {"pattern": "needle", "path": str(PROJECT)}),
        )
        ticker.cancel()
        return ticks

    ticks = asyncio.run(scenario())
    check("other calls keep running during a command and a grep", ticks > 10, f"{ticks} ticks")


def test_skills() -> None:
    def skill(folder: Path, name: str, description: str) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n---\n# {name}\nbody\n", encoding="utf-8"
        )

    skill(SKILLS / "core-one", "core-one", "The main skill.")
    skill(SKILLS / "design" / "pretty", "pretty", ">-\n  Folded\n  description.")
    skill(SKILLS / "design" / "tidy", "tidy", "Tidy UI.")
    (SKILLS / "design" / "pretty" / "references").mkdir()
    (SKILLS / "design" / "pretty" / "references" / "a.md").write_text("ref", encoding="utf-8")
    skill(PROJECT / ".agents" / "skills" / "local", "local", "Project skill.")

    listing = call(TERM, "list_skills")
    check("top-level skills are listed", "core-one" in listing)
    check("groups are collapsed to one line", "design/" in listing and "Tidy UI." not in listing, listing[:200])
    group = call(TERM, "list_skills", group="design")
    check("a group lists its skills", "Folded description." in group and "Tidy UI." in group, group[:200])
    body = call(TERM, "get_skill", name="design/pretty")
    check("get_skill finds a grouped skill with its files", "references" in body and "body" in body)
    local = call(TERM, "get_skill", name="local", project=str(PROJECT))
    check("project skills are found", "Project skill." in local or "# local" in local, local[:120])

    # bin/ parks skills: never listed, never loaded.
    skill(SKILLS / "bin" / "parked", "parked", "Switched off.")
    listing = call(TERM, "list_skills")
    check("bin/ is hidden from the list", "parked" not in listing and "bin/" not in listing, listing[:300])
    check("bin/ skills cannot be loaded", "Switched off." not in call(TERM, "get_skill", name="parked"))
    check("without project there is a hint", "project=" in listing)

    # Both scopes together, instruction files, the project wins a clash.
    skill(PROJECT / ".agents" / "skills" / "core-one", "core-one", "Project flavour.")
    skill(PROJECT / ".agent" / "skills" / "older", "older", "Antigravity folder.")
    (PROJECT / "AGENTS.md").write_text("# rules\nuse tabs\n", encoding="utf-8")
    both = call(TERM, "list_skills", project=str(PROJECT))
    check("global and project skills in one list", "The main skill." in both and "Project skill." in both, both[:400])
    check("instruction files are listed", "AGENTS.md" in both and "CLAUDE.md (" not in both, both[-400:])
    check("an override is marked", "overrides the global one" in both, both[-400:])
    check(".agent/skills is read too", "Antigravity folder." in both)
    clash = call(TERM, "get_skill", name="core-one", project=str(PROJECT))
    check("the project skill wins a name clash", "Project flavour." in clash, clash[:200])

    # Packing for upload: the folder itself goes into the zip.
    from core import skills as skills_module

    archive = skills_module.pack(SKILLS / "design" / "pretty", TEMP)
    with zipfile.ZipFile(archive) as packed:
        names = sorted(packed.namelist())
    check("pack keeps the folder layout", names == ["pretty/SKILL.md", "pretty/references/a.md"], str(names))


def main() -> int:
    tests = [
        test_single_copy_results, test_line_endings, test_non_utf8_refused, test_undo,
        test_reading, test_pack_unpack, test_settings_protected, test_run_command,
        test_wait_until, test_guard, test_loop_stays_free, test_skills,
    ]
    for test in tests:
        print(f"\n[{test.__name__}]")
        try:
            test()
        except Exception as exc:  # noqa: BLE001
            check(f"{test.__name__} ran without crashing", False, repr(exc))
    jobs.registry.stop_all()
    print()
    if failures:
        print(f"{len(failures)} check(s) failed: " + ", ".join(failures))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
