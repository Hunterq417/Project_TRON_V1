# skills.py
"""Skills for TRON, in the same shape as Claude's: a folder holding a SKILL.md.

    skills/morning-routine/SKILL.md
    ---
    name: morning-routine
    description: What to do when the user says "start my morning" — open mail, calendar and news.
    ---
    1. open_target "Outlook"
    2. open_website "https://calendar.google.com"
    3. ... (any instructions, in plain words; TRON follows them with its tools)

Like Claude, TRON only carries each skill's name and description in its instructions; the full text is
loaded when a request matches one (the use_skill tool), so a hundred skills cost a hundred lines, not a
hundred pages. Skills are added from the control panel (Memory tab > Skills): a SKILL.md file, a folder
with one in it, or a .zip — including a skill downloaded or exported from Claude.
"""
import re
import shutil
import zipfile
from pathlib import Path

import config

_MAX_LISTED = 60
_MAX_SKILL_CHARS = 12000


def skills_dir() -> Path:
    return config.app_dir() / "skills"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "skill"


def parse(text: str) -> dict:
    """{"name", "description", "body"} from a SKILL.md, frontmatter optional."""
    meta, body = {}, text
    m = re.match(r"^\s*---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            key, sep, value = line.partition(":")
            if sep:
                meta[key.strip().lower()] = value.strip().strip("\"'")
        body = m.group(2)
    if "name" not in meta:
        heading = re.search(r"^#\s+(.+)$", body, re.M)
        meta["name"] = heading.group(1).strip() if heading else ""
    if "description" not in meta:
        first = next((l.strip() for l in body.splitlines() if l.strip() and not l.startswith("#")), "")
        meta["description"] = first[:200]
    return {"name": meta.get("name", ""), "description": meta.get("description", ""), "body": body.strip()}


def all_skills() -> list:
    """Every installed skill: {"id", "name", "description", "path"}, sorted by name."""
    out = []
    root = skills_dir()
    if not root.exists():
        return out
    for md in sorted(root.glob("*/SKILL.md")):
        try:
            info = parse(md.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        out.append({"id": md.parent.name, "name": info["name"] or md.parent.name,
                    "description": info["description"], "path": md.parent})
    return sorted(out, key=lambda s: s["name"].lower())


def install(source) -> str:
    """Installs a skill from a SKILL.md / any .md file, a folder containing SKILL.md, or a .zip. Returns its
    name. Raises ValueError with a sentence for the user when the source isn't a skill."""
    source = Path(source)
    root = skills_dir()
    root.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        md = next(iter(source.rglob("SKILL.md")), None)
        if md is None:
            raise ValueError("that folder has no SKILL.md in it")
        info = parse(md.read_text(encoding="utf-8", errors="replace"))
        target = root / _slug(info["name"] or md.parent.name)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(md.parent, target)
        return info["name"] or target.name
    if source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as archive:
            names = [n for n in archive.namelist() if n.endswith("SKILL.md")]
            if not names:
                raise ValueError("that zip has no SKILL.md in it")
            prefix = names[0][: -len("SKILL.md")]
            info = parse(archive.read(names[0]).decode("utf-8", errors="replace"))
            target = root / _slug(info["name"] or Path(prefix).name or source.stem)
            if target.exists():
                shutil.rmtree(target)
            for member in archive.namelist():
                if not member.startswith(prefix) or member.endswith("/"):
                    continue
                relative = Path(member[len(prefix):])
                if ".." in relative.parts:   # never write outside the skill's folder
                    continue
                out = target / relative
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(archive.read(member))
        return info["name"] or target.name
    if source.suffix.lower() in (".md", ".markdown", ".txt"):
        text = source.read_text(encoding="utf-8", errors="replace")
        info = parse(text)
        name = info["name"] or source.stem
        target = root / _slug(name)
        target.mkdir(parents=True, exist_ok=True)
        (target / "SKILL.md").write_text(text, encoding="utf-8")
        return name
    raise ValueError("a skill is a SKILL.md file, a folder with one in it, or a .zip")


def remove(skill_id: str) -> bool:
    target = skills_dir() / skill_id
    if target.is_dir() and target.parent == skills_dir():
        shutil.rmtree(target)
        return True
    return False


def context() -> str:
    """The skills block of TRON's instructions: names and descriptions only."""
    found = all_skills()[:_MAX_LISTED]
    if not found:
        return ""
    lines = [f"- {s['name']}: {s['description']}" for s in found]
    return ("Skills you have (call use_skill with the name to read one before following it, whenever a "
            "request matches its description):\n" + "\n".join(lines))


def use_skill(args, cfg=None) -> str:
    """Tool: the full instructions of one skill, plus the other files it ships with."""
    wanted = str(args.get("name", "")).strip().lower()
    found = all_skills()
    match = next((s for s in found if s["name"].lower() == wanted or s["id"] == _slug(wanted)), None)
    if match is None:
        names = ", ".join(s["name"] for s in found) or "none installed"
        return f'there is no skill called "{wanted}". Skills: {names}'
    body = parse((match["path"] / "SKILL.md").read_text(encoding="utf-8", errors="replace"))["body"]
    extras = [str(p.relative_to(match["path"])) for p in match["path"].rglob("*")
              if p.is_file() and p.name != "SKILL.md"]
    note = f"\n\n(Files in this skill: {', '.join(extras[:20])})" if extras else ""
    return f"SKILL {match['name']} — follow these instructions with your tools:\n\n{body[:_MAX_SKILL_CHARS]}{note}"


DECLARATION = {
    "name": "use_skill",
    "description": "Read the full instructions of one of your skills (listed in your instructions) before doing it.",
    "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
}

EXAMPLE = """---
name: morning-routine
description: When the user says "start my day" or "morning routine" - open mail, calendar and the news.
---
When the user asks to start their day:

1. Say "Good morning, sir. Setting up your day."
2. open_target "Outlook"
3. open_website "https://calendar.google.com"
4. open_website "https://news.google.com"
5. current_time, then tell them the time and that everything is open.
"""


def install_example() -> str:
    """A first skill to show the format, installed if there are none yet."""
    if all_skills():
        return ""
    target = skills_dir() / "morning-routine"
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(EXAMPLE, encoding="utf-8")
    return "morning-routine"
