# dust_orb.py
"""The Dust Orb face: Ship Notes' dust-orb v2 (MIT, three.js/WebGL), shown exactly like the Aurora Orb.

WebGL needs a browser, and a browser window on Windows can't be see-through (an Edge WebView came out white,
and colour-keying it made the whole window vanish). So the orb is drawn in a headless Brave on a transparent
page, and its frames are handed to orb_ui's own per-pixel-alpha window - the same window, placement and
desktop pinning as the Aurora Orb. TRON's state and voice level go to the page as they change.
"""
import sys
import threading
import time
from pathlib import Path

import numpy as np

FPS = 24


def asset_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "assets" / "dust_orb"


class DustRenderer:
    """render() returns the newest frame as premultiplied BGRA (what UpdateLayeredWindow wants)."""

    def __init__(self, size: int):
        self.size = size
        self._frame = np.zeros((size, size, 4), np.uint8)
        self.frame_id = 0
        self._state, self._level, self._sent = "idle", 0.0, (None, None)
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="dust-orb").start()

    def set_state(self, name: str) -> None:
        self._state = name

    def close(self) -> None:
        self._stop.set()

    def render(self, angle=0.0, tint=None, amount=0.0, level=0.0):
        self._level = level
        return self._frame

    def _run(self):
        import base64
        import io
        from PIL import Image
        from playwright.sync_api import sync_playwright
        import browser_session
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=browser_session.brave_path(), headless=True,
                                             args=["--use-angle=d3d11", "--enable-gpu", "--ignore-gpu-blocklist"])
                page = browser.new_page(viewport={"width": self.size, "height": self.size})
                page.goto((asset_dir() / "tron.html").as_uri())
                cdp = page.context.new_cdp_session(page)
                cdp.send("Emulation.setDefaultBackgroundColorOverride", {"color": {"r": 0, "g": 0, "b": 0, "a": 0}})
                page.wait_for_function("() => !!document.getElementById('orb').setState", timeout=15000)
                while not self._stop.is_set():
                    started = time.time()
                    wanted = (self._state, round(self._level, 2))
                    if wanted != self._sent:
                        page.evaluate("([s, l]) => window.tron(s, l)", list(wanted))
                        self._sent = wanted
                    shot = cdp.send("Page.captureScreenshot", {"format": "png"})
                    rgba = np.asarray(Image.open(io.BytesIO(base64.b64decode(shot["data"]))).convert("RGBA"))
                    alpha = rgba[..., 3:4].astype(np.uint16)
                    bgra = np.empty_like(rgba)
                    bgra[..., :3] = (rgba[..., 2::-1].astype(np.uint16) * alpha // 255).astype(np.uint8)
                    bgra[..., 3] = rgba[..., 3]
                    self._frame = np.ascontiguousarray(bgra)
                    self.frame_id += 1
                    time.sleep(max(0.0, 1 / FPS - (time.time() - started)))
                browser.close()
        except Exception:
            import traceback
            import config
            try:
                with (config.app_dir() / "tron_error.log").open("a", encoding="utf-8") as log:
                    log.write("\n===== dust orb failed =====\n" + traceback.format_exc())
            except Exception:
                pass
