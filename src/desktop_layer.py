# desktop_layer.py
"""
Raw Win32 window manipulation for making the orb behave like a desktop
overlay rather than a normal window: pin_to_desktop() reparents it behind
every application window (the trick "live wallpaper" apps like Wallpaper
Engine use — undocumented, can silently fail on some Windows builds).
Degrades quietly (returns False) rather than raising when the trick doesn't
work on a given machine.

The orb is genuinely transparent: it is a layered window painted with
UpdateLayeredWindow, which gives real per-pixel alpha against whatever is
behind it (see orb_ui). Two earlier attempts are recorded here so they are not
retried — a WebView2 window with a colorkey (the key is all-or-nothing and
shredded the soft edge, and pywebview has open issues on this: r0x0r/pywebview
 #1779, #1758, #1611, #1653, #1634), and painting a copy of the wallpaper
behind an opaque window (which went stale the moment the wallpaper changed).

strip_window_chrome() exists because Windows 11 rounds and outlines frameless
windows, and a rounded outlined rectangle on the desktop is exactly the
"window" the orb is meant to have none of.
"""
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi

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

# DwmSetWindowAttribute, Windows 11 22000+. Older builds return a failure HRESULT
# and are left alone — they don't round window corners in the first place.
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWCP_DONOTROUND = 1
_DWMWA_BORDER_COLOR = 34
_DWMWA_COLOR_NONE = 0xFFFFFFFE

_HWND_BOTTOM = 1
_HWND_TOPMOST = -1
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOACTIVATE = 0x0010

user32.GetParent.restype = wintypes.HWND
user32.GetParent.argtypes = [wintypes.HWND]


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
    sibling = user32.FindWindowExW(None, progman, "WorkerW", None)
    if sibling:
        return sibling

    # Last resort: Progman itself. Observed on Windows 11 24H2, where the spawn
    # message is ignored, SHELLDLL_DefView stays parented to Progman, and every
    # WorkerW on the system is an invisible orphan — so both branches above come
    # back empty and pinning silently did nothing. Progman *is* the desktop
    # window, so parenting to it puts the orb on the wallpaper layer just the
    # same; it only sits alongside the icon host rather than behind it.
    if user32.FindWindowExW(progman, None, "SHELLDLL_DefView", None):
        return progman
    return None


def strip_window_chrome(hwnd: int) -> bool:
    """Squares off the window's corners and removes its border so nothing of the
    window itself is visible against the wallpaper. Best-effort: returns False on
    Windows 10 and earlier, where the attributes don't exist and corners aren't
    rounded anyway."""
    ok = True
    for attribute, value in (
        (_DWMWA_WINDOW_CORNER_PREFERENCE, _DWMWCP_DONOTROUND),
        (_DWMWA_BORDER_COLOR, _DWMWA_COLOR_NONE),
    ):
        result = dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(attribute),
            ctypes.byref(ctypes.c_uint(value)),
            ctypes.sizeof(ctypes.c_uint),
        )
        ok = ok and result == 0
    return ok


def pin_to_desktop(hwnd: int) -> bool:
    """Reparents hwnd onto the desktop so it sits behind every application
    window. Returns False (never raises) if no desktop window could be located
    or the reparent call failed — the window just stays at normal depth.

    **Not usable with a layered window.** Reparenting makes hwnd a child window,
    and UpdateLayeredWindow does not composite for child windows: the orb went
    fully black the moment this was applied to it. The orb therefore uses
    send_to_bottom() instead. Kept because it is the correct approach for an
    ordinary opaque window."""
    target = _find_worker_w()
    if not target:
        return False
    return bool(user32.SetParent(wintypes.HWND(hwnd), target))


