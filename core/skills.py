"""Discovery of skills: folders with a SKILL.md, in the open Agent Skills layout.

Where global skills come from, all under the skills root (`skills/`):

* `core/` - the bridge's own skills (mcp-coding-agent-v2 and friends);
* `.agents/skills/` - skills installed with Vercel's skills CLI. Run
  `npx skills add <owner/repo> -a universal` inside the skills root: the
  CLI treats that folder as a project and puts every skill into
  `.agents/skills/<name>`, writing `skills-lock.json` next to it, so
  `npx skills list / update / remove` keep working there unchanged;
* any other folder in the root, the older layout: a folder with a SKILL.md
  is a skill, a folder of skill folders is a group (`design/impeccable`).

On a name clash `core/` wins over an installed copy, so an update of a
third-party collection cannot replace the bridge's own instructions.

Groups keep big collections from flooding every list_skills reply. Skills
installed by the CLI must stay flat (the CLI owns that folder), so they are
grouped with an optional sidecar file, `skills/categories.json`:
`{"design": ["frontend-design", "impeccable"]}` - a category behaves
exactly like a folder group.

Optionally a project's own skills are added, from the places coding agents
look: `.agents/skills` (the shared standard), `.agent/skills`,
`.claude/skills` and `.opencode/skills`. Like Claude Code, OpenCode and
Antigravity, the bridge lists both scopes together; on a name clash the
project's skill wins, because it is the more specific one.

`skills/bin/` is a parking spot: skills kept there are never listed or
loaded, so a folder can be switched off without deleting it.

A project's instruction files (AGENTS.md, CLAUDE.md, GEMINI.md) are not
skills, but they are found here too, so one list_skills(project=...) call
tells an agent everything it should read before touching the project.

Everything is re-scanned on every call, so new skills appear with no
indexing step. The root is resolved lazily rather than stored as an
absolute path, so moving the app folder does not break skill lookup.
"""
from __future__ import annotations

from pathlib import Path

from core.config import PROJECT_ROOT, settings

SKILL_FILE = "SKILL.md"
PROJECT_SKILL_DIRS = (
    ".agents/skills", ".agent/skills", ".claude/skills", ".opencode/skills", ".opencode/skill",
)
INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")
CORE_DIR = "core"  # the bridge's own skills
INSTALLED_DIR = ".agents/skills"  # where `npx skills add` puts skills
CATEGORIES_FILE = "categories.json"
INSTALL_COMMAND = "npx skills add <owner/repo> -a universal"
HIDDEN = {"bin", CORE_DIR}  # never scanned as old-layout folders
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


def _skill(folder: Path, group: str, origin: str, source: str = "") -> dict | None:
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
        "source": source or origin,
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


def _scan(root: Path, origin: str, allow_groups: bool, source: str = "") -> list:
    found = []
    for entry in _children(root):
        if allow_groups and entry.name.lower() in HIDDEN:
            continue
        skill = _skill(entry, "", origin, source)
        if skill:
            found.append(skill)
            continue
        if allow_groups:
            for child in _children(entry):
                member = _skill(child, entry.name, origin, source)
                if member:
                    found.append(member)
    return found


def project_roots(project: str | Path | None) -> list:
    if not project:
        return []
    base = Path(project).expanduser()
    return [base / rel for rel in PROJECT_SKILL_DIRS if (base / rel).is_dir()]


def project_instructions(project: str | Path | None) -> list:
    """The project's agent instruction files, as (path, size in bytes)."""
    if not project:
        return []
    base = Path(project).expanduser()
    found = []
    for name in INSTRUCTION_FILES:
        path = base / name
        if path.is_file():
            try:
                found.append((path, path.stat().st_size))
            except OSError:
                continue
    return found


def categories_path() -> Path:
    return skills_root() / CATEGORIES_FILE


