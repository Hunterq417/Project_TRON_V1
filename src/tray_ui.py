# tray_ui.py
import threading
from typing import Callable

from PIL import Image, ImageDraw
import pystray

import config

_COLORS = {
    "idle": (235, 235, 235),      # white/gray — waiting for the hotkey
    "listening": (66, 133, 244),  # blue — mic capturing your speech
    "thinking": (255, 193, 7),    # amber — paused/waiting on Gemini
    "speaking": (52, 199, 89),    # green — TRON's reply is playing
    "acting": (155, 89, 182),     # purple — a tool is actively running
    "error": (220, 53, 69),       # red — network/API failure this turn
    "dictating": (239, 68, 68),   # red — recording a dictation
}


def _make_icon_image(color) -> Image.Image:
    img = Image.new("RGB", (64, 64), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((8, 8, 56, 56), fill=color)
    return img


class TrayUI:
    """System tray icon reflecting TronStateMachine state. Runs pystray's blocking loop on its own thread."""

    def __init__(self, quit_callback: Callable[[], None],
                 toggle_orb_callback: Callable[[], None] | None = None,
                 dashboard_callback: Callable[[], None] | None = None,
                 panel_callback: Callable[[], None] | None = None):
        menu_items = []
        if panel_callback is not None:
            menu_items.append(pystray.MenuItem("Control Panel", lambda: panel_callback(), default=True))
        if dashboard_callback is not None:
            menu_items.append(pystray.MenuItem("Web Dashboard", lambda: dashboard_callback(),
                                               default=panel_callback is None))
        if toggle_orb_callback is not None:
            menu_items.append(pystray.MenuItem("Show/Hide Orb", lambda: toggle_orb_callback()))
        menu_items.append(pystray.MenuItem("Quit", lambda: quit_callback()))

        self._icon = pystray.Icon(
            "tron",
            icon=_make_icon_image(_COLORS["idle"]),
            title=f"{config.APP_LABEL}: idle",
            menu=pystray.Menu(*menu_items),
        )
        self._thread = threading.Thread(target=self._icon.run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._icon.stop()

    def notify(self, message: str, title: str = config.APP_NAME) -> None:
        """A Windows notification from the tray icon. Best effort: never fails the caller."""
        try:
            self._icon.notify(message, title)
        except Exception:
            pass

    def on_state_change(self, state) -> None:
        name = state.name.lower()
        color = _COLORS.get(name, _COLORS["idle"])
        self._icon.icon = _make_icon_image(color)
        self._icon.title = f"{config.APP_LABEL}: {name}"
