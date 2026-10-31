# system_control.py
import subprocess

# No console: a shell-out from a windowed app flashes a terminal otherwise.
_CREATE_NO_WINDOW = 0x08000000

_DELAY_SECONDS = 30


def shutdown_pc(args, cfg) -> str:
    return _schedule("/s", "shutting down")


def restart_pc(args, cfg) -> str:
    return _schedule("/r", "restarting")


def _schedule(flag: str, verb: str) -> str:
    try:
        subprocess.run(
            ["shutdown", flag, "/t", str(_DELAY_SECONDS), "/c", f"TRON is {verb} this PC, as requested."],
            stdin=subprocess.DEVNULL, creationflags=_CREATE_NO_WINDOW,
            check=True, capture_output=True, text=True,
        )
    except Exception as exc:
        return f"couldn't start the {verb}, sir: {exc}"
    return f"{verb} in {_DELAY_SECONDS} seconds, sir — say \"cancel shutdown\" to stop it"


def cancel_shutdown(args, cfg) -> str:
    try:
        subprocess.run(["shutdown", "/a"], check=True, capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, creationflags=_CREATE_NO_WINDOW)
    except subprocess.CalledProcessError:
        return "there's no pending shutdown to cancel, sir"
    except Exception as exc:
        return f"couldn't cancel it, sir: {exc}"
    return "cancelled, sir"


# --- from Hey Jev: lock, sleep, dark mode ------------------------------------

def lock_pc(args, cfg) -> str:
    import ctypes
    ctypes.windll.user32.LockWorkStation()
    return "locked, sir"


def sleep_pc(args, cfg) -> str:
    import ctypes
    # ponytail: SetSuspendState hibernates instead when hibernation is switched on; fine for "go to sleep"
    ctypes.windll.powrprof.SetSuspendState(False, True, False)
    return "going to sleep, sir"


_THEME_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def dark_mode_on() -> bool:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _THEME_KEY) as key:
        return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0


def set_dark_mode(args, cfg) -> str:
    """mode: on, off or toggle. Switches apps and the taskbar together, like Settings does."""
    import ctypes
    import winreg
    from ctypes import wintypes
    mode = str(args.get("mode", "toggle")).lower()
    try:
        dark = {"on": True, "off": False}.get(mode, not dark_mode_on())
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _THEME_KEY, 0, winreg.KEY_SET_VALUE) as key:
            for name in ("AppsUseLightTheme", "SystemUsesLightTheme"):
                winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, 0 if dark else 1)
        # tell open windows, otherwise the taskbar and Explorer only notice later
        result = wintypes.DWORD()
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "ImmersiveColorSet", 0x0002, 1000,
                                                 ctypes.byref(result))
    except Exception as exc:
        return f"couldn't change the theme, sir: {exc}"
    return "dark mode on, sir" if dark else "dark mode off, sir"
