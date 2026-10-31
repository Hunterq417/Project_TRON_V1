# desktop_control.py
"""Volume, screen brightness and window management.

Three different Windows mechanisms, chosen per job rather than uniformly:

* Volume goes through pycaw (Core Audio). The media keys can only nudge in 2%
  steps, and "set the volume to thirty" is a normal thing to say out loud.
* Brightness goes through WMI over PowerShell. There is no unelevated Python
  API for it, and this needs no extra dependency.
* Window operations use Win32 directly for the focused window, and shell
  hotkeys for the shell-level ones (show desktop, switch window) because those
  are not window operations at all — they are things only Explorer can do.
"""
import ctypes
import os
import subprocess
import time
from ctypes import wintypes

import keyboard
from pycaw.pycaw import AudioUtilities

user32 = ctypes.windll.user32

_SW_MINIMIZE = 6
_SW_MAXIMIZE = 3
_SW_RESTORE = 9
_WM_CLOSE = 0x0010


# --- volume ---------------------------------------------------------------

def _endpoint():
    return AudioUtilities.GetSpeakers().EndpointVolume


def set_volume(args, cfg=None) -> str:
    """Absolute level, 0-100."""
    try:
        level = int(args.get("level"))
    except (TypeError, ValueError):
        return "I need a volume between 0 and 100, sir"
    level = max(0, min(100, level))
    try:
        endpoint = _endpoint()
        endpoint.SetMasterVolumeLevelScalar(level / 100.0, None)
        # Setting a level on a muted device leaves it silent, which reads as a
        # failure to whoever just asked for volume.
        if level > 0 and endpoint.GetMute():
            endpoint.SetMute(0, None)
    except Exception as exc:
        return f"I couldn't reach the volume control, sir ({exc})"
    return f"volume is at {level} percent, sir"


def change_volume(args, cfg=None) -> str:
    """Relative nudge, e.g. +10 or -10."""
    try:
        delta = int(args.get("delta"))
    except (TypeError, ValueError):
        return "I need an amount to change the volume by, sir"
    try:
        endpoint = _endpoint()
        current = round(endpoint.GetMasterVolumeLevelScalar() * 100)
        level = max(0, min(100, current + delta))
        endpoint.SetMasterVolumeLevelScalar(level / 100.0, None)
        if level > 0 and endpoint.GetMute():
            endpoint.SetMute(0, None)
    except Exception as exc:
        return f"I couldn't reach the volume control, sir ({exc})"
    return f"volume is at {level} percent, sir"


def set_mute(args, cfg=None) -> str:
    muted = bool(args.get("muted", True))
    try:
        _endpoint().SetMute(1 if muted else 0, None)
    except Exception as exc:
        return f"I couldn't reach the volume control, sir ({exc})"
    return "muted, sir" if muted else "unmuted, sir"


def volume_status(args=None, cfg=None) -> str:
    try:
        endpoint = _endpoint()
        level = round(endpoint.GetMasterVolumeLevelScalar() * 100)
        if endpoint.GetMute():
            return f"volume is muted, sir — it's set to {level} percent underneath"
        return f"volume is at {level} percent, sir"
    except Exception as exc:
        return f"I couldn't read the volume, sir ({exc})"


# --- brightness -----------------------------------------------------------

# See radio_control: a windowed frozen build has no console, so a child process
# inherits invalid standard handles unless it is given them explicitly.
_CREATE_NO_WINDOW = 0x08000000


def _powershell(script: str) -> str:
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=30,
        stdin=subprocess.DEVNULL, creationflags=_CREATE_NO_WINDOW,
    ).stdout.strip()


