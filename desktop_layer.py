# desktop_layer.py
"""
Reparents a window behind every application window, at the same z-level as
desktop icons — the trick "live wallpaper" apps like Wallpaper Engine use.
Undocumented Windows behavior (the 0x052C message to Progman isn't part of
the public Win32 API), so this can silently fail on some Windows builds —
callers should treat a False return as "stayed a normal window" and move on,
not as a fatal error.
"""
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]

user32.FindWindowExW.restype = wintypes.HWND
user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]

user32.SendMessageTimeoutW.restype = ctypes.c_void_p
user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
]

user32.SetParent.restype = wintypes.HWND
user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL

_SPAWN_WORKERW = 0x052C


def _find_worker_w():
    progman = user32.FindWindowW("Progman", None)
    if not progman:
        return None

    # Undocumented: asks Progman to spawn a second WorkerW behind the icons.
    user32.SendMessageTimeoutW(progman, _SPAWN_WORKERW, 0, 0, 0x0000, 1000, None)

    found = {"hwnd": None}

    @EnumWindowsProc
    def _enum(top_hwnd, _lparam):
        # The WorkerW that hosts the desktop icons has a SHELLDLL_DefView child;
        # the *next* WorkerW after it in z-order is the blank one we want.
        shell_view = user32.FindWindowExW(top_hwnd, None, "SHELLDLL_DefView", None)
        if shell_view:
            found["hwnd"] = user32.FindWindowExW(None, top_hwnd, "WorkerW", None)
        return True

    user32.EnumWindows(_enum, 0)
    if found["hwnd"]:
        return found["hwnd"]

    # Fallback for Windows builds where SHELLDLL_DefView stays a direct child
    # of Progman itself (the spawn message doesn't relocate it) — in that
    # arrangement, the WorkerW immediately after Progman in z-order is the
    # one to use, if one exists at all.
    return user32.FindWindowExW(None, progman, "WorkerW", None) or None


def pin_to_desktop(hwnd: int) -> bool:
    """Reparents hwnd behind every application window. Returns False (never
    raises) if the WorkerW window couldn't be located or the reparent call
    failed — the window just stays at normal depth in that case."""
    worker_w = _find_worker_w()
    if not worker_w:
        return False
    return bool(user32.SetParent(wintypes.HWND(hwnd), worker_w))
