# desktop_layer.py
"""
Raw Win32 window manipulation for making the orb behave like a desktop
overlay rather than a normal window: pin_to_desktop() reparents it behind
every application window (the trick "live wallpaper" apps like Wallpaper
Engine use — undocumented, can silently fail on some Windows builds), and
apply_chroma_key_transparency() gives it a genuinely see-through background
(pywebview's transparent=True is a known-incomplete no-op on Windows — see
that function's docstring). Both degrade quietly (return False) rather than
raising when the underlying trick doesn't work on a given machine.
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

user32.GetWindowLongW.restype = ctypes.c_long
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]

user32.SetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]

user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
user32.SetLayeredWindowAttributes.argtypes = [
    wintypes.HWND, wintypes.DWORD, ctypes.c_ubyte, wintypes.DWORD,
]

_SPAWN_WORKERW = 0x052C
_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x00080000
_LWA_COLORKEY = 0x00000001


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


def apply_chroma_key_transparency(hwnd: int, key_color_rgb: int) -> bool:
    """Makes every pixel of hwnd matching key_color_rgb (0xRRGGBB) fully
    transparent, via a Win32 layered-window color key. This is the actual fix
    for pywebview's transparent=True on Windows — that flag only makes the
    browser control alpha-aware against its own Form, which stays opaque (see
    module docstring's sibling problem), so the window renders as a solid
    gray/white box instead of showing the desktop through it. The caller's
    page must paint its background exactly key_color_rgb — not literally
    "transparent" — for this to have anything to key against (see orb.html)."""
    style = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, style | _WS_EX_LAYERED)
    r = (key_color_rgb >> 16) & 0xFF
    g = (key_color_rgb >> 8) & 0xFF
    b = key_color_rgb & 0xFF
    colorref = (b << 16) | (g << 8) | r
    return bool(user32.SetLayeredWindowAttributes(hwnd, colorref, 0, _LWA_COLORKEY))