def set_brightness(args, cfg=None) -> str:
    try:
        level = int(args.get("level"))
    except (TypeError, ValueError):
        return "I need a brightness between 0 and 100, sir"
    level = max(0, min(100, level))
    script = (
        "try { (Get-CimInstance -Namespace root/WMI -ClassName "
        "WmiMonitorBrightnessMethods -ErrorAction Stop)."
        f"WmiSetBrightness(1,{level}); Write-Output 'OK' }} "
        "catch { Write-Output 'UNSUPPORTED' }"
    )
    try:
        out = _powershell(script)
    except Exception as exc:
        return f"I couldn't set the brightness, sir ({exc})"
    if "OK" in out:
        return f"brightness is at {level} percent, sir"
    # External monitors do not expose this interface — only the built-in panel
    # does, so this is a normal outcome on a desktop, not a fault.
    return ("this display doesn't let me set its brightness, sir — that's usual "
            "for an external monitor")


def brightness_status(args=None, cfg=None) -> str:
    script = (
        "try { (Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness "
        "-ErrorAction Stop).CurrentBrightness } catch { Write-Output 'UNSUPPORTED' }"
    )
    try:
        out = _powershell(script)
    except Exception as exc:
        return f"I couldn't read the brightness, sir ({exc})"
    first = out.splitlines()[0].strip() if out else ""
    if first.isdigit():
        return f"brightness is at {first} percent, sir"
    return "this display doesn't report its brightness, sir"


# --- windows --------------------------------------------------------------

def _foreground() -> int:
    return user32.GetForegroundWindow()


# Windows that ARE the desktop. Closing these takes the taskbar or the desktop
# itself down, and "close explorer" would otherwise match them, because folder
# windows and the shell are the same process.
_SHELL_CLASSES = {"Progman", "Shell_TrayWnd", "WorkerW", "Shell_SecondaryTrayWnd",
                  "Windows.UI.Core.CoreWindow"}

# Dropped before matching: people say "close the browser window", and "window"
# or "the" would otherwise match everything on screen.
_FILLER = {"the", "my", "a", "an", "app", "application", "window", "windows",
           "program", "please", "current", "this", "that", "it", "one", "them",
           "these", "those", "all", "everything"}

_EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _cloaked(hwnd) -> bool:
    """Store apps leave "visible" windows Windows has actually hidden: a minimised Calculator's
    CoreWindow, suspended apps. Matching those made "switch to calculator" grab an invisible window."""
    value = ctypes.c_int(0)
    ctypes.windll.dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), 14,  # DWMWA_CLOAKED
                                               ctypes.byref(value), ctypes.sizeof(value))
    return value.value != 0


def _open_windows() -> list:
    """(hwnd, title, process name) for every visible, titled top-level window."""
    import psutil

    found = []

    @_EnumWindowsProc
    def collect(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd) or _cloaked(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)

        class_name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_name, 256)
        if class_name.value in _SHELL_CLASSES:
            return True

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            name = psutil.Process(pid.value).name()
        except Exception:
            name = ""
        found.append((hwnd, buffer.value, name))
        return True

    user32.EnumWindows(collect, 0)
    return found


def _matches(query: str, windows: list) -> list:
    """Windows matching a spoken name, most specific interpretation first.

    Tries the whole phrase before individual words, and longer words before
    shorter ones, so "file explorer" is decided by "explorer" rather than
    dragging in every window with "file" in its title."""
    cleaned = "".join(c for c in query.lower() if c.isalnum() or c.isspace())
    # Filler goes before ANY matching, the whole phrase included. "close it"
    # used to substring-match "it" against every title and closed GitHub and
    # Edit windows alike; a pronoun names no window, so it matches none.
    tokens = [t for t in cleaned.split() if t not in _FILLER]
    wanted = " ".join(tokens)
    if len(wanted) < 3:
        return []

    def haystack(entry):
        _hwnd, title, process = entry
        return f"{title} {process.removesuffix('.exe')}".lower()

    whole = [w for w in windows if wanted in haystack(w)]
    if whole:
        return whole

    for token in sorted((t for t in tokens if len(t) >= 3), key=len, reverse=True):
        hits = [w for w in windows if token in haystack(w)]
        if hits:
            return hits
    return []


