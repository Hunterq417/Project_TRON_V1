# orb_ui.py
import threading

import webview

import config

_ORB_WIDTH = 400
_ORB_HEIGHT = 400


class OrbUI:
    """Centered, always-on-top particle-sphere HUD reflecting TronStateMachine state.

    Stays hidden while idle — pops onto the screen the moment a conversation
    starts (any non-idle state) and drops back out of sight once it ends."""

    def __init__(self):
        orb_html = config.resolve_path("orb.html")
        self._window = webview.create_window(
            "TRON",
            url=str(orb_html),
            width=_ORB_WIDTH,
            height=_ORB_HEIGHT,
            frameless=True,
            transparent=True,
            on_top=True,
            easy_drag=False,
            hidden=True,
        )
        self._thread = threading.Thread(target=webview.start, daemon=True)
        self._visible = False

    def start(self) -> None:
        self._thread.start()

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
