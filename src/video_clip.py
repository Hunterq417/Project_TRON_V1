# video_clip.py
"""Clip the video you're watching: "tron, clip this from 1:20 to 2:05".

Everything here is free and open source:

* The video's address is read straight out of the browser's address bar through Windows UI Automation —
  no keystrokes, no focus change, so the video keeps playing undisturbed.
* yt-dlp downloads only the requested section and ffmpeg cuts it cleanly at the exact times.

yt-dlp is the official standalone yt-dlp.exe, fetched into tools\\ on first use rather than frozen into
TRON's exe: YouTube changes often and an old yt-dlp stops working, so when a clip fails it updates itself
(yt-dlp -U) and tries once more. ffmpeg doesn't go stale, so it ships inside TRON (imageio-ffmpeg).
"""
import ctypes
import os
import shutil
import subprocess
import threading
import urllib.request
from pathlib import Path

import config

YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
BROWSERS = {"chrome", "msedge", "brave", "firefox", "opera", "vivaldi"}
# Best MP4 up to 1080p, so the clip plays anywhere without re-encoding
FORMAT = "bv*[ext=mp4][height<=1080]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"
_CREATE_NO_WINDOW = 0x08000000

# main.py points this at something that tells the user (tray notification, spoken if TRON is free).
on_finished = lambda message: None  # noqa: E731
_lock = threading.Lock()


def tools_dir() -> Path:
    return config.app_dir() / "tools"


def clips_dir() -> Path:
    return Path.home() / "Videos" / "TRON Clips"


def stamp(seconds: float) -> str:
    """75 -> '1:15', 3725 -> '1:02:05'."""
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# --------------------------------------------------------------------------- which video
def _address_bar(hwnd) -> str:
    """The URL in a browser window's address bar, read via UI Automation."""
    import comtypes.client
    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen import UIAutomationClient as uia_lib
    uia = comtypes.client.CreateObject("{ff48dba4-60ef-4201-aa87-54103eef594e}",
                                       interface=uia_lib.IUIAutomation)
    window = uia.ElementFromHandle(hwnd)
    edit = window.FindFirst(uia_lib.TreeScope_Descendants, uia.CreatePropertyCondition(
        uia_lib.UIA_ControlTypePropertyId, uia_lib.UIA_EditControlTypeId))
    return str(edit.GetCurrentPropertyValue(uia_lib.UIA_ValueValuePropertyId) or "") if edit else ""


def current_video():
    """(url, title) of the video in the browser you're looking at, or None.

    The window in front wins; otherwise the highest browser window (EnumWindows lists them top to bottom).
    When the address bar can't be read — a video in full screen hides it — a YouTube title is searched for
    instead, which finds the same video."""
    import desktop_control
    browsers = [(h, t) for h, t, p in desktop_control._open_windows() if p.lower().removesuffix(".exe") in BROWSERS]
    if not browsers:
        return None
    front = ctypes.windll.user32.GetForegroundWindow()
    browsers.sort(key=lambda w: w[0] != front)
    hwnd, title = browsers[0]
    page = title.rsplit(" - ", 1)[0]  # drop " - Google Chrome"
    page = page.split(" - YouTube")[0] if " - YouTube" in page else page
    if page[:1] == "(" and ") " in page:  # YouTube's "(3) " unread-notifications prefix
        page = page.split(") ", 1)[1]
    try:
        url = _address_bar(hwnd).strip()
    except Exception:
        url = ""
    if url and " " not in url and "." in url:
        return (url if url.startswith(("http://", "https://")) else "https://" + url), page
    if " - YouTube" in title:
        return f"ytsearch1:{page}", page
    return None


# --------------------------------------------------------------------------- the tools
def _ytdlp() -> Path:
    exe = tools_dir() / "yt-dlp.exe"
    if not exe.exists():
        tools_dir().mkdir(parents=True, exist_ok=True)
        part = exe.with_suffix(".part")
        urllib.request.urlretrieve(YTDLP_URL, part)
        part.replace(exe)
    return exe


