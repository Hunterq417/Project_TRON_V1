# app_index.py
import difflib
import json
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

_MEDIA_FOLDER_NAMES = ["Pictures", "Videos", "Desktop", "Documents"]

# Never indexed from the user folders. open_target fuzzy-matches at 0.65, so a
# misheard name — or text the model read off the screen — could otherwise
# os.startfile a script sitting on the Desktop. Shortcuts (.lnk) stay: those
# are how Desktop apps get opened.
_RUNNABLE = {".exe", ".bat", ".cmd", ".com", ".ps1", ".psm1", ".vbs", ".vbe",
             ".js", ".jse", ".wsf", ".wsh", ".msi", ".msp", ".scr", ".hta",
             ".reg", ".cpl", ".jar", ".py", ".pyw"}

_START_APPS_CACHE = None


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
            if path.is_file() and path.suffix.lower() not in _RUNNABLE:
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


def start_apps(refresh: bool = False) -> Dict[str, str]:
    """Every app Windows itself lists in Start: name -> AppUserModelID.

    The .lnk scan above cannot see Store/UWP apps, because they have no
    shortcut file anywhere — Calculator, Settings, Photos, Camera, Clock and
    the modern Paint and Notepad are all invisible to it. That is why asking to
    open the calculator failed. Get-StartApps is Windows' own list and covers
    both kinds, so it is the authoritative source.

    Cached: the PowerShell round trip costs about a second, and the set of
    installed apps does not change during a conversation."""
    global _START_APPS_CACHE
    if _START_APPS_CACHE is not None and not refresh:
        return _START_APPS_CACHE

    apps: Dict[str, str] = {}
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=60,
            stdin=subprocess.DEVNULL, creationflags=0x08000000,
        ).stdout.strip()
        parsed = json.loads(out) if out else []
        if isinstance(parsed, dict):        # a single app comes back unwrapped
            parsed = [parsed]
        for entry in parsed:
            name, app_id = entry.get("Name"), entry.get("AppID")
            if name and app_id:
                apps[name.lower()] = app_id
    except Exception:
        # A missing app list must not stop the .lnk index from working.
        return {}

    _START_APPS_CACHE = apps
    return apps


def launch_start_app(app_id: str) -> None:
    """Launch by AppUserModelID. explorer.exe is the only launcher that
    understands shell:AppsFolder, which is how UWP apps are started."""
    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"])


def resolve_start_app(query: str, apps: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Fuzzy-match a spoken name against Windows' app list. Exact and prefix
    matches win before fuzzy ones, so "calculator" is never talked into being
    "Calendar"."""
    apps = start_apps() if apps is None else apps
    if not apps:
        return None
    wanted = query.lower().strip()
    if not wanted:
        return None     # "".startswith matches everything: launched a random app
    if wanted in apps:
        return apps[wanted]
    for name, app_id in apps.items():
        if name.startswith(wanted):
            return app_id
    # Substring before fuzzy: people say "store" for "Microsoft Store" and
    # "word" for "Word (Microsoft 365)". Shortest name wins so "store" prefers
    # Microsoft Store over some longer app that merely contains the word.
    contained = sorted((name for name in apps if wanted in name), key=len)
    if contained:
        return apps[contained[0]]
    matches = difflib.get_close_matches(wanted, apps.keys(), n=1, cutoff=0.7)
    return apps[matches[0]] if matches else None


def sound_key(text: str) -> str:
    """How a name sounds, roughly: letters only, vowels and y/w dropped, doubled letters merged. Speech
    recognition hears "Claude" as "cloud" - different spelling, same consonants (c-l-d)."""
    import re
    key = re.sub(r"[^a-z]", "", text.lower())
    key = key.replace("ph", "f").replace("ck", "k").replace("q", "k")
    key = re.sub(r"[aeiouyw]", "", key)
    return re.sub(r"(.)+", r"", key)


def sounds_like(query: str, names) -> list:
    """Names that sound like the spoken query, closest first: [(name, how sure 0..1)]. Tries the whole query
    and its leading words, so "cloud code" can find "Claude" ("cloud" ~ "claude")."""
    words = query.lower().split()
    tries = [" ".join(words[:n]) for n in range(len(words), 0, -1)]
    best = {}
    for name in names:
        key = sound_key(name)
        first = sound_key(name.split()[0]) if name.split() else key
        for i, part in enumerate(tries):
            pk = sound_key(part)
            if len(pk) < 2:
                continue
            ratio = max(difflib.SequenceMatcher(None, pk, key).ratio(), difflib.SequenceMatcher(None, pk, first).ratio())
            ratio -= 0.1 * i          # every dropped word makes it a bit less sure
            if ratio > best.get(name, 0):
                best[name] = ratio
    return sorted(((n, round(r, 2)) for n, r in best.items() if r >= 0.6), key=lambda x: -x[1])


def try_direct_launch(name: str) -> bool:
    """Attempts to launch `name` directly via the OS — handles built-in Windows
    utilities (notepad, calc, mspaint, control, explorer, ...) that Windows resolves
    via PATH/App Paths without ever appearing as a Start Menu .lnk shortcut. Returns
    True on success; False (never raises) if Windows can't resolve the bare name."""
    # A bare name only. This is the last-resort path with no index behind it,
    # so a path or URL here would launch whatever the model was told to.
    if not name.strip() or any(c in name for c in "\\/:"):
        return False
    try:
        os.startfile(name)
        return True
    except OSError:
        return False


def launch(path: Path) -> None:
    os.startfile(str(path))
