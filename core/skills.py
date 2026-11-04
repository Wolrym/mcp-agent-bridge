"""Discovery of skills: folders with a SKILL.md, in the open Agent Skills layout.

Where skills come from:

* the bridge's own skills folder. A folder with a SKILL.md is a skill; a
  folder without one whose subfolders have SKILL.md files is a group
  (for example `skills/design/impeccable`). Groups keep big third-party
  collections from flooding every list_skills reply;
* optionally a project's own skills, in the places coding agents look:
  `.agents/skills`, `.claude/skills` and `.opencode/skills`.

Everything is re-scanned on every call, so new skills appear with no
indexing step. The root is resolved lazily rather than stored as an
absolute path, so moving the app folder does not break skill lookup.
"""
from __future__ import annotations

from pathlib import Path

from core.config import PROJECT_ROOT, settings

SKILL_FILE = "SKILL.md"
PROJECT_SKILL_DIRS = (".agents/skills", ".claude/skills", ".opencode/skills", ".opencode/skill")
MAX_BUNDLED = 40
_NOISE = {".git", "__pycache__", "node_modules", ".DS_Store"}


def default_root() -> Path:
    """Where skills live when the setting is left empty.

    Prefers the folder shipped with this app; falls back to a `skills`
    folder next to it, which is where the older gateway kept them.
    """
    local = PROJECT_ROOT / "skills"
    if local.is_dir():
        return local
    legacy = PROJECT_ROOT.parent / "skills"
    return legacy if legacy.is_dir() else local


def skills_root() -> Path:
    configured = str(settings.get("skills_root", default="") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return default_root()


def parse_front_matter(text: str) -> dict:
    """Extract top-level keys from a YAML front matter block.

    Handles plain and quoted values plus `>` / `|` block scalars, which is
    how long skill descriptions are usually written. Not a YAML parser.
    """
    meta: dict = {}
    if not text.startswith("---"):
        return meta
    end = text.find("\n---", 3)
    if end == -1:
        return meta
    lines = text[3:end].splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        index += 1
        if not line or line[0] in " \t#" or ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if value[:1] in (">", "|"):
            block = []
            while index < len(lines) and (not lines[index].strip() or lines[index][:1] in " \t"):
                block.append(lines[index].strip())
                index += 1
            joiner = " " if value[:1] == ">" else "\n"
            value = joiner.join(part for part in block if part).strip()
        elif len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        meta[key.strip().lower()] = value
    return meta


def _skill(folder: Path, group: str, origin: str) -> dict | None:
    skill_file = folder / SKILL_FILE
    if not skill_file.is_file():
        return None
    name, description = folder.name, ""
    try:
        meta = parse_front_matter(skill_file.read_text(encoding="utf-8", errors="replace")[:16384])
        name = meta.get("name") or folder.name
        description = meta.get("description", "")
    except OSError:
        pass
    return {
        "slug": folder.name,
        "name": name,
        "description": description,
        "group": group,
        "origin": origin,
        "dir": str(folder),
        "file": str(skill_file),
    }


def _children(folder: Path) -> list:
    try:
        return sorted(
            (p for p in folder.iterdir() if p.is_dir() and not p.name.startswith(".")),
            key=lambda p: p.name.lower(),
        )
    except OSError:
        return []


def _scan(root: Path, origin: str, allow_groups: bool) -> list:
    found = []
    for entry in _children(root):
        skill = _skill(entry, "", origin)
        if skill:
            found.append(skill)
            continue
        if allow_groups:
            for child in _children(entry):
                member = _skill(child, entry.name, origin)
                if member:
                    found.append(member)
    return found


def project_roots(project: str | Path | None) -> list:
    if not project:
        return []
    base = Path(project).expanduser()
    return [base / rel for rel in PROJECT_SKILL_DIRS if (base / rel).is_dir()]


def discover(project: str | Path | None = None) -> list:
    """Every skill: the bridge's own (with groups), then the project's."""
    found = []
    root = skills_root()
    if root.is_dir():
        found += _scan(root, "bridge", allow_groups=True)
    for extra in project_roots(project):
        found += _scan(extra, "project", allow_groups=False)
    return found


def qualified(skill: dict) -> str:
    return f"{skill['group']}/{skill['slug']}" if skill["group"] else skill["slug"]


def describe(skill: dict, width: int = 220) -> str:
    text = " ".join(skill["description"].split())
    if len(text) > width:
        text = text[: width - 3] + "..."
    label = qualified(skill)
    return f"- {label}: {text}" if text else f"- {label}"


def find(name: str, project: str | Path | None = None) -> tuple:
    """Look up a skill by slug, name or group/slug.

    Returns:
        (skill or None, candidates). When the skill is None, `candidates`
        holds either the ambiguous matches or every known skill.
    """
    all_skills = discover(project)
    target = name.strip().strip("/").lower()
    keys = lambda s: (s["slug"].lower(), s["name"].lower(), qualified(s).lower())  # noqa: E731
    exact = [s for s in all_skills if target in keys(s)]
    if len(exact) > 1:
        # The same name in the project and in the bridge: the project wins.
        local = [s for s in exact if s["origin"] == "project"]
        exact = local if len(local) == 1 else exact
    matches = exact or [s for s in all_skills if any(target in k for k in keys(s))]
    if len(matches) == 1:
        return matches[0], []
    return None, (matches or all_skills)


def bundled_files(skill: dict) -> list:
    """Files shipped with a skill besides SKILL.md, relative to its folder."""
    folder = Path(skill["dir"])
    found = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.name == SKILL_FILE and path.parent == folder:
            continue
        if any(part in _NOISE for part in path.relative_to(folder).parts):
            continue
        found.append(str(path.relative_to(folder)))
        if len(found) >= MAX_BUNDLED:
            found.append("... (more files not listed)")
            break
    return found