def load_categories() -> dict:
    """{skill name or slug (lower case): category} from categories.json.

    A broken or missing file means no categories; it never breaks listing.
    """
    import json

    try:
        data = json.loads(categories_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    mapping = {}
    if isinstance(data, dict):
        for category, members in data.items():
            if str(category).startswith("_") or not isinstance(members, list):
                continue  # "_comment" and similar keys
            for member in members:
                mapping.setdefault(str(member).strip().lower(), str(category).strip())
    return mapping


def ensure_categories_file() -> Path:
    """Create an example categories.json if there is none; return its path."""
    import json

    path = categories_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        example = {
            "_comment": "Category -> skill names. Listed skills are shown as one "
                        "collapsed group, like a folder group. Folders stay as they are.",
            "design": [],
        }
        path.write_text(json.dumps(example, indent=2) + "\n", encoding="utf-8")
    return path


def global_skills() -> list:
    """The bridge's skills: core/, then installed, then the old layout."""
    root = skills_root()
    if not root.is_dir():
        return []
    found = _scan(root / CORE_DIR, "bridge", allow_groups=False, source="core")
    taken = {s["slug"].lower() for s in found} | {s["name"].lower() for s in found}
    for skill in _scan(root / INSTALLED_DIR, "bridge", allow_groups=False, source="installed"):
        if skill["slug"].lower() in taken or skill["name"].lower() in taken:
            continue  # core/ wins: an update must not replace our own skill
        found.append(skill)
    found += _scan(root, "bridge", allow_groups=True, source="folder")
    categories = load_categories()
    if categories:
        for skill in found:
            if not skill["group"]:
                skill["group"] = categories.get(skill["slug"].lower()) or categories.get(
                    skill["name"].lower(), ""
                )
    return found


def discover(project: str | Path | None = None) -> list:
    """Every skill: the bridge's own (with groups), then the project's."""
    found = global_skills()
    for extra in project_roots(project):
        found += _scan(extra, "project", allow_groups=False)
    return found


def group_folder(name: str) -> Path:
    """What to open for a group: its folder, or categories.json for a category."""
    folder = skills_root() / name
    return folder if folder.is_dir() else categories_path()


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


def _add_folder(archive, source: Path) -> None:
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if not path.is_file() or any(part in _NOISE for part in relative.parts):
            continue
        archive.write(path, (Path(source.name) / relative).as_posix())


def _skill_folder(folder: str | Path) -> Path:
    source = Path(folder).expanduser().resolve()
    if not (source / SKILL_FILE).is_file():
        raise ValueError(f"{source} has no {SKILL_FILE}, so it is not a skill folder")
    return source


def pack(folder: str | Path, destination: str | Path) -> Path:
    """Zip one skill folder for uploading elsewhere (Notion, claude.ai, ...).

    The archive holds the folder itself (`<name>/SKILL.md`, `<name>/...`),
    which is the layout skill uploaders expect. Caches and VCS folders are
    left out. Returns the written path.
    """
    import zipfile

    source = _skill_folder(folder)
    target = Path(destination).expanduser()
    if target.is_dir():
        target = target / f"{source.name}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        _add_folder(archive, source)
    return target


def export(folders: list, destination: str | Path, separate: bool = False) -> list:
    """Export several skills at once. Returns the written zip paths.

    * separate=False: one zip with a `<name>/` folder per skill - unpack it
      into any `.agents/skills` (or another skills folder) to install them all;
    * separate=True: one zip per skill, for upload forms that take one skill
      at a time (Notion, claude.ai).

    `destination` is a folder; for a single combined zip it may also be a
    .zip path.
    """
    import time
    import zipfile

    sources = [_skill_folder(f) for f in folders]
    if not sources:
        raise ValueError("no skills chosen")
    names = [s.name.lower() for s in sources]
    clashes = sorted({n for n in names if names.count(n) > 1})
    if clashes and not separate:
        raise ValueError("two chosen skills share a folder name: " + ", ".join(clashes))
    target = Path(destination).expanduser()
    if separate or len(sources) == 1:
        target.mkdir(parents=True, exist_ok=True)
        return [pack(s, target) for s in sources]
    if target.suffix.lower() != ".zip":
        target.mkdir(parents=True, exist_ok=True)
        target = target / f"skills-{time.strftime('%Y%m%d-%H%M')}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for source in sources:
            _add_folder(archive, source)
    return [target]