def close_app(args, cfg=None) -> str:
    """Close an application by name, e.g. "close the file explorer".

    Separate from window_action because that one only ever touches the focused
    window, and people name the thing they want closed. Without this the model
    has no tool that fits "close X" and reaches for open_target instead, which
    is how asking to close File Explorer opened a second one."""
    query = str(args.get("name", "")).strip()
    if not query:
        return "which app should I close, sir?"

    own_pid = os.getpid()
    windows = []
    for hwnd, title, process in _open_windows():
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != own_pid:          # never close ourselves
            windows.append((hwnd, title, process))

    hits = _matches(query, windows)
    if not hits:
        return _close_background(query)

    for hwnd, _title, _process in hits:
        user32.PostMessageW(wintypes.HWND(hwnd), _WM_CLOSE, 0, 0)

    if len(hits) == 1:
        return f'closed "{hits[0][1] or query}", sir'
    return f"closed {len(hits)} {query} windows, sir"


# Windows itself: never ended by "close X", whatever X matches.
_PROTECTED = {"system", "registry", "smss", "csrss", "wininit", "winlogon", "services", "lsass", "svchost",
              "dwm", "explorer", "fontdrvhost", "sihost", "ctfmon", "taskhostw", "runtimebroker", "searchhost",
              "startmenuexperiencehost", "shellexperiencehost", "audiodg", "conhost", "spoolsv", "msmpeng",
              "securityhealthservice", "python", "pythonw", "tron"}


