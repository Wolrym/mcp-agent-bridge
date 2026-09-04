"""Discovery of coding skills stored as markdown files.

A skill is either a folder containing SKILL.md, or a single .md file. The
folder is re-scanned on every call so newly added skills appear with no
indexing step.

The root is resolved lazily rather than stored as an absolute path, so
renaming or moving the project folder does not break skill lookup.
"""
from __future__ import annotations

from pathlib import Path

from core.config import PROJECT_ROOT, settings


def default_root() -> Path:
    """Where skills live when the setting is left empty.

    Prefers the folder shipped with this project; falls back to a `skills`
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
    """Extract top-level `key: value` pairs from a YAML front matter block."""
    meta: dict = {}
    if not text.startswith("---"):
        return meta
    end = text.find("\n---", 3)
    if end == -1:
        return meta
    for raw in text[3:end].splitlines():
        line = raw.rstrip()
        if not line or line[0] in " \t#" or ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        meta[key.strip().lower()] = value
    return meta


def discover() -> list:
    """Return descriptors for every skill found under the skills root."""
    root = skills_root()
    if not root.is_dir():
        return []

    found = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if entry.name.startswith("."):
            continue

        skill_file: Path | None = None
        references: list = []
        slug = entry.name

        if entry.is_dir():
            candidate = entry / "SKILL.md"
            if candidate.is_file():
                skill_file = candidate
            else:
                markdown = sorted(entry.glob("*.md"))
                skill_file = markdown[0] if markdown else None
            reference_dir = entry / "references"
            if reference_dir.is_dir():
                references = [
                    str(p) for p in sorted(reference_dir.iterdir())
                    if not p.name.startswith(".")
                ]
        elif entry.suffix.lower() == ".md":
            skill_file = entry
            slug = entry.stem

        if skill_file is None:
            continue

        name, description = slug, ""
        try:
            meta = parse_front_matter(skill_file.read_text(encoding="utf-8")[:8192])
            name = meta.get("name") or slug
            description = meta.get("description", "")
        except OSError:
            pass

        found.append({
            "slug": slug,
            "name": name,
            "description": description,
            "file": str(skill_file),
            "references": references,
        })
    return found


def find(name: str) -> tuple:
    """Look up a skill by slug or name.

    Returns:
        A tuple of (skill or None, candidates). When the skill is None,
        `candidates` holds either the ambiguous matches or every known skill.
    """
    all_skills = discover()
    target = name.strip().lower()
    exact = [
        s for s in all_skills
        if s["slug"].lower() == target or s["name"].lower() == target
    ]
    matches = exact or [
        s for s in all_skills
        if target in s["slug"].lower() or target in s["name"].lower()
    ]
    if len(matches) == 1:
        return matches[0], []
    return None, (matches or all_skills)
