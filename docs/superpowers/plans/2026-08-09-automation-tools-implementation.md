# Automation/Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** TRON can open apps/files/games, control media playback (including a best-effort seek), search the web, and draft-then-send email — all via Gemini Live tool-calling — per `docs/superpowers/specs/2026-08-09-automation-tools-design.md`. Builds directly on top of the Voice Core built in the previous plan (same repo, same branch lineage).

**Architecture:** `GeminiLiveSession.receive()` changes from yielding raw audio bytes to yielding tagged events (`audio`/`tool_call`/`turn_complete`). `TronStateMachine`'s `recv_loop` dispatches `tool_call` events through `tools.TOOL_DISPATCH`, driving a new `ACTING` (purple) tray state while a tool runs, then reports the result back via `send_tool_response()`.

**Tech Stack:** Same as Voice Core, no new third-party dependencies — `app_index`/`media_control`/`email_client` are stdlib (`difflib`, `os`, `smtplib`) plus the already-installed `keyboard` package.

## Global Constraints

- No new pip dependencies — everything new is stdlib, or reuses `keyboard` (already installed).
- `send_email` never fires without a prior `draft_email` call and spoken confirmation in the same conversation — enforced via the persona prompt (`persona.txt`), not app code. This is a documented limitation, not a hard guarantee (see spec's error-handling table).
- Tool functions never raise for expected failure modes (unresolvable app name, SMTP failure, seek beyond cap) — they return a plain string explaining what happened, so Gemini can relay it as speech instead of the process crashing.
- `ACTING` (purple, `(155, 89, 182)`) is a new tray state for "a tool is currently running," distinct from `THINKING` (waiting on Gemini) — extends `tray_ui._COLORS` and `state_manager.State`, both established in the Voice Core plan.
- Every `TOOL_DISPATCH` entry has the uniform signature `(args: dict, cfg: Config | None) -> str`, even tools that ignore `cfg` — one calling convention, no per-tool special-casing in `state_manager.py`.

---

### Task 1: App/file launcher index

**Files:**
- Create: `app_index.py`
- Test: `tests/test_app_index.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `app_index.build_index(startmenu_dirs: list[Path] | None = None, home: Path | None = None) -> dict[str, Path]`, `app_index.resolve(query: str, index: dict[str, Path]) -> Path | None`, `app_index.launch(path: Path) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_app_index.py
from pathlib import Path
from unittest.mock import MagicMock

import app_index


def test_build_index_scans_startmenu_and_media_folders(tmp_path):
    startmenu = tmp_path / "startmenu"
    (startmenu / "sub").mkdir(parents=True)
    (startmenu / "Notepad.lnk").write_text("")
    (startmenu / "sub" / "Chess Titans.lnk").write_text("")

    home = tmp_path / "home"
    (home / "Pictures").mkdir(parents=True)
    (home / "Pictures" / "dune poster.jpg").write_text("")
    (home / "Videos").mkdir(parents=True)

    index = app_index.build_index(startmenu_dirs=[startmenu], home=home)

    assert index["notepad"] == startmenu / "Notepad.lnk"
    assert index["chess titans"] == startmenu / "sub" / "Chess Titans.lnk"
    assert index["dune poster"] == home / "Pictures" / "dune poster.jpg"


def test_build_index_skips_missing_directories(tmp_path):
    index = app_index.build_index(startmenu_dirs=[tmp_path / "nope"], home=tmp_path / "also-nope")
    assert index == {}


def test_resolve_fuzzy_matches_closest_name():
    index = {
        "notepad": Path("C:/x/notepad.lnk"),
        "chrome": Path("C:/x/chrome.lnk"),
    }

    assert app_index.resolve("note pad", index) == Path("C:/x/notepad.lnk")
    assert app_index.resolve("chrom", index) == Path("C:/x/chrome.lnk")


def test_resolve_returns_none_when_nothing_close():
    index = {"notepad": Path("C:/x/notepad.lnk")}
    assert app_index.resolve("completely unrelated query", index) is None


def test_resolve_returns_none_for_empty_index():
    assert app_index.resolve("anything", {}) is None


def test_launch_calls_os_startfile(monkeypatch):
    fake_startfile = MagicMock()
    monkeypatch.setattr(app_index.os, "startfile", fake_startfile, raising=False)

    app_index.launch(Path("C:/x/notepad.lnk"))

    fake_startfile.assert_called_once_with("C:\\x\\notepad.lnk")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\pytest tests/test_app_index.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app_index'`

- [ ] **Step 3: Write `app_index.py`**

```python
# app_index.py
import difflib
import os
from pathlib import Path
from typing import Dict, List, Optional

_MEDIA_FOLDER_NAMES = ["Pictures", "Videos", "Desktop", "Documents"]


def _default_startmenu_dirs() -> List[Path]:
    dirs = []
    for env_var in ("PROGRAMDATA", "APPDATA"):
        base = os.environ.get(env_var)
        if base:
            dirs.append(Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return dirs


def build_index(
    startmenu_dirs: Optional[List[Path]] = None,
    home: Optional[Path] = None,
) -> Dict[str, Path]:
    """Scans Start Menu shortcuts and common user folders into a name -> path index."""
    startmenu_dirs = startmenu_dirs if startmenu_dirs is not None else _default_startmenu_dirs()
    home = home if home is not None else Path.home()

    index: Dict[str, Path] = {}

    for base in startmenu_dirs:
        if not base.exists():
            continue
        for path in base.rglob("*.lnk"):
            index[path.stem.lower()] = path

    for folder_name in _MEDIA_FOLDER_NAMES:
        folder = home / folder_name
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            if path.is_file():
                index[path.stem.lower()] = path

    return index


def resolve(query: str, index: Dict[str, Path]) -> Optional[Path]:
    """Fuzzy-matches a spoken name against the index. Returns the best match or None."""
    if not index:
        return None
    matches = difflib.get_close_matches(query.lower(), index.keys(), n=1, cutoff=0.5)
    return index[matches[0]] if matches else None


def launch(path: Path) -> None:
    os.startfile(str(path))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\pytest tests/test_app_index.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add app_index.py tests/test_app_index.py
git commit -m "Add app/file launcher index with fuzzy name matching"
```

---

### Task 2: Media playback control

**Files:**
- Create: `media_control.py`
- Test: `tests/test_media_control.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `media_control.play_pause() -> str`, `media_control.next_track() -> str`, `media_control.previous_track() -> str`, `media_control.seek(direction: str, seconds: int = 10) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_media_control.py
from unittest.mock import MagicMock

import media_control


def test_play_pause_sends_media_key(monkeypatch):
    fake_send = MagicMock()
    monkeypatch.setattr(media_control.keyboard, "send", fake_send)

    result = media_control.play_pause()

    fake_send.assert_called_once_with("play/pause media")
    assert "toggled" in result.lower()


def test_next_and_previous_send_correct_keys(monkeypatch):
    fake_send = MagicMock()
    monkeypatch.setattr(media_control.keyboard, "send", fake_send)

    media_control.next_track()
    fake_send.assert_called_with("next track")

    media_control.previous_track()
    fake_send.assert_called_with("previous track")


def test_seek_within_cap_presses_arrow_key_proportionally(monkeypatch):
    fake_send = MagicMock()
    monkeypatch.setattr(media_control.keyboard, "send", fake_send)
    monkeypatch.setattr(media_control.time, "sleep", MagicMock())

    result = media_control.seek("forward", seconds=15)

    # 15s / 5s-per-press = 3 presses of the right-arrow key
    assert fake_send.call_count == 3
    fake_send.assert_called_with("right")
    assert "forward" in result.lower()


def test_seek_backward_uses_left_arrow(monkeypatch):
    fake_send = MagicMock()
    monkeypatch.setattr(media_control.keyboard, "send", fake_send)
    monkeypatch.setattr(media_control.time, "sleep", MagicMock())

    media_control.seek("backward", seconds=5)

    fake_send.assert_called_with("left")


def test_seek_beyond_cap_explains_instead_of_spamming_keys(monkeypatch):
    fake_send = MagicMock()
    monkeypatch.setattr(media_control.keyboard, "send", fake_send)

    result = media_control.seek("forward", seconds=600)

    fake_send.assert_not_called()
    assert "60" in result or "minute" in result.lower() or "manually" in result.lower()


def test_seek_unknown_direction_returns_explanation(monkeypatch):
    fake_send = MagicMock()
    monkeypatch.setattr(media_control.keyboard, "send", fake_send)

    result = media_control.seek("sideways", seconds=10)

    fake_send.assert_not_called()
    assert "forward" in result.lower() and "backward" in result.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\pytest tests/test_media_control.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'media_control'`

- [ ] **Step 3: Write `media_control.py`**

```python
# media_control.py
import time

import keyboard

_SEEK_KEY = {"forward": "right", "backward": "left"}
_MAX_SEEK_SECONDS = 60
_SECONDS_PER_KEYPRESS = 5
_KEYPRESS_DELAY_S = 0.05


def play_pause() -> str:
    keyboard.send("play/pause media")
    return "toggled playback"


def next_track() -> str:
    keyboard.send("next track")
    return "skipped to the next track"


def previous_track() -> str:
    keyboard.send("previous track")
    return "went back to the previous track"


def seek(direction: str, seconds: int = 10) -> str:
    if direction not in _SEEK_KEY:
        return f'unknown seek direction "{direction}", sir — use "forward" or "backward"'
    if seconds > _MAX_SEEK_SECONDS:
        return (
            f"I can only nudge playback by simulated keystrokes, up to about "
            f"{_MAX_SEEK_SECONDS} seconds, sir — a jump that large will need to be done manually."
        )
    presses = max(1, round(seconds / _SECONDS_PER_KEYPRESS))
    key = _SEEK_KEY[direction]
    for _ in range(presses):
        keyboard.send(key)
        time.sleep(_KEYPRESS_DELAY_S)
    return f"skipped {direction} about {presses * _SECONDS_PER_KEYPRESS} seconds"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\pytest tests/test_media_control.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add media_control.py tests/test_media_control.py
git commit -m "Add media playback control (play/pause/skip/seek)"
```

---

### Task 3: Email client + config fields

**Files:**
- Create: `email_client.py`
- Modify: `config.py`
- Modify: `config.example.json`
- Test: `tests/test_email_client.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `email_client.draft_email(to: str, subject: str, body: str) -> str`, `email_client.send_email(to: str, subject: str, body: str, smtp_host: str, smtp_port: int, smtp_user: str, smtp_app_password: str) -> str`. `config.Config` gains fields `smtp_host: str`, `smtp_port: int`, `smtp_user: str`, `smtp_app_password: str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_email_client.py
from unittest.mock import MagicMock

import email_client


def test_draft_email_formats_readable_text():
    draft = email_client.draft_email("alex@example.com", "Running late", "Be there in 20.")

    assert "alex@example.com" in draft
    assert "Running late" in draft
    assert "Be there in 20." in draft


def test_send_email_success(monkeypatch):
    fake_server = MagicMock()
    fake_smtp_cm = MagicMock()
    fake_smtp_cm.__enter__ = MagicMock(return_value=fake_server)
    fake_smtp_cm.__exit__ = MagicMock(return_value=False)
    fake_smtp_ssl = MagicMock(return_value=fake_smtp_cm)
    monkeypatch.setattr(email_client.smtplib, "SMTP_SSL", fake_smtp_ssl)

    result = email_client.send_email(
        to="alex@example.com", subject="Running late", body="Be there in 20.",
        smtp_host="smtp.example.com", smtp_port=465,
        smtp_user="me@example.com", smtp_app_password="app-pw",
    )

    fake_smtp_ssl.assert_called_once_with("smtp.example.com", 465)
    fake_server.login.assert_called_once_with("me@example.com", "app-pw")
    fake_server.send_message.assert_called_once()
    assert "sent" in result.lower()
    assert "alex@example.com" in result


def test_send_email_failure_returns_message_instead_of_raising(monkeypatch):
    fake_smtp_ssl = MagicMock(side_effect=OSError("connection refused"))
    monkeypatch.setattr(email_client.smtplib, "SMTP_SSL", fake_smtp_ssl)

    result = email_client.send_email(
        to="alex@example.com", subject="s", body="b",
        smtp_host="smtp.example.com", smtp_port=465,
        smtp_user="me@example.com", smtp_app_password="app-pw",
    )

    assert "failed" in result.lower()
    assert "connection refused" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\pytest tests/test_email_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'email_client'`

- [ ] **Step 3: Write `email_client.py`**

```python
# email_client.py
import smtplib
from email.mime.text import MIMEText


def draft_email(to: str, subject: str, body: str) -> str:
    return f"To: {to}\nSubject: {subject}\n\n{body}"


def send_email(
    to: str, subject: str, body: str,
    smtp_host: str, smtp_port: int, smtp_user: str, smtp_app_password: str,
) -> str:
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to
    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(smtp_user, smtp_app_password)
            server.send_message(msg)
    except Exception as exc:
        return f"failed to send: {exc}"
    return f"sent to {to}"
```

- [ ] **Step 4: Modify `config.py`** — add SMTP fields to `Config` and `load_config`

```python
# config.py
import json
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"


@dataclass
class Config:
    gemini_api_key: str
    wake_mode: str
    hotkey: str
    wakeword_model_path: str
    persona_path: str
    silence_timeout_s: float
    voice_name: str
    model_name: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_app_password: str


def load_config() -> Config:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Missing {CONFIG_PATH}. Copy config.example.json to config.json "
            "and fill in gemini_api_key."
        )
    data = json.loads(CONFIG_PATH.read_text())
    return Config(
        gemini_api_key=data["gemini_api_key"],
        wake_mode=data.get("wake_mode", "hotkey"),
        hotkey=data.get("hotkey", "ctrl+alt+t"),
        wakeword_model_path=data.get("wakeword_model_path", "models/tron.onnx"),
        persona_path=data.get("persona_path", "persona.txt"),
        silence_timeout_s=data.get("silence_timeout_s", 45.0),
        voice_name=data.get("voice_name", "Charon"),
        model_name=data.get("model_name", "gemini-2.0-flash-live-001"),
        smtp_host=data.get("smtp_host", ""),
        smtp_port=data.get("smtp_port", 465),
        smtp_user=data.get("smtp_user", ""),
        smtp_app_password=data.get("smtp_app_password", ""),
    )
```

Existing `tests/test_config.py` is unaffected — it only checks a subset of fields, and the new ones default via `.get()`, so no config file lacking them breaks.

- [ ] **Step 5: Modify `config.example.json`**

```json
{
  "gemini_api_key": "YOUR_GEMINI_API_KEY_HERE",
  "wake_mode": "hotkey",
  "hotkey": "ctrl+alt+t",
  "wakeword_model_path": "models/tron.onnx",
  "persona_path": "persona.txt",
  "silence_timeout_s": 45.0,
  "voice_name": "Charon",
  "model_name": "gemini-2.0-flash-live-001",
  "smtp_host": "smtp.gmail.com",
  "smtp_port": 465,
  "smtp_user": "YOUR_EMAIL@gmail.com",
  "smtp_app_password": "YOUR_16_CHAR_APP_PASSWORD"
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv\Scripts\pytest tests/test_email_client.py tests/test_config.py -v`
Expected: PASS (5 tests: 3 new + 2 existing)

- [ ] **Step 7: Commit**

```bash
git add email_client.py config.py config.example.json tests/test_email_client.py
git commit -m "Add email client and SMTP config fields"
```

---

### Task 4: Tool registry (declarations + dispatch)

**Files:**
- Create: `tools.py`
- Test: `tests/test_tools.py`

**Interfaces:**
- Consumes: `app_index.build_index/resolve/launch`, `media_control.play_pause/next_track/previous_track/seek`, `email_client.draft_email/send_email`, `config.Config`
- Produces: `tools.TOOL_DECLARATIONS: list[dict]` (Gemini function-declaration schemas), `tools.TOOL_DISPATCH: dict[str, Callable[[dict, Config | None], str]]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tools.py
from pathlib import Path
from unittest.mock import MagicMock

import tools


def test_every_declaration_has_a_matching_dispatch_entry():
    declared_names = {d["name"] for d in tools.TOOL_DECLARATIONS}
    dispatched_names = set(tools.TOOL_DISPATCH.keys())
    assert declared_names == dispatched_names


def test_open_target_found(monkeypatch):
    monkeypatch.setattr(tools, "_APP_INDEX_CACHE", {"notepad": Path("C:/x/notepad.lnk")})
    fake_launch = MagicMock()
    monkeypatch.setattr(tools.app_index, "launch", fake_launch)

    result = tools.TOOL_DISPATCH["open_target"]({"name": "notepad"}, None)

    fake_launch.assert_called_once_with(Path("C:/x/notepad.lnk"))
    assert "notepad" in result.lower()


def test_open_target_not_found(monkeypatch):
    monkeypatch.setattr(tools, "_APP_INDEX_CACHE", {"notepad": Path("C:/x/notepad.lnk")})

    result = tools.TOOL_DISPATCH["open_target"]({"name": "spreadsheet thing"}, None)

    assert "could not find" in result.lower()


def test_web_search_opens_browser(monkeypatch):
    fake_open = MagicMock()
    monkeypatch.setattr(tools.webbrowser, "open", fake_open)

    result = tools.TOOL_DISPATCH["web_search"]({"query": "weather today"}, None)

    (called_url,), _ = fake_open.call_args
    assert "weather" in called_url
    assert "weather" in result.lower()


def test_media_tools_delegate_to_media_control(monkeypatch):
    fake_play_pause = MagicMock(return_value="toggled playback")
    monkeypatch.setattr(tools.media_control, "play_pause", fake_play_pause)

    result = tools.TOOL_DISPATCH["media_play_pause"]({}, None)

    fake_play_pause.assert_called_once()
    assert result == "toggled playback"


def test_media_seek_passes_args_through(monkeypatch):
    fake_seek = MagicMock(return_value="skipped forward about 10 seconds")
    monkeypatch.setattr(tools.media_control, "seek", fake_seek)

    tools.TOOL_DISPATCH["media_seek"]({"direction": "forward", "seconds": 10}, None)

    fake_seek.assert_called_once_with("forward", 10)


def test_draft_email_delegates(monkeypatch):
    fake_draft = MagicMock(return_value="Draft text")
    monkeypatch.setattr(tools.email_client, "draft_email", fake_draft)

    result = tools.TOOL_DISPATCH["draft_email"](
        {"to": "a@b.com", "subject": "s", "body": "b"}, None
    )

    fake_draft.assert_called_once_with("a@b.com", "s", "b")
    assert result == "Draft text"


def test_send_email_uses_cfg_smtp_settings(monkeypatch):
    fake_send = MagicMock(return_value="sent to a@b.com")
    monkeypatch.setattr(tools.email_client, "send_email", fake_send)

    fake_cfg = MagicMock(
        smtp_host="smtp.example.com", smtp_port=465,
        smtp_user="me@example.com", smtp_app_password="pw",
    )

    tools.TOOL_DISPATCH["send_email"]({"to": "a@b.com", "subject": "s", "body": "b"}, fake_cfg)

    fake_send.assert_called_once_with(
        "a@b.com", "s", "b",
        smtp_host="smtp.example.com", smtp_port=465,
        smtp_user="me@example.com", smtp_app_password="pw",
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\pytest tests/test_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools'`

- [ ] **Step 3: Write `tools.py`**

```python
# tools.py
import urllib.parse
import webbrowser

import app_index
import email_client
import media_control

_APP_INDEX_CACHE = None


def _get_app_index():
    global _APP_INDEX_CACHE
    if _APP_INDEX_CACHE is None:
        _APP_INDEX_CACHE = app_index.build_index()
    return _APP_INDEX_CACHE


def _open_target(args, cfg):
    name = args["name"]
    path = app_index.resolve(name, _get_app_index())
    if path is None:
        return f'could not find anything called "{name}", sir'
    app_index.launch(path)
    return f'opened "{path.stem}"'


def _web_search(args, cfg):
    query = args["query"]
    url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
    webbrowser.open(url)
    return f'opened a search for "{query}"'


def _media_play_pause(args, cfg):
    return media_control.play_pause()


def _media_next(args, cfg):
    return media_control.next_track()


def _media_previous(args, cfg):
    return media_control.previous_track()


def _media_seek(args, cfg):
    return media_control.seek(args["direction"], args.get("seconds", 10))


def _draft_email(args, cfg):
    return email_client.draft_email(args["to"], args["subject"], args["body"])


def _send_email(args, cfg):
    return email_client.send_email(
        args["to"], args["subject"], args["body"],
        smtp_host=cfg.smtp_host, smtp_port=cfg.smtp_port,
        smtp_user=cfg.smtp_user, smtp_app_password=cfg.smtp_app_password,
    )


TOOL_DISPATCH = {
    "open_target": _open_target,
    "web_search": _web_search,
    "media_play_pause": _media_play_pause,
    "media_next": _media_next,
    "media_previous": _media_previous,
    "media_seek": _media_seek,
    "draft_email": _draft_email,
    "send_email": _send_email,
}

TOOL_DECLARATIONS = [
    {
        "name": "open_target",
        "description": "Open an application, file, photo, video, or game by name.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "What to open, as spoken by the user."}
            },
            "required": ["name"],
        },
    },
    {
        "name": "web_search",
        "description": "Search the web for a query and open the results in the browser.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "media_play_pause",
        "description": "Toggle play/pause on whatever media is currently playing.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "media_next",
        "description": "Skip to the next track.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "media_previous",
        "description": "Go to the previous track.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "media_seek",
        "description": (
            "Seek forward or backward in the currently focused video/media player, by "
            "roughly the given number of seconds (best-effort, capped at about 60 seconds)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["forward", "backward"]},
                "seconds": {
                    "type": "integer",
                    "description": "Roughly how many seconds to skip. Defaults to 10.",
                },
            },
            "required": ["direction"],
        },
    },
    {
        "name": "draft_email",
        "description": (
            "Compose an email draft and return its text for you to read back to the user. "
            "Always call this before send_email, read the draft back verbatim, and wait "
            "for explicit confirmation before calling send_email."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "send_email",
        "description": (
            "Actually send an email. Only call this after draft_email was called, the "
            "draft was read back to the user, and the user explicitly confirmed sending it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
    },
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\pytest tests/test_tools.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add tools.py tests/test_tools.py
git commit -m "Add tool registry: declarations + dispatch table"
```

---

### Task 5: Gemini Live client — tool-calling support

**Files:**
- Modify: `gemini_live_client.py`
- Modify: `tests/test_gemini_live_client.py` (full rewrite — event shape changes)

**Interfaces:**
- Consumes: nothing new
- Produces (changed from Voice Core): `GeminiLiveSession(api_key, model_name, voice_name, system_instruction, tools: list[dict] | None = None)`. `receive()` now yields `dict` events: `{"type": "audio", "data": bytes}`, `{"type": "tool_call", "calls": [{"id": str, "name": str, "args": dict}]}`, `{"type": "turn_complete"}` — replaces the old bytes-with-`b""`-sentinel shape. New method: `await session.send_tool_response(call_id: str, name: str, result: str) -> None`.

- [ ] **Step 1: Write the failing test (replaces the whole file)**

```python
# tests/test_gemini_live_client.py
import asyncio
from unittest.mock import MagicMock

import gemini_live_client as glc


def _audio_response(data):
    resp = MagicMock()
    resp.data = data
    resp.tool_call = None
    resp.server_content = MagicMock()
    resp.server_content.turn_complete = False
    return resp


def _tool_call_response(calls):
    resp = MagicMock()
    resp.data = None
    resp.tool_call = MagicMock()
    resp.tool_call.function_calls = [
        MagicMock(id=c["id"], name=c["name"], args=c["args"]) for c in calls
    ]
    resp.server_content = None
    return resp


def _turn_complete_response():
    resp = MagicMock()
    resp.data = None
    resp.tool_call = None
    resp.server_content = MagicMock()
    resp.server_content.turn_complete = True
    return resp


class FakeLiveSession:
    def __init__(self, responses):
        self.sent_audio = []
        self.sent_tool_responses = []
        self._responses = responses

    async def send_realtime_input(self, audio):
        self.sent_audio.append(audio)

    async def send_tool_response(self, function_responses):
        self.sent_tool_responses.append(function_responses)

    async def receive(self):
        for resp in self._responses:
            yield resp


class FakeConnectCM:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _connect(monkeypatch, fake_session):
    fake_client = MagicMock()
    fake_client.aio.live.connect = MagicMock(return_value=FakeConnectCM(fake_session))
    monkeypatch.setattr(glc.genai, "Client", MagicMock(return_value=fake_client))


def test_receive_yields_audio_then_turn_complete_events(monkeypatch):
    fake_session = FakeLiveSession([_audio_response(b"hello-audio"), _turn_complete_response()])
    _connect(monkeypatch, fake_session)

    async def run():
        async with glc.GeminiLiveSession(
            api_key="k", model_name="m", voice_name="Charon", system_instruction="be TRON"
        ) as session:
            return [event async for event in session.receive()]

    events = asyncio.run(run())

    assert events == [
        {"type": "audio", "data": b"hello-audio"},
        {"type": "turn_complete"},
    ]


def test_receive_yields_tool_call_events(monkeypatch):
    fake_session = FakeLiveSession([
        _tool_call_response([{"id": "call-1", "name": "open_target", "args": {"name": "notepad"}}])
    ])
    _connect(monkeypatch, fake_session)

    async def run():
        async with glc.GeminiLiveSession(
            api_key="k", model_name="m", voice_name="Charon", system_instruction="be TRON",
            tools=[{"name": "open_target", "description": "d", "parameters": {"type": "object"}}],
        ) as session:
            return [event async for event in session.receive()]

    events = asyncio.run(run())

    assert events == [
        {"type": "tool_call", "calls": [{"id": "call-1", "name": "open_target", "args": {"name": "notepad"}}]}
    ]


def test_send_tool_response_forwards_result(monkeypatch):
    fake_session = FakeLiveSession([])
    _connect(monkeypatch, fake_session)

    async def run():
        async with glc.GeminiLiveSession(
            api_key="k", model_name="m", voice_name="Charon", system_instruction="be TRON"
        ) as session:
            await session.send_tool_response("call-1", "open_target", 'opened "notepad"')

    asyncio.run(run())

    assert len(fake_session.sent_tool_responses) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\pytest tests/test_gemini_live_client.py -v`
Expected: FAIL — old assertions no longer match the current `gemini_live_client.py` behavior (still yields raw bytes)

- [ ] **Step 3: Rewrite `gemini_live_client.py`**

```python
# gemini_live_client.py
from typing import Any, AsyncIterator, Dict, List, Optional

from google import genai
from google.genai import types


class GeminiLiveSession:
    """One Gemini Live conversation: PCM audio in, tagged events (audio/tool_call/turn_complete) out."""

    def __init__(
        self,
        api_key: str,
        model_name: str,
        voice_name: str,
        system_instruction: str,
        tools: Optional[List[Dict[str, Any]]] = None,
    ):
        self._client = genai.Client(api_key=api_key)
        self._model_name = model_name

        live_tools = None
        if tools:
            live_tools = [types.Tool(function_declarations=[
                types.FunctionDeclaration(
                    name=t["name"], description=t["description"], parameters=t.get("parameters")
                )
                for t in tools
            ])]

        self._config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                )
            ),
            system_instruction=types.Content(parts=[types.Part(text=system_instruction)]),
            tools=live_tools,
        )
        self._connect_cm = None
        self._session = None

    async def __aenter__(self) -> "GeminiLiveSession":
        self._connect_cm = self._client.aio.live.connect(model=self._model_name, config=self._config)
        self._session = await self._connect_cm.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._connect_cm is not None:
            await self._connect_cm.__aexit__(exc_type, exc, tb)

    async def send_audio_chunk(self, pcm_bytes: bytes, sample_rate: int = 16000) -> None:
        await self._session.send_realtime_input(
            audio=types.Blob(data=pcm_bytes, mime_type=f"audio/pcm;rate={sample_rate}")
        )

    async def send_tool_response(self, call_id: str, name: str, result: str) -> None:
        await self._session.send_tool_response(
            function_responses=[types.FunctionResponse(id=call_id, name=name, response={"result": result})]
        )

    async def receive(self) -> AsyncIterator[Dict[str, Any]]:
        """Yields tagged events: {"type": "audio", "data": bytes},
        {"type": "tool_call", "calls": [...]}, or {"type": "turn_complete"}."""
        async for response in self._session.receive():
            if response.data:
                yield {"type": "audio", "data": response.data}
            if response.tool_call and response.tool_call.function_calls:
                calls = [
                    {"id": fc.id, "name": fc.name, "args": dict(fc.args or {})}
                    for fc in response.tool_call.function_calls
                ]
                yield {"type": "tool_call", "calls": calls}
            if response.server_content and response.server_content.turn_complete:
                yield {"type": "turn_complete"}
```

Note: as with the model/voice name in the Voice Core plan, verify `types.Tool`/`types.FunctionDeclaration`/`response.tool_call` field names against the current [Gemini Live API docs](https://ai.google.dev/gemini-api/docs/live) if this errors — the SDK's function-calling surface is more likely to shift between versions than the basic audio path.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\pytest tests/test_gemini_live_client.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add gemini_live_client.py tests/test_gemini_live_client.py
git commit -m "Add tool-calling support to Gemini Live client"
```

---

### Task 6: State machine — dispatch tool calls, add ACTING state

**Files:**
- Modify: `state_manager.py`
- Modify: `tests/test_state_manager.py`

**Interfaces:**
- Consumes: `tools.TOOL_DISPATCH`, `tools.TOOL_DECLARATIONS`, the new `gemini_live_client.GeminiLiveSession` event shape and `send_tool_response`
- Produces (changed from Voice Core): `state_manager.State` gains `ACTING`. `TronStateMachine.__init__` gains `cfg=None` parameter, threaded through to tool dispatch calls.

- [ ] **Step 1: Write the failing test (full rewrite of the fakes to match the new event shape, plus a new tool-call test)**

```python
# tests/test_state_manager.py
from unittest.mock import MagicMock

import state_manager as sm


class FakeAudio:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.played = []
        self._mic_chunks = [b"sir-are-you-there", b""]

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def drain_mic(self):
        return self._mic_chunks.pop(0) if self._mic_chunks else b""

    def play_chunk(self, pcm_bytes):
        self.played.append(pcm_bytes)


class FakeSession:
    """events: a list of gemini_live_client-style event dicts to replay from receive()."""

    def __init__(self, events=None):
        self.sent_audio = []
        self.sent_tool_responses = []
        self._events = events if events is not None else [
            {"type": "audio", "data": b"reply-audio"},
            {"type": "turn_complete"},
        ]

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def send_audio_chunk(self, pcm_bytes, sample_rate=16000):
        self.sent_audio.append(pcm_bytes)

    async def send_tool_response(self, call_id, name, result):
        self.sent_tool_responses.append((call_id, name, result))

    async def receive(self):
        for event in self._events:
            yield event


def test_trigger_runs_full_state_cycle_with_distinct_colors_per_phase():
    audio = FakeAudio()
    states = []

    machine = sm.TronStateMachine(
        api_key="k", model_name="m", voice_name="Charon", persona_text="be TRON",
        silence_timeout_s=0.1,
        on_state_change=states.append,
        audio=audio,
        session_factory=lambda: FakeSession(),
    )

    assert machine.state is sm.State.IDLE

    machine.trigger()

    assert machine.state is sm.State.IDLE
    assert audio.started is True
    assert audio.stopped is True
    assert b"reply-audio" in audio.played
    assert states[0] is sm.State.LISTENING
    assert sm.State.SPEAKING in states
    assert states[-1] is sm.State.IDLE


def test_trigger_is_a_no_op_while_already_in_a_conversation():
    audio = FakeAudio()
    audio._mic_chunks = []

    call_count = {"n": 0}

    def counting_factory():
        call_count["n"] += 1
        return FakeSession()

    machine = sm.TronStateMachine(
        api_key="k", model_name="m", voice_name="Charon", persona_text="be TRON",
        silence_timeout_s=0.1,
        audio=audio,
        session_factory=counting_factory,
    )
    machine.state = sm.State.THINKING

    machine.trigger()

    assert call_count["n"] == 0


def test_failed_session_sets_error_state_and_stays_retriggerable():
    audio = FakeAudio()

    class BrokenSession(FakeSession):
        async def __aenter__(self):
            raise ConnectionError("network unreachable")

    attempts = {"n": 0}

    def flaky_factory():
        attempts["n"] += 1
        return BrokenSession() if attempts["n"] == 1 else FakeSession()

    machine = sm.TronStateMachine(
        api_key="k", model_name="m", voice_name="Charon", persona_text="be TRON",
        silence_timeout_s=0.1,
        audio=audio,
        session_factory=flaky_factory,
    )

    machine.trigger()
    assert machine.state is sm.State.ERROR

    machine.trigger()
    assert machine.state is sm.State.IDLE
    assert attempts["n"] == 2


def test_tool_call_event_dispatches_and_sends_response(monkeypatch):
    import tools

    audio = FakeAudio()
    audio._mic_chunks = []
    states = []

    fake_tool = MagicMock(return_value='opened "notepad"')
    monkeypatch.setitem(tools.TOOL_DISPATCH, "open_target", fake_tool)

    session = FakeSession(events=[
        {"type": "tool_call", "calls": [{"id": "call-1", "name": "open_target", "args": {"name": "notepad"}}]},
        {"type": "turn_complete"},
    ])
    fake_cfg = MagicMock()

    machine = sm.TronStateMachine(
        api_key="k", model_name="m", voice_name="Charon", persona_text="be TRON",
        silence_timeout_s=0.1,
        on_state_change=states.append,
        audio=audio,
        session_factory=lambda: session,
        cfg=fake_cfg,
    )

    machine.trigger()

    fake_tool.assert_called_once_with({"name": "notepad"}, fake_cfg)
    assert session.sent_tool_responses == [("call-1", "open_target", 'opened "notepad"')]
    assert sm.State.ACTING in states
    assert machine.state is sm.State.IDLE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\pytest tests/test_state_manager.py -v`
Expected: FAIL — current `state_manager.py` still expects bytes from `receive()`, has no `ACTING` state or `cfg` param

- [ ] **Step 3: Rewrite `state_manager.py`**

```python
# state_manager.py
import asyncio
import time
from enum import Enum, auto

import tools
from audio_io import DuplexAudio, SAMPLE_RATE_IN
from gemini_live_client import GeminiLiveSession


class State(Enum):
    IDLE = auto()
    LISTENING = auto()
    THINKING = auto()
    SPEAKING = auto()
    ACTING = auto()
    ERROR = auto()


_RETRIGGERABLE = (State.IDLE, State.ERROR)


class TronStateMachine:
    def __init__(
        self,
        api_key: str,
        model_name: str,
        voice_name: str,
        persona_text: str,
        silence_timeout_s: float,
        on_state_change=None,
        audio: DuplexAudio | None = None,
        session_factory=None,
        cfg=None,
    ):
        self._api_key = api_key
        self._model_name = model_name
        self._voice_name = voice_name
        self._persona_text = persona_text
        self._silence_timeout_s = silence_timeout_s
        self._on_state_change = on_state_change or (lambda state: None)
        self.state = State.IDLE
        self._audio = audio or DuplexAudio()
        self._cfg = cfg
        self._session_factory = session_factory or (
            lambda: GeminiLiveSession(
                self._api_key, self._model_name, self._voice_name, self._persona_text,
                tools=tools.TOOL_DECLARATIONS,
            )
        )

    def _set_state(self, state: State) -> None:
        self.state = state
        self._on_state_change(state)

    def trigger(self) -> None:
        """Called by the trigger (hotkey today, wake-word later). Starts a conversation
        from IDLE or ERROR; a no-op while a conversation is already in progress."""
        if self.state in _RETRIGGERABLE:
            asyncio.run(self._run_conversation())

    async def _run_conversation(self) -> None:
        self._audio.start()
        self._set_state(State.LISTENING)
        last_activity = time.monotonic()
        ended_in_error = False

        def touch() -> None:
            nonlocal last_activity
            last_activity = time.monotonic()

        try:
            async with self._session_factory() as session:

                async def send_loop() -> None:
                    was_listening = True
                    while time.monotonic() - last_activity < self._silence_timeout_s:
                        chunk = self._audio.drain_mic()
                        if chunk:
                            if not was_listening:
                                self._set_state(State.LISTENING)
                                was_listening = True
                            await session.send_audio_chunk(chunk, SAMPLE_RATE_IN)
                            touch()
                        elif was_listening:
                            self._set_state(State.THINKING)
                            was_listening = False
                        await asyncio.sleep(0.05)

                async def recv_loop() -> None:
                    async for event in session.receive():
                        if event["type"] == "audio":
                            self._set_state(State.SPEAKING)
                            self._audio.play_chunk(event["data"])
                            touch()
                        elif event["type"] == "tool_call":
                            self._set_state(State.ACTING)
                            for call in event["calls"]:
                                handler = tools.TOOL_DISPATCH[call["name"]]
                                result = handler(call["args"], self._cfg)
                                await session.send_tool_response(call["id"], call["name"], result)
                            touch()
                        elif event["type"] == "turn_complete":
                            self._set_state(State.THINKING)

                recv_task = asyncio.create_task(recv_loop())
                try:
                    await send_loop()
                finally:
                    recv_task.cancel()
        except Exception:
            ended_in_error = True
            self._set_state(State.ERROR)
        finally:
            self._audio.stop()
            if not ended_in_error:
                self._set_state(State.IDLE)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\pytest tests/test_state_manager.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add state_manager.py tests/test_state_manager.py
git commit -m "Dispatch tool-call events through TOOL_DISPATCH; add ACTING state"
```

---

### Task 7: Tray icon — ACTING color

**Files:**
- Modify: `tray_ui.py`
- Modify: `tests/test_tray_ui.py`

**Interfaces:**
- Consumes: `state_manager.State.ACTING`
- Produces: `tray_ui._COLORS["acting"]`

- [ ] **Step 1: Update the failing assertion**

```python
# tests/test_tray_ui.py — same file as Voice Core; only this import and the two
# existing tests are unchanged. No new test is needed: test_each_state_gets_a_distinct_color
# already iterates every member of state_manager.State, so it automatically covers ACTING
# once state_manager.State includes it (Task 6) and _COLORS has an "acting" entry (this task).
```

No test file changes are needed here — `test_each_state_gets_a_distinct_color` (written in the Voice Core plan) already loops over every `sm.State` member and asserts every state maps to a distinct color. It will fail against the current `tray_ui._COLORS` (missing an `"acting"` key) the moment Task 6 lands `State.ACTING`, and pass again once this task adds the color.

- [ ] **Step 2: Run test to verify it currently fails**

Run: `.venv\Scripts\pytest tests/test_tray_ui.py -v`
Expected: FAIL on `test_each_state_gets_a_distinct_color` with a `KeyError: 'acting'`

- [ ] **Step 3: Modify `tray_ui.py`** — add the `acting` color

```python
_COLORS = {
    "idle": (235, 235, 235),      # white/gray — waiting for the hotkey
    "listening": (66, 133, 244),  # blue — mic capturing your speech
    "thinking": (255, 193, 7),    # amber — paused/waiting on Gemini
    "speaking": (52, 199, 89),    # green — TRON's reply is playing
    "acting": (155, 89, 182),     # purple — a tool is actively running
    "error": (220, 53, 69),       # red — network/API failure this turn
}
```

(Only the `_COLORS` dict changes — everything else in `tray_ui.py` is untouched.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\pytest tests/test_tray_ui.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add tray_ui.py
git commit -m "Add ACTING (purple) tray color for tool execution"
```

---

### Task 8: Wire it into main.py, update persona, update smoke test

**Files:**
- Modify: `main.py`
- Modify: `persona.txt`
- Modify: `tests/test_smoke.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `config.load_config` (now returns SMTP fields too), `state_manager.TronStateMachine(..., cfg=...)`
- Produces: nothing new (this is the final wiring task)

- [ ] **Step 1: Write the failing/updated smoke test**

```python
# tests/test_smoke.py
from unittest.mock import MagicMock

import state_manager as sm


class ScriptedAudio:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.played = []
        self._chunks = [b"hey-tron-are-you-there", b"", b""]

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def drain_mic(self):
        return self._chunks.pop(0) if self._chunks else b""

    def play_chunk(self, pcm_bytes):
        self.played.append(pcm_bytes)


class ScriptedGeminiSession:
    """Fake Gemini Live session: answers, then calls a tool, then answers again."""

    def __init__(self, *args, **kwargs):
        self.sent_tool_responses = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def send_audio_chunk(self, pcm_bytes, sample_rate=16000):
        pass

    async def send_tool_response(self, call_id, name, result):
        self.sent_tool_responses.append((call_id, name, result))

    async def receive(self):
        yield {"type": "audio", "data": b"one-moment-sir"}
        yield {
            "type": "tool_call",
            "calls": [{"id": "call-1", "name": "open_target", "args": {"name": "notepad"}}],
        }
        yield {"type": "audio", "data": b"done-sir"}
        yield {"type": "turn_complete"}


def test_wake_trigger_produces_a_spoken_response_dry_run():
    audio = ScriptedAudio()
    states = []

    machine = sm.TronStateMachine(
        api_key="dry-run-key",
        model_name="gemini-2.0-flash-live-001",
        voice_name="Charon",
        persona_text="You are TRON. Address the user as sir.",
        silence_timeout_s=0.1,
        on_state_change=states.append,
        audio=audio,
        session_factory=lambda: ScriptedGeminiSession(),
    )

    machine.trigger()

    assert audio.played, "expected at least one non-empty response chunk played back"
    assert b"one-moment-sir" in audio.played
    assert machine.state is sm.State.IDLE
    assert states[0] is sm.State.LISTENING
    assert sm.State.SPEAKING in states
    assert states[-1] is sm.State.IDLE


def test_wake_trigger_handles_a_tool_call_mid_conversation(monkeypatch):
    import tools

    audio = ScriptedAudio()
    states = []
    fake_tool = MagicMock(return_value='opened "notepad"')
    monkeypatch.setitem(tools.TOOL_DISPATCH, "open_target", fake_tool)

    machine = sm.TronStateMachine(
        api_key="dry-run-key",
        model_name="gemini-2.0-flash-live-001",
        voice_name="Charon",
        persona_text="You are TRON. Address the user as sir.",
        silence_timeout_s=0.1,
        on_state_change=states.append,
        audio=audio,
        session_factory=lambda: ScriptedGeminiSession(),
        cfg=MagicMock(),
    )

    machine.trigger()

    fake_tool.assert_called_once()
    assert b"done-sir" in audio.played
    assert sm.State.ACTING in states
    assert machine.state is sm.State.IDLE
```

Note: this replaces the previous smoke test's fake session (which yielded raw bytes) with the new tagged-event shape, and adds a second scenario exercising a tool call mid-conversation — the actual point of this sub-project.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\pytest tests/test_smoke.py -v`
Expected: FAIL — `ScriptedGeminiSession` didn't exist in this shape before; state_manager.py from Task 6 is already in place, so once this file is saved it should actually pass immediately. Run it to confirm; if not, re-check Task 6's `state_manager.py` against this test's expectations first.

- [ ] **Step 3: Run test to verify it passes**

Run: `.venv\Scripts\pytest tests/test_smoke.py -v`
Expected: PASS (2 tests)

- [ ] **Step 4: Modify `persona.txt`** — add tool-usage and confirm-before-send rules

```
You are TRON, a personal AI assistant running on the user's own computer.

Always address the user as "sir." Keep your tone formal, economical, and
dry-witted — a butler-AI register, not a chatty consumer assistant. Default
to short, direct responses; elaborate only when asked to. Never break
character or mention that you are a language model unless directly asked
about your own nature.

You have tools to open apps/files/games, control media playback, search
the web, and handle email. Use them directly for routine requests — do not
ask permission to open an app or search the web.

Email is the one exception: always call draft_email first, read the
subject and body back to the user verbatim, and wait for an explicit
spoken confirmation ("yes," "send it," etc.) before calling send_email.
Never call send_email in the same turn as draft_email without that
confirmation happening in between. If the user says no or asks for
changes, revise and read back the draft again rather than sending it.
```

- [ ] **Step 5: Modify `main.py`** — pass `cfg` through to the state machine

```python
# main.py
import sys
import time
from pathlib import Path

from config import load_config
from state_manager import TronStateMachine
from wake_trigger import HotkeyTrigger
from tray_ui import TrayUI


def main() -> None:
    cfg = load_config()
    persona_text = Path(cfg.persona_path).read_text(encoding="utf-8")

    if cfg.wake_mode != "hotkey":
        raise NotImplementedError(
            f'wake_mode="{cfg.wake_mode}" is not wired up yet — only "hotkey" is. '
            "See docs/train_wakeword.md to add a trained wake-word model, then "
            "extend wake_trigger.py with an OpenWakeWordTrigger."
        )

    tray = TrayUI(quit_callback=lambda: _quit(trigger, tray))

    machine = TronStateMachine(
        api_key=cfg.gemini_api_key,
        model_name=cfg.model_name,
        voice_name=cfg.voice_name,
        persona_text=persona_text,
        silence_timeout_s=cfg.silence_timeout_s,
        on_state_change=tray.on_state_change,
        cfg=cfg,
    )

    trigger = HotkeyTrigger(cfg.hotkey, on_trigger=machine.trigger)
    trigger.start()
    tray.start()

    print(f'TRON is running. Press {cfg.hotkey} to talk. Quit from the tray icon menu.')
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        _quit(trigger, tray)


def _quit(trigger: HotkeyTrigger, tray: TrayUI) -> None:
    trigger.stop()
    tray.stop()
    sys.exit(0)


if __name__ == "__main__":
    main()
```

(Only the `cfg=cfg` addition to the `TronStateMachine(...)` call changes from the Voice Core version.)

- [ ] **Step 6: Modify `README.md`** — document the new tray color and email setup

```markdown
# TRON

A personal voice assistant. Sub-project 2/6 (Automation/Tools) of the larger
TRON program — see `docs/superpowers/specs/` for the full design and roadmap.

## Setup

1. Python 3.13 (this machine only had 3.13 installed; the original spec
   targeted 3.11/3.12 but nothing here needs an older version).
2. `python -m venv .venv` then `.venv\Scripts\pip install -r requirements.txt`
3. Get a Gemini API key from https://aistudio.google.com/apikey
4. `copy config.example.json config.json` and fill in `gemini_api_key`
5. (Optional, for email) Fill in `smtp_host`/`smtp_port`/`smtp_user`/
   `smtp_app_password` in `config.json`. For Gmail: enable 2FA on the
   account, then generate an "app password" at
   https://myaccount.google.com/apppasswords — your normal password will
   not work over SMTP.
6. `.venv\Scripts\python main.py`
7. Press `Ctrl+Alt+T` (configurable in `config.json`) to talk to TRON. Quit
   from the system tray icon.

## Tray icon status colors

| Color | State | Meaning |
|---|---|---|
| White/gray | Idle | Waiting for the hotkey |
| Blue | Listening | Mic is capturing your speech |
| Amber | Thinking | Waiting on Gemini's response |
| Green | Speaking | TRON's reply is playing |
| Purple | Acting | A tool (open app, media control, email, search) is running |
| Red | Error | Network/API failure this turn — press the hotkey again to retry |

## What TRON can do now

- Open apps, files, photos, videos, or games by name ("open notepad", "open that dune photo")
- Control media playback: play/pause, next/previous track, seek forward/backward (best-effort, up to about a minute)
- Search the web
- Draft and — after you confirm out loud — send email

## Tests

`.venv\Scripts\pytest`

## Upgrading to a real "TRON" wake word (no hotkey)

See `docs/train_wakeword.md`.
```

- [ ] **Step 7: Compile-check and run the full test suite**

Run: `.venv\Scripts\python -m py_compile main.py` then `.venv\Scripts\pytest -v`
Expected: `main.py` compiles; all tests across all 8 tasks pass.

- [ ] **Step 8: Commit**

```bash
git add main.py persona.txt tests/test_smoke.py README.md
git commit -m "Wire tool config into main.py, add confirm-before-send persona rule"
```