def _close_background(query: str) -> str:
    """An app with no visible window (in the tray, running in the background): find its processes by name,
    ask its hidden windows to close as a person would, end what's still running after a moment, and check."""
    import psutil
    own = os.getpid()
    procs = []
    for p in psutil.process_iter(["pid", "name"]):
        name = (p.info["name"] or "").lower().removesuffix(".exe")
        if p.info["pid"] != own and name and name not in _PROTECTED:
            procs.append((p.info["pid"], "", name))
    hits = _matches(query, procs)
    if not hits:
        return f"I can't find \"{query}\" running, sir - not as a window and not in the background"
    pids = {pid for pid, _t, _n in hits}
    name = hits[0][2]

    @_EnumWindowsProc
    def ask(hwnd, _lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids:
            user32.PostMessageW(wintypes.HWND(hwnd), _WM_CLOSE, 0, 0)
        return True
    user32.EnumWindows(ask, 0)
    _gone, alive = psutil.wait_procs([psutil.Process(pid) for pid in pids if psutil.pid_exists(pid)], timeout=3)
    for proc in alive:            # tray apps often just hide on close: end them
        try:
            proc.terminate()
        except psutil.Error:
            pass
    _gone, still = psutil.wait_procs(alive, timeout=3)
    if still:
        return f"I tried to close {name} in the background, but {len(still)} of its processes are still running, sir"
    return f"closed {name}, which was running in the background, sir"


def list_windows(args=None, cfg=None) -> str:
    """What is actually open, so "close X" can be aimed at a real window."""
    windows = _open_windows()
    if not windows:
        return "nothing is open, sir"
    titles = [title for _hwnd, title, _process in windows][:12]
    return "open windows, sir: " + "; ".join(titles)


def window_action(args, cfg=None) -> str:
    """minimise / maximise / restore / close the focused window, or drive the
    shell for show-desktop and switch-window."""
    action = str(args.get("action", "")).strip().lower().replace("_", " ")

    if action in ("show desktop", "minimize all", "minimise all"):
        keyboard.send("windows+d")
        return "showing the desktop, sir"
    if action in ("switch window", "switch", "next window"):
        keyboard.send("alt+tab")
        return "switched window, sir"

    hwnd = _foreground()
    if not hwnd:
        return "there's no focused window, sir"

    if action in ("minimize", "minimise"):
        user32.ShowWindow(wintypes.HWND(hwnd), _SW_MINIMIZE)
        return "minimised, sir"
    if action in ("maximize", "maximise"):
        user32.ShowWindow(wintypes.HWND(hwnd), _SW_MAXIMIZE)
        return "maximised, sir"
    if action == "restore":
        user32.ShowWindow(wintypes.HWND(hwnd), _SW_RESTORE)
        return "restored, sir"
    if action == "close":
        # PostMessage(WM_CLOSE), not TerminateProcess: this is the same thing
        # clicking the X does, so the app gets to prompt about unsaved work
        # rather than losing it.
        user32.PostMessageW(wintypes.HWND(hwnd), _WM_CLOSE, 0, 0)
        return "closed it, sir"

    return (f'I don\'t know how to "{action}", sir. I can minimise, maximise, '
            "restore, close, show the desktop, or switch window")


# --- by-name app control (from Hey Jev) -------------------------------------

def _app_hits(query: str) -> list:
    own_pid = os.getpid()
    windows = []
    for hwnd, title, process in _open_windows():
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != own_pid:
            windows.append((hwnd, title, process))
    return _matches(query, windows)


def _bring_to_front(hwnd) -> None:
    """Windows only lets whoever last had input change the foreground window. A tap of Alt counts as
    input; if that isn't enough, briefly sharing input with the current foreground thread always is."""
    if user32.IsIconic(wintypes.HWND(hwnd)):
        user32.ShowWindow(wintypes.HWND(hwnd), _SW_RESTORE)
    elif user32.GetForegroundWindow() == hwnd:
        # Already in front: no Alt. In Chromium apps (Spotify, browsers) Alt opens the app's menu, and a
        # second Alt closes it — which is why every other Spotify search came back empty.
        return
    keyboard.send("alt")
    if user32.SetForegroundWindow(wintypes.HWND(hwnd)):
        return
    kernel32 = ctypes.windll.kernel32
    ours = kernel32.GetCurrentThreadId()
    theirs = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    user32.AttachThreadInput(ours, theirs, True)
    try:
        user32.BringWindowToTop(wintypes.HWND(hwnd))
        user32.SetForegroundWindow(wintypes.HWND(hwnd))
    finally:
        user32.AttachThreadInput(ours, theirs, False)


def focus_app(args, cfg=None) -> str:
    """Switch to an app that is already open, e.g. "switch to Spotify"."""
    query = str(args.get("name", "")).strip()
    if not query:
        return "which app should I switch to, sir?"
    hits = _app_hits(query)
    if not hits:
        return f'"{query}" is not open, sir. I can open it instead'
    _bring_to_front(hits[0][0])
    return f'switched to "{hits[0][1]}", sir'


def minimize_app(args, cfg=None) -> str:
    """Minimise every window of a named app, e.g. "minimise Chrome"."""
    query = str(args.get("name", "")).strip()
    if not query:
        return "which app should I minimise, sir?"
    hits = _app_hits(query)
    if not hits:
        return f'I cannot find a window for "{query}", sir'
    for hwnd, _title, _process in hits:
        user32.ShowWindow(wintypes.HWND(hwnd), _SW_MINIMIZE)
    return f"minimised {query}, sir"


# --- one app's own volume, e.g. Spotify's slider in the volume mixer --------

def _app_session(name: str):
    want = "".join(c for c in name.lower() if c.isalnum())
    for session in AudioUtilities.GetAllSessions():
        if session.Process:
            process = session.Process.name().lower().removesuffix(".exe")
            if len(process) >= 3 and (process in want or want in process):
                return session.SimpleAudioVolume
    return None


def set_app_volume(args, cfg=None) -> str:
    """Set or nudge one app's own volume without touching the system level."""
    name = str(args.get("app", "")).strip()
    if not name:
        return "which app's volume, sir?"
    if "spotify" in name.lower():
        import music
        said = music.spotify_volume(args)   # Spotify's own slider, the one the user sees
        if said:
            return said
    try:
        volume = _app_session(name)
        if volume is None:
            return f"{name} is not playing any sound right now, sir"
        current = round(volume.GetMasterVolume() * 100)
        if args.get("level") is not None:
            level = int(args["level"])
        else:
            level = current + int(args.get("delta", 0))
        level = max(0, min(100, level))
        volume.SetMasterVolume(level / 100.0, None)
    except (TypeError, ValueError):
        return "I need a level between 0 and 100, sir"
    except Exception as exc:
        return f"I couldn't reach {name}'s volume, sir ({exc})"
    return f"{name} is at {level} percent, sir"


# --- browser -----------------------------------------------------------------

_BROWSER_EXE = {"chrome": "chrome", "google chrome": "chrome", "edge": "msedge", "microsoft edge": "msedge",
                "brave": "brave", "firefox": "firefox"}


def open_website(args, cfg=None) -> str:
    """Open a URL, in a named browser if one was asked for, else the default."""
    url = str(args.get("url", "")).strip()
    if not url or " " in url:
        return "which website, sir?"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    exe = _BROWSER_EXE.get(str(args.get("browser", "")).strip().lower())
    try:
        if exe:
            subprocess.run(["cmd", "/c", "start", "", exe, url], check=True,
                           stdin=subprocess.DEVNULL, creationflags=_CREATE_NO_WINDOW)
        else:
            os.startfile(url)
    except Exception as exc:
        return f"I couldn't open that, sir ({exc})"
    site = url.split("://", 1)[1].split("/", 1)[0].removeprefix("www.")
    return f"opened {site}, sir"


def new_tab(args, cfg=None) -> str:
    """A fresh tab in the named browser, or in whichever window is in front."""
    browser = str(args.get("browser", "")).strip()
    if browser:
        hits = _app_hits(browser)
        if not hits:
            return f"{browser} is not open, sir"
        _bring_to_front(hits[0][0])
        time.sleep(0.3)
    keyboard.send("ctrl+t")
    return "new tab's open, sir"


# --------------------------------------------------------------------------- video in the browser
_FULL = ("full screen", "fullscreen")


def _video_window():
    """The browser window showing the video: the front one if it's a browser, else the topmost browser."""
    import video_clip
    browsers = [w for w in _open_windows() if w[2].lower().removesuffix(".exe") in video_clip.BROWSERS]
    front = _foreground()
    browsers.sort(key=lambda w: w[0] != front)
    return browsers[0][0] if browsers else None


def _controls(hwnd):
    """(name, element) for every button/toggle in the window, hidden ones included: a player's controls
    fade out after a moment, but they can still be pressed."""
    import music
    uia, lib = music._uia()
    cond = uia.CreateOrCondition(
        uia.CreatePropertyCondition(lib.UIA_ControlTypePropertyId, lib.UIA_ButtonControlTypeId),
        uia.CreatePropertyCondition(lib.UIA_ControlTypePropertyId, lib.UIA_CheckBoxControlTypeId))
    found = uia.ElementFromHandle(hwnd).FindAll(lib.TreeScope_Descendants, cond)
    out = []
    for i in range(found.Length):
        try:
            element = found.GetElement(i)
            out.append(((element.CurrentName or "").strip().lower(), element))
        except Exception:
            continue
    return out


def _press(element) -> bool:
    import music
    _uia_obj, lib = music._uia()
    for pattern_id, iface, call in ((lib.UIA_InvokePatternId, lib.IUIAutomationInvokePattern, "Invoke"),
                                    (lib.UIA_TogglePatternId, lib.IUIAutomationTogglePattern, "Toggle")):
        try:
            pattern = element.GetCurrentPattern(pattern_id)
            if pattern:
                getattr(pattern.QueryInterface(iface), call)()
                return True
        except Exception:
            continue
    return False


def _monitor(hwnd):
    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(user32.MonitorFromWindow(wintypes.HWND(hwnd), 2), ctypes.byref(info))
    return info.rcMonitor


def _video_element(hwnd):
    """The page's video: the biggest element named like a video or player ("Video Player" on Miruro)."""
    import music
    uia, lib = music._uia()
    found = uia.ElementFromHandle(hwnd).FindAll(lib.TreeScope_Descendants, uia.CreateTrueCondition())
    best, area = None, 0
    for i in range(found.Length):
        try:
            element = found.GetElement(i)
            name = (element.CurrentName or "").lower()
            r = element.CurrentBoundingRectangle
            size = max(0, r.right - r.left) * max(0, r.bottom - r.top)
        except Exception:
            continue
        if ("video" in name or "player" in name) and size > area:
            best, area = element, size
    return best


def _is_fullscreen(hwnd) -> bool:
    """The video fills the monitor. (The window size can't tell: with an auto-hiding taskbar a maximised
    window covers the monitor too, and Brave still reports its address bar in full screen.)"""
    video = _video_element(hwnd)
    if video is None:
        return False
    r, m = video.CurrentBoundingRectangle, _monitor(hwnd)
    return (r.right - r.left) >= 0.95 * (m.right - m.left) and (r.bottom - r.top) >= 0.85 * (m.bottom - m.top)


def _double_click_video(hwnd) -> bool:
    """Double-click the middle of the video: every common web player toggles full screen on it. (It can
    also toggle play/pause; video_control puts playback back the way it was.)"""
    import computer
    video = _video_element(hwnd)
    if video is None:
        return False
    computer._real_click(video, double=True)
    return True


def _is_playing(hwnd):
    """True/False from the player's own button (it reads "Pause" while playing), None when it has none."""
    names = [n for n, _e in _controls(hwnd)]
    if any(n == "pause" or n.startswith("pause (") for n in names):
        return True
    if any(n == "play" or n.startswith("play (") for n in names):
        return False
    return None


def video_control(args, cfg=None) -> str:
    """Tool: play, pause or full-screen the video in the browser, and check that it happened."""
    action = str(args.get("action", "")).lower().replace(" ", "_")
    hwnd = _video_window()
    if not hwnd:
        return "there's no browser window with a video open, sir"
    _bring_to_front(hwnd)
    time.sleep(0.4)
    if action in ("play", "pause", "play_fullscreen"):
        want = action != "pause"
        if _is_playing(hwnd) != want:
            buttons = [e for n, e in _controls(hwnd) if n == ("play" if want else "pause")
                       or n.startswith(("play (" if want else "pause ("))]
            if not (buttons and _press(buttons[0])):
                keyboard.send("play/pause media")   # the browser passes media keys to the page's player
            time.sleep(1.2)
        state = _is_playing(hwnd)
        if state is not None and state != want:
            return f"I pressed {'play' if want else 'pause'} but the video didn't {'start' if want else 'stop'}, sir"
        if action != "play_fullscreen":
            return f"the video is {'playing' if want else 'paused'}, sir"
        time.sleep(0.8)   # players build their full-screen button once playback starts
    if action in ("fullscreen", "play_fullscreen", "exit_fullscreen"):
        want = action != "exit_fullscreen"
        was_playing = _is_playing(hwnd)
        if _is_fullscreen(hwnd) == want:
            return f"it's already {'in' if want else 'out of'} full screen, sir"
        if not want:
            keyboard.send("esc")
        else:
            buttons = [e for n, e in _controls(hwnd) if any(f in n for f in _FULL) and "exit" not in n]
            if not (buttons and _press(buttons[0])):
                keyboard.send("f")   # YouTube, Plyr and most players: F toggles full screen
                time.sleep(1.0)
                if not _is_fullscreen(hwnd):
                    _double_click_video(hwnd)   # the player's own controls sat in a frame Windows can't see
        time.sleep(1.2)
        if _is_fullscreen(hwnd) != want:
            return (f"I tried, but the video didn't go {'full screen' if want else 'back to normal'}, sir. "
                    "Click the video once, then ask again.")
        if was_playing and _is_playing(hwnd) is False:
            keyboard.send("play/pause media")   # the double-click paused it
            time.sleep(0.8)
        return "the video is playing in full screen, sir" if action == "play_fullscreen" else \
            f"{'full screen' if want else 'back to normal size'}, sir"
    return "say play, pause, fullscreen, play_fullscreen or exit_fullscreen, sir"
