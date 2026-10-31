# browser_session.py
"""TRON's own connection to a real browser: Brave, driven through the Chrome DevTools Protocol by Playwright.

Why not the Windows accessibility tree any more: a video player's controls usually live in an iframe from
another site (Miruro's player is one), and Windows never sees inside it. Over CDP, Playwright can read every
frame, the page's accessible names and its <video> elements, and check what really happened.

Safety choices:
* A separate TRON browser profile (<TRON folder>/browser_profile). Your everyday Brave profile, its logins
  and sessions are never touched. (Recent Chromium refuses remote debugging on the default profile anyway.)
* The debugging port listens on 127.0.0.1 only: nothing on your network can reach it. Any program running
  on this PC as you could, while the TRON browser is open, so log in there only to sites you'd let TRON use.
* All browser work happens on one worker thread, which owns the Playwright connection: Playwright's sync API
  can't be called from inside an asyncio loop, and Gemini conversations run inside one.
"""
import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path

import config

PORT = 9222
HOST = "127.0.0.1"          # loopback only, never 0.0.0.0
ENDPOINT = f"http://{HOST}:{PORT}"


class BrowserUnavailable(RuntimeError):
    """The TRON browser isn't running or can't be reached. The message says what to do."""


def profile_dir() -> Path:
    return config.app_dir() / "browser_profile"


def brave_path():
    for candidate in (os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
                      os.path.expandvars(r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe"),
                      os.path.expandvars(r"%ProgramFiles(x86)%\BraveSoftware\Brave-Browser\Application\brave.exe")):
        if os.path.exists(candidate):
            return candidate
    return shutil.which("brave")


def healthy(timeout: float = 1.5) -> bool:
    """True when a browser answers on TRON's loopback debugging port."""
    import requests
    try:
        return requests.get(f"{_worker.endpoint}/json/version", timeout=timeout).ok
    except Exception:
        return False


def launch(url: str = "") -> str:
    """Opens the TRON browser (Brave, TRON's own profile, loopback debugging). Returns a status sentence."""
    if healthy():
        return "the TRON browser is already open, sir"
    exe = brave_path()
    if not exe:
        raise BrowserUnavailable("Brave isn't installed where I can find it, sir")
    profile_dir().mkdir(parents=True, exist_ok=True)
    args = [exe, f"--remote-debugging-port={PORT}", f"--remote-debugging-address={HOST}",
            f"--user-data-dir={profile_dir()}", "--no-first-run", "--no-default-browser-check"]
    subprocess.Popen(args + ([url] if url else []), close_fds=True)
    import time
    deadline = time.time() + 15
    while time.time() < deadline:
        if healthy(0.5):
            return "opened the TRON browser, sir"
        time.sleep(0.3)
    raise BrowserUnavailable("I started Brave but its debugging port didn't answer. Close every Brave window "
                             "using the TRON profile and try again, sir")


# --------------------------------------------------------------------------- the worker thread
class _Worker:
    def __init__(self):
        self._jobs: queue.Queue = queue.Queue()
        self._thread = None
        self._pw = self._browser = None
        self.endpoint = ENDPOINT

    def _run(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        while True:
            fn, box, done = self._jobs.get()
            try:
                box["value"] = fn(self)
            except BaseException as exc:   # handed back to the caller's thread, never lost here
                box["error"] = exc
            done.set()

    def browser(self):
        """The CDP connection, made on first use and remade if the browser was closed and reopened."""
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        if not healthy():
            raise BrowserUnavailable("The TRON browser isn't open. Say 'open the TRON browser', or start it "
                                     "from the control panel, then open your video there, sir")
        try:
            # attaching to every frame of a busy page (ads, players) can take a while on a page still loading
            self._browser = self._pw.chromium.connect_over_cdp(self.endpoint, timeout=20000)
        except Exception as exc:
            raise BrowserUnavailable(f"I couldn't connect to the TRON browser ({type(exc).__name__}); give the page "
                                     "a moment to load and ask again, sir") from exc
        return self._browser

    def call(self, fn, timeout: float = 45.0):
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, daemon=True, name="tron-browser")
            self._thread.start()
        box, done = {}, threading.Event()
        self._jobs.put((fn, box, done))
        if not done.wait(timeout):
            raise TimeoutError("the browser didn't respond in time")
        if "error" in box:
            raise box["error"]
        return box.get("value")


_worker = _Worker()


def run(fn, timeout: float = 45.0):
    """Runs fn(worker) on the browser thread and returns its result (exceptions come back here)."""
    return _worker.call(fn, timeout)


def use_endpoint(endpoint: str) -> None:
    """Points the worker at another CDP endpoint (tests: a headless Brave on a spare port)."""
    _worker.endpoint = endpoint
    _worker._browser = None


def active_page(worker):
    """The tab the user is looking at: the visible one with a video if any, else the last visible one."""
    pages = [p for ctx in worker.browser().contexts for p in ctx.pages if not p.url.startswith("devtools://")]
    if not pages:
        raise BrowserUnavailable("the TRON browser has no tabs open, sir")
    visible = []
    for page in pages:
        try:
            if page.evaluate("document.visibilityState") == "visible":
                visible.append(page)
        except Exception:
            continue
    candidates = visible or pages
    for page in candidates:
        try:
            if any(f.evaluate("!!document.querySelector('video')") for f in page.frames if not f.is_detached()):
                return page
        except Exception:
            continue
    return candidates[-1]
