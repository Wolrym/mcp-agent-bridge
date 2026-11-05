r"""Zip skills for uploading to another agent or installing elsewhere.

    python tools\pack_skill.py mcp-coding-agent-v2
    python tools\pack_skill.py design/impeccable --out C:\Users\me\Desktop
    python tools\pack_skill.py C:\proj\.agents\skills\deploy
    python tools\pack_skill.py deploy --project C:\proj
    python tools\pack_skill.py impeccable frontend-design        (one zip, both)
    python tools\pack_skill.py --all                             (every global skill)
    python tools\pack_skill.py --all --separate                  (one zip per skill)

Each argument is a skill name (as list_skills shows it) or a skill folder.
A zip holds the folders themselves (<name>/SKILL.md plus its files): one
skill per zip is what upload forms expect (Notion: Library -> Skills ->
More ways to add a skill -> Upload skill); a zip with several folders
unpacks straight into any .agents/skills. Default destination: Downloads.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import skills  # noqa: E402


def default_destination() -> Path:
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else Path.cwd()


def resolve(name: str, project: str) -> Path | None:
    folder = Path(name).expanduser()
    if (folder / skills.SKILL_FILE).is_file():
        return folder
    found, candidates = skills.find(name, project or None)
    if found is None:
        names = ", ".join(sorted(skills.qualified(c) for c in candidates[:20]))
        print(f"No single skill matches '{name}'. Close: {names}")
        return None
    return Path(found["dir"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Zip skill folders for upload or install.")
    parser.add_argument("skill", nargs="*", help="skill names, group/name, or folders with a SKILL.md")
    parser.add_argument("--all", action="store_true", help="every global skill (bin/ excluded)")
    parser.add_argument("--separate", action="store_true", help="one zip per skill")
    parser.add_argument("--out", default="", help="folder (or .zip path for one zip); default: Downloads")
    parser.add_argument("--project", default="", help="project folder, to find its own skills")
    args = parser.parse_args()

    if args.all:
        folders = [Path(s["dir"]) for s in skills.global_skills()]
    else:
        folders = [resolve(name, args.project) for name in args.skill]
        if None in folders:
            return 1
    if not folders:
        parser.error("name at least one skill, or pass --all")

    out = Path(args.out).expanduser() if args.out else default_destination()
    if len(folders) == 1 and not args.separate:
        written = [skills.pack(folders[0], out)]
    else:
        written = skills.export(folders, out, separate=args.separate)
    for target in written:
        print(f"{target}  ({target.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
