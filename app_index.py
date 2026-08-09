# app_index.py
import difflib
import os
from pathlib import Path
from typing import Dict, List, Optional

_MEDIA_FOLDER_NAMES = ["Pictures", "Videos", "Desktop", "Documents"]


def _default_startmenu_dirs() -> List[Path]:
    dirs = []
    for env_var in ("PROGRAMDATA", "APPDATA"):
        base = os.environ.get(env_var)
        if base:
            dirs.append(Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return dirs


def build_index(
    startmenu_dirs: Optional[List[Path]] = None,
    home: Optional[Path] = None,
) -> Dict[str, Path]:
    """Scans Start Menu shortcuts and common user folders into a name -> path index."""
    startmenu_dirs = startmenu_dirs if startmenu_dirs is not None else _default_startmenu_dirs()
    home = home if home is not None else Path.home()

    index: Dict[str, Path] = {}

    for base in startmenu_dirs:
        if not base.exists():
            continue
        for path in base.rglob("*.lnk"):
            index[path.stem.lower()] = path

    for folder_name in _MEDIA_FOLDER_NAMES:
        folder = home / folder_name
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            if path.is_file():
                index[path.stem.lower()] = path

    return index


def resolve(query: str, index: Dict[str, Path]) -> Optional[Path]:
    """Fuzzy-matches a spoken name against the index. Returns the best match or None.
    cutoff=0.65 (not the more permissive 0.5) because a wrong-but-plausible match
    (e.g. "notepad" -> "OneNote.lnk") is worse than an honest "couldn't find it" —
    better to fall through to try_direct_launch or a clear failure than guess."""
    if not index:
        return None
    matches = difflib.get_close_matches(query.lower(), index.keys(), n=1, cutoff=0.65)
    return index[matches[0]] if matches else None


def try_direct_launch(name: str) -> bool:
    """Attempts to launch `name` directly via the OS — handles built-in Windows
    utilities (notepad, calc, mspaint, control, explorer, ...) that Windows resolves
    via PATH/App Paths without ever appearing as a Start Menu .lnk shortcut. Returns
    True on success; False (never raises) if Windows can't resolve the bare name."""
    try:
        os.startfile(name)
        return True
    except OSError:
        return False


def launch(path: Path) -> None:
    os.startfile(str(path))
