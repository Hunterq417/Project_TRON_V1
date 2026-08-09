# tray_ui.py
import threading
from typing import Callable

from PIL import Image, ImageDraw
import pystray

_COLORS = {
    "idle": (235, 235, 235),      # white/gray — waiting for the hotkey
    "listening": (66, 133, 244),  # blue — mic capturing your speech
    "thinking": (255, 193, 7),    # amber — paused/waiting on Gemini
    "speaking": (52, 199, 89),    # green — TRON's reply is playing
    "error": (220, 53, 69),       # red — network/API failure this turn
}


def _make_icon_image(color) -> Image.Image:
    img = Image.new("RGB", (64, 64), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((8, 8, 56, 56), fill=color)
    return img


class TrayUI:
    """System tray icon reflecting TronStateMachine state. Runs pystray's blocking loop on its own thread."""

    def __init__(self, quit_callback: Callable[[], None]):
        self._icon = pystray.Icon(
            "tron",
            icon=_make_icon_image(_COLORS["idle"]),
            title="TRON: idle",
            menu=pystray.Menu(pystray.MenuItem("Quit", lambda: quit_callback())),
        )
        self._thread = threading.Thread(target=self._icon.run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._icon.stop()

    def on_state_change(self, state) -> None:
        name = state.name.lower()
        color = _COLORS.get(name, _COLORS["idle"])
        self._icon.icon = _make_icon_image(color)
        self._icon.title = f"TRON: {name}"
