# orb_ui.py
import ctypes
import time
import json
import math
import tkinter as tk
from ctypes import wintypes

import config
import desktop_layer
import orb_render
import widget_render

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x00080000
_WS_EX_TOOLWINDOW = 0x00000080   # keeps it out of the taskbar and alt-tab
_WS_EX_NOACTIVATE = 0x08000000   # never steals focus from what you are doing
_ULW_ALPHA = 0x02
_AC_SRC_OVER = 0x00
_AC_SRC_ALPHA = 0x01
_GA_ROOT = 2

# Orb radius as a fraction of the shorter screen edge, in real pixels. The
# window is only a few pixels wider than the sphere: with no halo there is
# nothing to leave room for, and every pixel outside the sphere is fully
# transparent anyway.
_RADIUS_FRACTION = 0.115
_FRAME_MS = 33

# The interface models the dashboard can switch between.
#
# The two differ in more than looks. The orb is desktop furniture: large,
# centred, behind every window, and not interactive. The ring is a floating
# widget: small, on top of your work, and dragged wherever you want it — which
# is why "topmost" and "draggable" live here rather than being global.
_MODELS = {
    # spin: turn continuously (the ring) rather than rocking about the fitted
    # pose (the orb, which cannot rotate far — see _WOBBLE).
    "aurora-orb": {"topmost": False, "draggable": False, "size": None, "spin": False},
    "halo-ring": {"topmost": True, "draggable": True, "size": 150, "spin": True},
    # Dust Orb: drawn by WebGL in a headless browser (dust_orb.py), shown and pinned like the Aurora Orb.
    "dust-orb": {"topmost": False, "draggable": False, "size": None, "spin": False},
}
_DEFAULT_MODEL = "halo-ring"

# How far the gradient tilts off the fitted pose, in radians. Small on purpose:
# all nine lobes sit on the front hemisphere because the reference frame only
# ever showed the front, so rotating far collapses the blend into a hard-edged
# black wedge. See orb_render.PARAMS.
_WOBBLE = 0.13

