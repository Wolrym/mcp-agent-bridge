r"""Zip a skill folder for uploading to another agent (Notion, claude.ai, ...).

    python tools\pack_skill.py mcp-coding-agent-v2
    python tools\pack_skill.py design/impeccable --out C:\Users\me\Desktop
    python tools\pack_skill.py C:\proj\.agents\skills\deploy
    python tools\pack_skill.py deploy --project C:\proj

The argument is a skill name (as list_skills shows it) or a skill folder.
The zip holds the folder itself (<name>/SKILL.md plus its files), which is
what skill uploaders expect. Default destination: your Downloads folder.
In Notion: Library -> Skills -> More ways to add a skill -> Upload skill.
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Zip a skill folder for upload.")
    parser.add_argument("skill", help="skill name, group/name, or a folder with a SKILL.md")
    parser.add_argument("--out", default="", help="folder or .zip path (default: Downloads)")
    parser.add_argument("--project", default="", help="project folder, to find its own skills")
    args = parser.parse_args()

    folder = Path(args.skill).expanduser()
    if not (folder / skills.SKILL_FILE).is_file():
        found, candidates = skills.find(args.skill, args.project or None)
        if found is None:
            names = ", ".join(sorted(skills.qualified(c) for c in candidates[:20]))
            print(f"No single skill matches '{args.skill}'. Close: {names}")
            return 1
        folder = Path(found["dir"])

    target = skills.pack(folder, Path(args.out).expanduser() if args.out else default_destination())
    print(f"{target}  ({target.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