def _ffmpeg_dir() -> Path:
    """A folder holding ffmpeg.exe, which is what yt-dlp looks for by name."""
    target = tools_dir() / "ffmpeg.exe"
    if not target.exists():
        import imageio_ffmpeg
        tools_dir().mkdir(parents=True, exist_ok=True)
        shutil.copy(imageio_ffmpeg.get_ffmpeg_exe(), target)
    return tools_dir()


def _run_ytdlp(url: str, start: float, end: float) -> str:
    """Downloads the section, returns the saved file's path."""
    clips_dir().mkdir(parents=True, exist_ok=True)
    name = f"%(title).80s [{stamp(start).replace(':', '-')} to {stamp(end).replace(':', '-')}].%(ext)s"
    ffmpeg = _ffmpeg_dir()
    env = {**os.environ, "PATH": f"{ffmpeg}{os.pathsep}{os.environ.get('PATH', '')}"}
    cmd = [str(_ytdlp()), url, "--no-playlist", "-f", FORMAT, "--merge-output-format", "mp4",
           "--download-sections", f"*{start:.2f}-{end:.2f}", "--force-keyframes-at-cuts",
           "--ffmpeg-location", str(ffmpeg), "-o", str(clips_dir() / name),
           "--print", "after_move:filepath", "--no-progress", "--encoding", "utf-8"]
    done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=30 * 60, env=env, stdin=subprocess.DEVNULL, creationflags=_CREATE_NO_WINDOW)
    path = done.stdout.strip().splitlines()[-1] if done.stdout.strip() else ""
    if done.returncode or not path or not Path(path).exists():
        error = next((line for line in done.stderr.splitlines() if "ERROR" in line), done.stderr.strip()[-300:])
        raise RuntimeError(error or "yt-dlp failed")
    return path


def _duration(url: str):
    """The video's length in seconds, or None if it can't be read (a live stream, say)."""
    done = subprocess.run([str(_ytdlp()), url, "--no-playlist", "--skip-download", "--print", "duration"],
                          capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL,
                          creationflags=_CREATE_NO_WINDOW)
    try:
        return float(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def _clip(url: str, start: float, end: float, title: str) -> None:
    with _lock:   # one at a time: two downloads at once just halve each other's speed
        try:
            try:
                path = _run_ytdlp(url, start, end)
            except RuntimeError:
                # Asked for more than there is? Say so, rather than surfacing an ffmpeg exit code.
                length = _duration(url)
                if length is not None and end > length + 1:
                    raise RuntimeError(f"the video is only {stamp(length)} long, so it can't go to {stamp(end)}")
                # Otherwise YouTube changed something and this yt-dlp is out of date: update, try once more
                subprocess.run([str(_ytdlp()), "-U"], capture_output=True, timeout=120,
                               stdin=subprocess.DEVNULL, creationflags=_CREATE_NO_WINDOW)
                path = _run_ytdlp(url, start, end)
            message = f"The clip of {title} from {stamp(start)} to {stamp(end)} is saved in Videos, TRON Clips."
            result = f"saved {path}"
        except Exception as exc:
            message = f"I couldn't clip {title}: {exc}"
            result = f"failed: {exc}"
    import memory
    memory.log_activity({"tool": "clip_video", "args": {"url": url, "start": start, "end": end}, "result": result})
    on_finished(message)


def clip_video(args, cfg=None) -> str:
    """Tool handler: starts the clip in the background and answers straight away."""
    try:
        start = float(args.get("start_seconds"))
        end = float(args.get("end_seconds"))
    except (TypeError, ValueError):
        return "I need the start and end times of the clip, sir"
    if start < 0 or end <= start:
        return "the end of the clip has to come after its start, sir"
    found = current_video()
    if not found:
        return ("I can't see a video in a browser, sir. I can clip videos playing in Chrome, Edge, Brave, "
                "Firefox, Opera or Vivaldi")
    url, title = found
    threading.Thread(target=_clip, args=(url, start, end, title), daemon=True).start()
    return (f'clipping "{title}" from {stamp(start)} to {stamp(end)}. It takes a few seconds to a minute; '
            "tell the user you'll let them know when it's saved")
