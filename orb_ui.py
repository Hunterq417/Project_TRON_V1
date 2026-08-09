# orb_ui.py
import ctypes
import threading

import webview

import config
import desktop_layer

_ORB_WIDTH = 400
_ORB_HEIGHT = 400


def _centered_position(width: int, height: int) -> tuple[int, int]:
    """Centers on the primary monitor specifically (GetSystemMetrics(SM_CXSCREEN/
    SM_CYSCREEN) always refers to the primary display, regardless of how many
    other monitors are attached) — never on whichever monitor happens to be
    treated as default by the window manager."""
    screen_w = ctypes.windll.user32.GetSystemMetrics(0)
    screen_h = ctypes.windll.user32.GetSystemMetrics(1)
    return (screen_w - width) // 2, (screen_h - height) // 2


class OrbUI:
    """Centered particle-sphere HUD reflecting TronStateMachine state, pinned to the
    desktop layer (behind every application window, like a live wallpaper) so it
    never covers whatever you're actually working on — see desktop_layer.py. Pinning
    is undocumented Windows behavior and can fail on some builds; when it does, the
    orb just stays a normal (non-topmost) window instead of crashing.

    Stays hidden while idle — pops onto the screen the moment a conversation
    starts (any non-idle state) and drops back out of sight once it ends.

    Must be run via run(), from the main thread — pywebview requires it."""

    def __init__(self):
        orb_html = config.resolve_path("orb.html")
        x, y = _centered_position(_ORB_WIDTH, _ORB_HEIGHT)
        self._window = webview.create_window(
            "TRON",
            url=str(orb_html),
            width=_ORB_WIDTH,
            height=_ORB_HEIGHT,
            x=x,
            y=y,
            frameless=True,
            transparent=True,
            on_top=False,
            easy_drag=False,
            hidden=True,
        )
        self._visible = False

    def run(self, on_ready) -> None:
        """Blocks the calling thread running pywebview's GUI loop — call this last,
        from the main thread, once everything else is constructed. on_ready runs
        once the GUI loop has started (used for the things that don't need the
        native window itself, like starting the wake trigger and tray icon)."""
        threading.Thread(target=self._pin_to_desktop_when_ready, daemon=True).start()
        webview.start(func=on_ready)

    def quit(self) -> None:
        self._window.destroy()

    def on_state_change(self, state) -> None:
        name = state.name.lower()
        try:
            self._window.evaluate_js(f"setState('{name}')")
        except Exception:
            pass  # window may not be ready yet, or has been closed — non-fatal, purely visual

        if name == "idle":
            self._hide()
        else:
            self._show()

    def on_audio_level(self, level: float) -> None:
        try:
            self._window.evaluate_js(f"setAudioLevel({level})")
        except Exception:
            pass  # same non-fatal reasoning as on_state_change — purely visual

    def toggle_visibility(self) -> None:
        self._hide() if self._visible else self._show()

    def _show(self) -> None:
        if not self._visible:
            self._window.show()
            self._visible = True

    def _hide(self) -> None:
        if self._visible:
            self._window.hide()
            self._visible = False

    def _pin_to_desktop_when_ready(self) -> None:
        if not self._window.events.shown.wait(15):
            return
        try:
            hwnd = int(self._window.native.Handle.ToInt64())
        except Exception:
            return
        desktop_layer.pin_to_desktop(hwnd)