def send_to_bottom(hwnd: int) -> bool:
    """Sinks hwnd to the bottom of the z-order, so every application window
    covers it while the desktop does not.

    This is the layered-window-safe alternative to pin_to_desktop: hwnd stays
    top-level, which UpdateLayeredWindow requires. Paired with WS_EX_NOACTIVATE
    the window never raises itself, so it stays down there."""
    return bool(user32.SetWindowPos(
        wintypes.HWND(hwnd), wintypes.HWND(_HWND_BOTTOM), 0, 0, 0, 0,
        _SWP_NOSIZE | _SWP_NOMOVE | _SWP_NOACTIVATE,
    ))


def survive_show_desktop(hwnd: int) -> bool:
    """Keeps hwnd on screen through Show desktop (Win+D, the three-finger swipe down), which hides every
    application window. Windows leaves the desktop's own windows alone, so this makes the desktop (Progman)
    the window's OWNER, the way desktop-widget apps such as Rainmeter do. An owner, not a parent: hwnd stays
    top-level, so its layered transparency still works (pin_to_desktop's child window renders black)."""
    progman = user32.FindWindowW("Progman", None)
    if not progman:
        return False
    set_owner = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
    set_owner.restype = ctypes.c_void_p
    set_owner.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    set_owner(wintypes.HWND(hwnd), -8, progman)   # GWLP_HWNDPARENT sets the owner of a top-level window
    return True


def keep_on_top(hwnd: int) -> bool:
    """Floats hwnd above ordinary windows, without stealing focus.

    The counterpart to send_to_bottom: the compact widget is meant to sit over
    whatever you are working in, where the desktop orb is meant to sit under
    it."""
    return bool(user32.SetWindowPos(
        wintypes.HWND(hwnd), wintypes.HWND(_HWND_TOPMOST), 0, 0, 0, 0,
        _SWP_NOSIZE | _SWP_NOMOVE | _SWP_NOACTIVATE,
    ))


def move_onscreen(hwnd: int, x: int, y: int) -> bool:
    """Moves hwnd to x,y, clamped so it can never be dragged off the screen.

    Without the clamp a widget flicked at the edge becomes unreachable — there
    is no title bar to grab it back by."""
    rect = wintypes.RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return False
    width = rect.right - rect.left
    margin = 12          # always leave a grabbable sliver on screen
    # The virtual desktop, not the primary monitor: clamping to metrics 0/1
    # pulled the widget back whenever it was dragged onto a second screen, and
    # y >= 0 blocked monitors placed above or left of the primary.
    left, top = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    right = left + user32.GetSystemMetrics(78)
    bottom = top + user32.GetSystemMetrics(79)
    x = max(left + margin - width, min(int(x), right - margin))
    y = max(top, min(int(y), bottom - margin))
    return bool(user32.SetWindowPos(
        wintypes.HWND(hwnd), None, x, y, 0, 0, _SWP_NOSIZE | _SWP_NOACTIVATE))


def center_on_primary(hwnd: int) -> bool:
    """Centres hwnd on the primary monitor in real screen pixels.

    Doing it here rather than at creation time because window managers take
    position in logical (DPI-scaled) units while GetSystemMetrics reports
    physical ones: on a scaled display the two disagree and the orb lands
    noticeably off-centre. Working from the window's own measured rect sidesteps
    the scale factor entirely.

    Must run *after* pinning: reparenting makes the position parent-relative, so
    the coordinates are converted through the parent when there is one."""
    rect = wintypes.RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return False
    width, height = rect.right - rect.left, rect.bottom - rect.top
    x = (user32.GetSystemMetrics(0) - width) // 2
    y = (user32.GetSystemMetrics(1) - height) // 2

    parent = user32.GetParent(wintypes.HWND(hwnd))
    if parent:
        point = wintypes.POINT(x, y)
        user32.ScreenToClient(wintypes.HWND(parent), ctypes.byref(point))
        x, y = point.x, point.y

    return bool(user32.SetWindowPos(
        wintypes.HWND(hwnd), wintypes.HWND(_HWND_BOTTOM), x, y, 0, 0,
        _SWP_NOSIZE | _SWP_NOACTIVATE,
    ))