# tint, how strongly the state colours the sphere's edge, and how fast the
# gradient breathes. idle is 0, so at rest the orb is the untouched replica.
_STATES = {
    "idle":      {"tint": (0.29, 0.33, 0.41), "amt": 0.00, "rate": 0.30},
    "listening": {"tint": (0.26, 0.52, 0.96), "amt": 0.62, "rate": 0.75},
    "thinking":  {"tint": (1.00, 0.76, 0.03), "amt": 0.58, "rate": 1.45},
    "speaking":  {"tint": (0.20, 0.78, 0.35), "amt": 0.55, "rate": 0.95},
    "acting":    {"tint": (0.61, 0.35, 0.71), "amt": 0.62, "rate": 1.15},
    "error":     {"tint": (0.86, 0.21, 0.27), "amt": 0.78, "rate": 2.40},
    "dictating": {"tint": (0.94, 0.27, 0.27), "amt": 0.50, "rate": 0.60},
}


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class OrbUI:
    """A genuinely transparent orb pinned to the desktop layer.

    The window is a Win32 layered window driven by UpdateLayeredWindow, which is
    the only mechanism on Windows that gives real per-pixel alpha over whatever
    is behind it. That is why the orb is drawn on the CPU (see orb_render) rather
    than in a browser: a hosted WebView2 cannot composite against the desktop.
    The previous approach painted a copy of the wallpaper behind the orb to fake
    it, and that broke the instant the wallpaper changed — this one has nothing
    to keep in sync.

    tkinter supplies the window and the message loop; nothing it draws is ever
    shown, because a layered window's pixels come entirely from the bitmap handed
    to UpdateLayeredWindow.

    It is a permanent desktop ornament: up from launch and left up, changing
    only how it looks as the state changes. The tray's Show/Hide Orb is the one
    thing that takes it away. Because it is on screen all day, the tick loop
    skips both the render and the push whenever nothing that reaches the image
    has changed — see _tick.

    Must be run via run(), from the main thread.
    """

    def __init__(self):
        user32.SetProcessDPIAware()
        self._root = tk.Tk()
        self._root.title(config.APP_LABEL)
        self._root.overrideredirect(True)
        self._root.withdraw()

        data = self._config_data()
        self.model = data.get("ui_model") or _DEFAULT_MODEL
        if self.model not in _MODELS:
            self.model = _DEFAULT_MODEL
        spec = _MODELS[self.model]
        self._topmost = spec["topmost"]
        self._draggable = spec["draggable"]
        self._spin = spec["spin"]

        screen = min(user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
        if spec["size"]:
            size = int(spec["size"] * max(1.0, screen / 1080.0))   # keep it the same
            self._renderer = widget_render.RingWidget(               # size to the eye
                size=size, label=self._label(data))
        else:
            radius = max(24.0, screen * _RADIUS_FRACTION)
            size = int(radius * 2) + 8
            if self.model == "dust-orb":
                import dust_orb
                size = int(size * 1.4)      # the dust spreads wider than the aurora's sphere
                self._renderer = dust_orb.DustRenderer(size)
            else:
                self._renderer = orb_render.OrbRenderer(size=size, radius=radius)
        self._size = size
        self._drag_from = None

        self._root.geometry("%dx%d" % (size, size))
        self._root.update_idletasks()
        self._hwnd = user32.GetAncestor(wintypes.HWND(int(self._root.winfo_id())), _GA_ROOT)
        style = user32.GetWindowLongW(self._hwnd, _GWL_EXSTYLE)
        user32.SetWindowLongW(self._hwnd, _GWL_EXSTYLE,
                              style | _WS_EX_LAYERED | _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE)

        # The orb is a permanent desktop ornament: visible from launch and left
        # up, rather than appearing only for the length of a conversation. The
        # tray's Show/Hide Orb is the only thing that takes it away.
        if self._draggable:
            self._root.bind("<Button-1>", self._on_press)
            self._root.bind("<B1-Motion>", self._on_drag)
            self._root.bind("<ButtonRelease-1>", self._on_release)

        self._visible = True
        self._sunk_at = 0.0
        self._last_key = None
        self._placed = False
        self._quitting = False
        self._state = "idle"
        self._audio_level = 0.0
        self._smoothed_level = 0.0
        self._phase = 0.0
        self._rate = _STATES["idle"]["rate"]
        self._amt = _STATES["idle"]["amt"]
        self._tint = list(_STATES["idle"]["tint"])

    # ---- config -----------------------------------------------------------

    @staticmethod
    def _config_data():
        """Raw config, read defensively — the UI must come up even if the file
        is missing or malformed, because a broken config is exactly when you
        want to see that TRON is running at all."""
        try:
            return json.loads(config.CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def _label(data):
        """The active assistant's name, which is what the ring shows."""
        try:
            return str(config.active_assistant(data).get("name", "TRON"))
        except Exception:
            return "TRON"

    def _save_position(self, x, y):
        """Remembers where the widget was dragged to.

        Merged into config.json rather than rewritten, and failures are
        swallowed: losing the position is a nuisance, losing the config is not."""
        try:
            config.update_config_file({"widget_pos": [int(x), int(y)]})
        except Exception:
            pass

    # ---- the API main.py and the tray drive ------------------------------

    def run(self, on_ready) -> None:
        """Blocks the calling thread running the GUI loop — call this last, from
        the main thread. on_ready runs once the loop has started."""
        self._root.after(60, on_ready)
        self._root.after(_FRAME_MS, self._tick)
        self._root.mainloop()

    @property
    def root(self):
        """The Tk root, for windows that must share the orb's GUI thread (the control panel)."""
        return self._root

    def quit(self) -> None:
        # Called from the tray's thread; tkinter is not thread-safe, so this only
        # sets a flag and lets the tick loop do the teardown on the GUI thread.
        self._quitting = True
        if hasattr(self._renderer, "close"):
            self._renderer.close()

    def on_state_change(self, state) -> None:
        # State changes what the orb *looks* like, never whether it is on screen.
        # Visibility belongs solely to toggle_visibility, so hiding the orb from
        # the tray keeps it hidden through a whole conversation instead of having
        # it reappear at the next state change.
        name = state.name.lower()
        if name in _STATES:
            self._state = name
        if hasattr(self._renderer, "set_state"):
            self._renderer.set_state(name)

    def on_audio_level(self, level: float) -> None:
        self._audio_level = max(0.0, min(1.0, level))


    def toggle_visibility(self) -> None:
        self._visible = not self._visible


    # ---- painting ---------------------------------------------------------

    def _push(self, bgra) -> bool:
        """Hands the rendered frame to Windows as this window's actual pixels."""
        h, w = bgra.shape[:2]
        screen_dc = user32.GetDC(0)
        mem_dc = gdi32.CreateCompatibleDC(screen_dc)
        info = BITMAPINFOHEADER()
        info.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.biWidth, info.biHeight = w, -h        # negative height = top-down rows
        info.biPlanes, info.biBitCount = 1, 32
        bits = ctypes.c_void_p()
        dib = gdi32.CreateDIBSection(screen_dc, ctypes.byref(info), 0,
                                     ctypes.byref(bits), None, 0)
        try:
            ctypes.memmove(bits, bgra.ctypes.data, bgra.nbytes)
            old = gdi32.SelectObject(mem_dc, dib)
            blend = BLENDFUNCTION(_AC_SRC_OVER, 0, 255, _AC_SRC_ALPHA)
            size = wintypes.SIZE(w, h)
            src = wintypes.POINT(0, 0)
            # NULL destination: position is owned by desktop_layer.center_on_primary,
            # which knows how to convert once the window is parented to the desktop.
            ok = user32.UpdateLayeredWindow(
                wintypes.HWND(self._hwnd), screen_dc, None, ctypes.byref(size),
                mem_dc, ctypes.byref(src), 0, ctypes.byref(blend), _ULW_ALPHA)
            gdi32.SelectObject(mem_dc, old)
            return bool(ok)
        finally:
            gdi32.DeleteObject(dib)
            gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(0, screen_dc)

    def _place(self) -> None:
        """Put the window where it belongs. Runs after the first frame, because
        positioning measures the window and its size only settles once
        UpdateLayeredWindow has been given a frame."""
        desktop_layer.strip_window_chrome(self._hwnd)
        desktop_layer.survive_show_desktop(self._hwnd)   # stays through Win+D and the three-finger swipe
        saved = self._config_data().get("widget_pos")
        if self._draggable and isinstance(saved, (list, tuple)) and len(saved) == 2:
            desktop_layer.move_onscreen(self._hwnd, int(saved[0]), int(saved[1]))
        elif self._draggable:
            # First run: park it clear of the middle of the screen rather than
            # on top of whatever you are reading.
            sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
            desktop_layer.move_onscreen(self._hwnd, sw - self._size - 60, sh - self._size - 140)
        else:
            desktop_layer.center_on_primary(self._hwnd)
        self._placed = True

    # ---- dragging ---------------------------------------------------------

    def _on_press(self, event) -> None:
        self._drag_from = (event.x_root, event.y_root, *self._window_xy())

    def _on_drag(self, event) -> None:
        if not self._drag_from:
            return
        x0, y0, wx, wy = self._drag_from
        desktop_layer.move_onscreen(self._hwnd,
                                    wx + (event.x_root - x0), wy + (event.y_root - y0))

    def _on_release(self, _event) -> None:
        if self._drag_from:
            self._drag_from = None
            x, y = self._window_xy()
            self._save_position(x, y)

    def _window_xy(self):
        rect = wintypes.RECT()
        user32.GetWindowRect(wintypes.HWND(self._hwnd), ctypes.byref(rect))
        return rect.left, rect.top

    def _sink(self) -> None:
        """Drop the orb behind every application window.

        Repeated on every show, not once: showing the window raises it, so a
        second conversation would otherwise pop the orb on top of whatever you
        were working in.

        send_to_bottom rather than pin_to_desktop — reparenting onto the desktop
        would make this a child window, and UpdateLayeredWindow does not
        composite for child windows (the orb renders solid black). Windows keeps
        the desktop itself last, so HWND_BOTTOM lands the orb directly above the
        wallpaper and below everything else, which is what was wanted.
        """
        desktop_layer.send_to_bottom(self._hwnd)
        self._sunk_at = time.monotonic()

    def _tick(self) -> None:
        """One animation frame. Never allowed to raise.

        An exception in a tkinter callback is printed to stderr and swallowed,
        and the exe is built windowed — so stderr goes nowhere. The loop would
        simply stop and the widget would sit there invisible with no clue why.
        Anything that goes wrong is written next to the exe instead."""
        try:
            self._frame()
        except Exception:
            import traceback
            try:
                (config.app_dir() / "tron_error.log").write_text(
                    "orb tick failed:\n" + traceback.format_exc(), encoding="utf-8")
            except Exception:
                pass
            self._root.after(_FRAME_MS, self._tick)   # keep trying; do not die silently

    def _frame(self) -> None:
        if self._quitting:
            self._root.quit()
            self._root.destroy()
            return
        self._root.after(_FRAME_MS, self._tick)

        shown = bool(user32.IsWindowVisible(wintypes.HWND(self._hwnd)))
        if not self._visible:
            if shown:
                self._root.withdraw()
            return                      # hidden: no rendering, no cost

        dt = _FRAME_MS / 1000.0
        s = _STATES[self._state]
        # Ease rather than snap, so a state change reads as the orb changing its
        # mind instead of a cut.
        k = 1.0 - math.exp(-dt * 3.5)
        self._rate += (s["rate"] - self._rate) * k
        self._amt += (s["amt"] - self._amt) * k
        for i in range(3):
            self._tint[i] += (s["tint"][i] - self._tint[i]) * k

        # Integrate the phase: changing the rate would otherwise jump the
        # gradient to a different pose. The phase drives a sine, so the tilt
        # oscillates around the fitted pose instead of running away.
        self._phase += self._rate * dt
        # The ring turns; the orb only rocks, because rotating it far exposes a
        # hemisphere the fit never constrained.
        angle = self._phase * 0.45 if self._spin else math.sin(self._phase) * _WOBBLE

        target = self._audio_level if self._state == "speaking" else 0.0
        self._smoothed_level += (target - self._smoothed_level) * (
            0.35 if target > self._smoothed_level else 0.06)

        # The orb is up all day now, so redrawing an identical frame 30 times a
        # second would burn most of a core doing nothing. Skip the render *and*
        # the push when nothing that reaches the image has changed — a layered
        # window keeps its last frame, so the orb just stays as it is.
        #
        # The angle is compared in the renderer's own quantisation bucket: at
        # idle the wobble moves at most 0.039 rad/s, so it crosses a bucket only
        # a few times a second and almost every tick is a no-op.
        key = (getattr(self._renderer, "frame_id", None),     # the dust orb: a new frame is a change
               int(round(angle / orb_render.ANGLE_STEP)),
               round(self._amt, 3),
               tuple(round(c, 3) for c in self._tint),
               round(self._smoothed_level, 3))
        if key == self._last_key and shown:
            return
        self._last_key = key

        self._push(self._renderer.render(angle, tuple(self._tint), self._amt,
                                         self._smoothed_level))
        if not shown:
            self._root.deiconify()
            user32.ShowWindow(wintypes.HWND(self._hwnd), 8)   # SW_SHOWNA, no focus
            if not self._placed:
                self._place()
            if self._topmost:
                desktop_layer.keep_on_top(self._hwnd)
            else:
                self._sink()
        elif not self._topmost and time.monotonic() - self._sunk_at > 2.0:
            # Something can raise the orb above your windows (a restore after Show desktop, a click on it);
            # pushing it back down every 2 s keeps it under them. It still shows on Show desktop, because
            # the desktop owns it (desktop_layer.survive_show_desktop).
            self._sink()
