# Perception + Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Screen/camera vision (genuinely multimodal, via Gemini Live, off by default and structurally ungatable until explicitly enabled) and a Windows-Defender-backed malware scan — per `docs/superpowers/specs/2026-08-09-perception-security-design.md`. The final sub-project of the TRON program.

**Architecture:** `tools.declarations_for(cfg)` filters vision tools out of what's declared to Gemini unless `cfg.camera_enabled`/`cfg.screen_enabled` is true. `state_manager.py` special-cases the two vision tool names (they need the live session to push a frame, unlike every other tool). `security_scan.py` wraps `Start-MpScan` in a background thread; both new tools log to the existing `memory.py` activity log.

**Tech Stack:** New dependency `opencv-python` (webcam capture — no lighter stdlib option exists). Everything else (screen capture via Pillow, malware scan via PowerShell subprocess) uses what's already available.

## Global Constraints

- `camera_enabled`/`screen_enabled` default to `false` in `config.py`/`config.example.json`/the setup wizard. This is enforced structurally — `look_at_screen`/`look_via_camera` are not declared to Gemini at all unless enabled, not merely discouraged by a prompt instruction.
- No frame (screen or camera) is ever written to disk. Captured bytes go straight into `session.send_video_frame()` and are discarded; only the *fact* of the capture is logged via `memory.log_activity`, never the image itself.
- `scan_for_malware`/`check_scan_status` follow the normal `(args, cfg) -> str` `TOOL_DISPATCH` signature and are always declared — malware scanning isn't gated like camera/screen, since it inspects the user's own files for their benefit rather than capturing them.
- All tool wrapper functions in `tools.py` call through to their backing module by attribute lookup at call time (e.g. `security_scan.scan_for_malware(...)`), not a captured reference at import time — this is what makes `monkeypatch.setattr(tools.security_scan, "scan_for_malware", ...)` work in tests, matching every prior tool wrapper in this file.

---

### Task 1: Config fields for camera/screen consent

**Files:**
- Modify: `config.py`
- Modify: `config.example.json`
- Modify: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `Config.camera_enabled: bool`, `Config.screen_enabled: bool` (both default `False` via `load_config()`)

- [ ] **Step 1: Add the failing tests to `tests/test_config.py`**

```python
def test_load_config_defaults_camera_and_screen_to_disabled(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"gemini_api_key": "k"}))
    monkeypatch.setattr(config_module, "CONFIG_PATH", cfg_path)

    cfg = config_module.load_config()

    assert cfg.camera_enabled is False
    assert cfg.screen_enabled is False


def test_load_config_respects_explicit_camera_and_screen_flags(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "gemini_api_key": "k", "camera_enabled": True, "screen_enabled": True,
    }))
    monkeypatch.setattr(config_module, "CONFIG_PATH", cfg_path)

    cfg = config_module.load_config()

    assert cfg.camera_enabled is True
    assert cfg.screen_enabled is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest tests/test_config.py -v`
Expected: FAIL — `Config` has no `camera_enabled`/`screen_enabled` fields yet

- [ ] **Step 3: Modify `config.py`**

```python
# add two fields to the Config dataclass, after smtp_app_password:
    camera_enabled: bool
    screen_enabled: bool

# add to load_config()'s Config(...) construction, after smtp_app_password:
        camera_enabled=data.get("camera_enabled", False),
        screen_enabled=data.get("screen_enabled", False),
```

- [ ] **Step 4: Modify `config.example.json`** — add after `smtp_app_password`

```json
  "camera_enabled": false,
  "screen_enabled": false
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\pytest tests/test_config.py -v`
Expected: PASS (8 tests: 6 existing + 2 new)

- [ ] **Step 6: Commit**

```bash
git add config.py config.example.json tests/test_config.py
git commit -m "Add camera_enabled/screen_enabled config fields, defaulting to disabled"
```

---

### Task 2: Screen and camera frame capture

**Files:**
- Create: `perception.py`
- Test: `tests/test_perception.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: nothing new
- Produces: `perception.capture_screen_jpeg() -> bytes`, `perception.capture_camera_jpeg() -> bytes` (raises `RuntimeError` on capture failure)

- [ ] **Step 1: Add `opencv-python` to `requirements.txt`**

```
google-genai>=0.3.0
sounddevice>=0.4.6
numpy>=1.26
keyboard>=0.13.5
pystray>=0.19.5
Pillow>=10.0
pywebview>=5.0
opencv-python>=4.8
pytest>=8.0
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_perception.py
from unittest.mock import MagicMock

import numpy as np
import pytest
from PIL import Image

import perception


def test_capture_screen_jpeg_returns_jpeg_bytes(monkeypatch):
    fake_image = Image.new("RGB", (20, 20), color=(10, 20, 30))
    monkeypatch.setattr(perception.ImageGrab, "grab", lambda: fake_image)

    data = perception.capture_screen_jpeg()

    assert data[:2] == b"\xff\xd8"  # JPEG magic bytes


def test_capture_camera_jpeg_returns_jpeg_bytes(monkeypatch):
    fake_frame = np.zeros((10, 10, 3), dtype=np.uint8)
    fake_cap = MagicMock()
    fake_cap.isOpened.return_value = True
    fake_cap.read.return_value = (True, fake_frame)
    monkeypatch.setattr(perception.cv2, "VideoCapture", MagicMock(return_value=fake_cap))

    data = perception.capture_camera_jpeg()

    assert data[:2] == b"\xff\xd8"
    fake_cap.release.assert_called_once()


def test_capture_camera_jpeg_raises_when_camera_unavailable(monkeypatch):
    fake_cap = MagicMock()
    fake_cap.isOpened.return_value = False
    monkeypatch.setattr(perception.cv2, "VideoCapture", MagicMock(return_value=fake_cap))

    with pytest.raises(RuntimeError):
        perception.capture_camera_jpeg()
    fake_cap.release.assert_called_once()


def test_capture_camera_jpeg_raises_when_read_fails(monkeypatch):
    fake_cap = MagicMock()
    fake_cap.isOpened.return_value = True
    fake_cap.read.return_value = (False, None)
    monkeypatch.setattr(perception.cv2, "VideoCapture", MagicMock(return_value=fake_cap))

    with pytest.raises(RuntimeError):
        perception.capture_camera_jpeg()
    fake_cap.release.assert_called_once()
```

- [ ] **Step 3: Install the new dependency and run test to verify it fails**

Run: `.venv\Scripts\pip install -r requirements.txt` then `.venv\Scripts\pytest tests/test_perception.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'perception'`

- [ ] **Step 4: Write `perception.py`**

```python
# perception.py
import io

import cv2
from PIL import ImageGrab


def capture_screen_jpeg() -> bytes:
    img = ImageGrab.grab()
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def capture_camera_jpeg() -> bytes:
    cap = cv2.VideoCapture(0)
    try:
        if not cap.isOpened():
            raise RuntimeError("could not open the camera")
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError("could not read a frame from the camera")
        success, buf = cv2.imencode(".jpg", frame)
        if not success:
            raise RuntimeError("could not encode the camera frame")
        return buf.tobytes()
    finally:
        cap.release()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv\Scripts\pytest tests/test_perception.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add perception.py requirements.txt tests/test_perception.py
git commit -m "Add one-shot screen/camera frame capture"
```

---

### Task 3: Gemini Live client — video frame input

**Files:**
- Modify: `gemini_live_client.py`
- Modify: `tests/test_gemini_live_client.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `GeminiLiveSession.send_video_frame(jpeg_bytes: bytes) -> None`

- [ ] **Step 1: Update `tests/test_gemini_live_client.py`'s `FakeLiveSession`**

```python
# FakeLiveSession — generalize send_realtime_input to accept either audio or video,
# and add sent_video tracking:
class FakeLiveSession:
    def __init__(self, responses):
        self.sent_audio = []
        self.sent_video = []
        self.sent_tool_responses = []
        self._responses = responses

    async def send_realtime_input(self, audio=None, video=None):
        if audio is not None:
            self.sent_audio.append(audio)
        if video is not None:
            self.sent_video.append(video)

    async def send_tool_response(self, function_responses):
        self.sent_tool_responses.append(function_responses)

    async def receive(self):
        for resp in self._responses:
            yield resp
```

Add the new failing test:

```python
def test_send_video_frame_forwards_jpeg_bytes(monkeypatch):
    fake_session = FakeLiveSession([])
    _connect(monkeypatch, fake_session)

    async def run():
        async with glc.GeminiLiveSession(
            api_key="k", model_name="m", voice_name="Charon", system_instruction="be TRON"
        ) as session:
            await session.send_video_frame(b"\xff\xd8fake-jpeg-bytes")

    asyncio.run(run())

    assert len(fake_session.sent_video) == 1
```

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `.venv\Scripts\pytest tests/test_gemini_live_client.py -v`
Expected: FAIL — `GeminiLiveSession` has no `send_video_frame` yet (the other 3 tests still pass, since `send_realtime_input`'s new signature is backward compatible with `audio=`-only calls)

- [ ] **Step 3: Modify `gemini_live_client.py`** — add one method after `send_audio_chunk`

```python
    async def send_video_frame(self, jpeg_bytes: bytes) -> None:
        await self._session.send_realtime_input(
            video=types.Blob(data=jpeg_bytes, mime_type="image/jpeg")
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest tests/test_gemini_live_client.py -v`
Expected: PASS (4 tests: 3 unchanged + 1 new)

- [ ] **Step 5: Commit**

```bash
git add gemini_live_client.py tests/test_gemini_live_client.py
git commit -m "Add video frame input to Gemini Live client"
```

---

### Task 4: Malware scan (wraps Windows Defender)

**Files:**
- Create: `security_scan.py`
- Test: `tests/test_security_scan.py`

**Interfaces:**
- Consumes: `memory.log_activity`
- Produces: `security_scan.scan_for_malware(args, cfg) -> str`, `security_scan.check_scan_status(args, cfg) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_security_scan.py
from unittest.mock import MagicMock

import pytest

import security_scan


@pytest.fixture(autouse=True)
def reset_status():
    with security_scan._status_lock:
        security_scan._status["state"] = "never_run"
    yield
    with security_scan._status_lock:
        security_scan._status["state"] = "never_run"


def test_check_scan_status_never_run():
    assert "no scan has been run" in security_scan.check_scan_status({}, None)


def test_scan_for_malware_starts_background_thread(monkeypatch):
    monkeypatch.setattr(security_scan.subprocess, "run", MagicMock())
    monkeypatch.setattr(
        security_scan.threading, "Thread",
        lambda target, daemon: MagicMock(start=target),
    )

    result = security_scan.scan_for_malware({}, None)

    assert "scan started" in result.lower()


def test_scan_for_malware_refuses_concurrent_scans():
    with security_scan._status_lock:
        security_scan._status["state"] = "running"

    result = security_scan.scan_for_malware({}, None)

    assert "already running" in result.lower()


def test_run_scan_marks_completed_on_success(monkeypatch):
    monkeypatch.setattr(security_scan.subprocess, "run", MagicMock())
    logged = []
    monkeypatch.setattr(security_scan.memory, "log_activity", lambda entry: logged.append(entry))

    security_scan._run_scan()

    assert security_scan._status["state"] == "completed"
    assert logged[0]["tool"] == "scan_for_malware"


def test_run_scan_marks_failed_on_error(monkeypatch):
    monkeypatch.setattr(
        security_scan.subprocess, "run", MagicMock(side_effect=OSError("powershell not found"))
    )
    logged = []
    monkeypatch.setattr(security_scan.memory, "log_activity", lambda entry: logged.append(entry))

    security_scan._run_scan()

    assert security_scan._status["state"] == "failed"
    assert "failed" in logged[0]["result"].lower()


def test_check_scan_status_running():
    with security_scan._status_lock:
        security_scan._status["state"] = "running"
    assert "still running" in security_scan.check_scan_status({}, None)


def test_check_scan_status_completed():
    with security_scan._status_lock:
        security_scan._status["state"] = "completed"
    assert "completed" in security_scan.check_scan_status({}, None)


def test_check_scan_status_failed():
    with security_scan._status_lock:
        security_scan._status["state"] = "failed"
    assert "failed" in security_scan.check_scan_status({}, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\pytest tests/test_security_scan.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'security_scan'`

- [ ] **Step 3: Write `security_scan.py`**

```python
# security_scan.py
import subprocess
import threading
import time

import memory

_status_lock = threading.Lock()
_status = {"state": "never_run"}  # never_run | running | completed | failed


def scan_for_malware(args, cfg) -> str:
    """Kicks off a Windows Defender quick scan in the background and returns immediately."""
    with _status_lock:
        if _status["state"] == "running":
            return "a scan is already running, sir"
        _status["state"] = "running"

    thread = threading.Thread(target=_run_scan, daemon=True)
    thread.start()
    return "scan started, sir — I'll let you know when it's finished"


def _run_scan() -> None:
    started_at = time.time()
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Start-MpScan -ScanType QuickScan"],
            check=True, capture_output=True, text=True, timeout=1800,
        )
        with _status_lock:
            _status["state"] = "completed"
        memory.log_activity({
            "tool": "scan_for_malware", "args": {},
            "result": f"quick scan completed in {int(time.time() - started_at)}s",
        })
    except Exception as exc:
        with _status_lock:
            _status["state"] = "failed"
        memory.log_activity({
            "tool": "scan_for_malware", "args": {}, "result": f"scan failed: {exc}",
        })


def check_scan_status(args, cfg) -> str:
    with _status_lock:
        state = _status["state"]
    if state == "never_run":
        return "no scan has been run yet, sir"
    if state == "running":
        return "the scan is still running, sir"
    if state == "completed":
        return "the last scan completed with no issues reported, sir"
    return "the last scan failed to complete — check Windows Security for details, sir"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\pytest tests/test_security_scan.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add security_scan.py tests/test_security_scan.py
git commit -m "Add Windows Defender-backed malware scan tools"
```

---

### Task 5: Register in the tool registry; add `declarations_for(cfg)`

**Files:**
- Modify: `tools.py`
- Modify: `tests/test_tools.py`

**Interfaces:**
- Consumes: `security_scan.scan_for_malware`, `security_scan.check_scan_status`
- Produces: `tools.declarations_for(cfg) -> list[dict]`, `tools.VISION_TOOL_NAMES: set[str]`, `TOOL_DISPATCH["scan_for_malware"]`, `TOOL_DISPATCH["check_scan_status"]`

- [ ] **Step 1: Add the failing tests to `tests/test_tools.py`**

```python
def test_declarations_for_excludes_vision_tools_by_default():
    cfg = MagicMock(camera_enabled=False, screen_enabled=False)
    names = {d["name"] for d in tools.declarations_for(cfg)}
    assert "look_at_screen" not in names
    assert "look_via_camera" not in names


def test_declarations_for_includes_screen_when_enabled():
    cfg = MagicMock(camera_enabled=False, screen_enabled=True)
    names = {d["name"] for d in tools.declarations_for(cfg)}
    assert "look_at_screen" in names
    assert "look_via_camera" not in names


def test_declarations_for_includes_camera_when_enabled():
    cfg = MagicMock(camera_enabled=True, screen_enabled=False)
    names = {d["name"] for d in tools.declarations_for(cfg)}
    assert "look_via_camera" in names
    assert "look_at_screen" not in names


def test_declarations_for_handles_none_cfg():
    names = {d["name"] for d in tools.declarations_for(None)}
    assert "look_at_screen" not in names
    assert "look_via_camera" not in names


def test_scan_for_malware_delegates(monkeypatch):
    fake_scan = MagicMock(return_value="scan started, sir")
    monkeypatch.setattr(tools.security_scan, "scan_for_malware", fake_scan)

    result = tools.TOOL_DISPATCH["scan_for_malware"]({}, None)

    fake_scan.assert_called_once_with({}, None)
    assert result == "scan started, sir"


def test_check_scan_status_delegates(monkeypatch):
    fake_check = MagicMock(return_value="no scan has been run yet, sir")
    monkeypatch.setattr(tools.security_scan, "check_scan_status", fake_check)

    result = tools.TOOL_DISPATCH["check_scan_status"]({}, None)

    fake_check.assert_called_once_with({}, None)
    assert result == "no scan has been run yet, sir"
```

(`test_every_declaration_has_a_matching_dispatch_entry`, already in the file, keeps passing unmodified — vision tools are absent from both `TOOL_DECLARATIONS` and `TOOL_DISPATCH`, appearing only via `declarations_for()`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest tests/test_tools.py -v`
Expected: FAIL — `tools.declarations_for` and `tools.security_scan` don't exist yet

- [ ] **Step 3: Modify `tools.py`**

```python
# add to the imports at the top:
import security_scan

# add two wrapper functions alongside the other _xxx handlers:
def _scan_for_malware(args, cfg):
    return security_scan.scan_for_malware(args, cfg)


def _check_scan_status(args, cfg):
    return security_scan.check_scan_status(args, cfg)

# add to TOOL_DISPATCH:
    "scan_for_malware": _scan_for_malware,
    "check_scan_status": _check_scan_status,

# add to TOOL_DECLARATIONS:
    {
        "name": "scan_for_malware",
        "description": (
            "Start a Windows Defender quick scan for malware/viruses. Runs in the "
            "background; use check_scan_status later to see if it finished."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "check_scan_status",
        "description": "Check whether the most recent malware scan has finished and what it found.",
        "parameters": {"type": "object", "properties": {}},
    },

# add after TOOL_DECLARATIONS, as new module-level content:
_LOOK_AT_SCREEN_DECLARATION = {
    "name": "look_at_screen",
    "description": (
        "Capture and look at what's currently on the user's screen, then describe it. "
        'Say something like "let me take a look, sir" before calling this.'
    ),
    "parameters": {"type": "object", "properties": {}},
}

_LOOK_VIA_CAMERA_DECLARATION = {
    "name": "look_via_camera",
    "description": (
        "Capture a frame from the webcam and describe what's seen. "
        'Say something like "let me take a look, sir" before calling this.'
    ),
    "parameters": {"type": "object", "properties": {}},
}

VISION_TOOL_NAMES = {"look_at_screen", "look_via_camera"}


def declarations_for(cfg) -> list:
    """The tool schema actually sent to Gemini Live — vision tools are only
    included if the corresponding config flag is on. This is the structural
    enforcement of the camera/screen consent model: a tool Gemini was never
    told about is a tool it cannot call."""
    declarations = list(TOOL_DECLARATIONS)
    if cfg is not None and getattr(cfg, "screen_enabled", False):
        declarations.append(_LOOK_AT_SCREEN_DECLARATION)
    if cfg is not None and getattr(cfg, "camera_enabled", False):
        declarations.append(_LOOK_VIA_CAMERA_DECLARATION)
    return declarations
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest tests/test_tools.py -v`
Expected: PASS (17 tests: 11 existing + 6 new)

- [ ] **Step 5: Commit**

```bash
git add tools.py tests/test_tools.py
git commit -m "Add declarations_for(cfg) consent gate and malware scan tools to registry"
```

---

### Task 6: Wire vision tools into the state machine

**Files:**
- Modify: `state_manager.py`
- Modify: `tests/test_state_manager.py`

**Interfaces:**
- Consumes: `tools.declarations_for`, `tools.VISION_TOOL_NAMES`, `perception.capture_screen_jpeg`, `perception.capture_camera_jpeg`, `GeminiLiveSession.send_video_frame`
- Produces: no new public interface — `look_at_screen`/`look_via_camera` tool calls are now handled correctly; the default session factory now respects `cfg.camera_enabled`/`cfg.screen_enabled`

- [ ] **Step 1: Add the failing tests to `tests/test_state_manager.py`**

```python
# add near the top, alongside the existing imports:
import perception

# update FakeSession to track video frames (add sent_video and send_video_frame):
class FakeSession:
    """events: a list of gemini_live_client-style event dicts to replay from receive()."""

    def __init__(self, events=None):
        self.sent_audio = []
        self.sent_video = []
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

    async def send_video_frame(self, jpeg_bytes):
        self.sent_video.append(jpeg_bytes)

    async def send_tool_response(self, call_id, name, result):
        self.sent_tool_responses.append((call_id, name, result))

    async def receive(self):
        for event in self._events:
            yield event


# add these new tests:

def test_look_at_screen_sends_video_frame_and_acks(monkeypatch):
    audio = FakeAudio()
    audio._mic_chunks = []
    states = []

    fake_frame = b"\xff\xd8fake-jpeg"
    monkeypatch.setattr(perception, "capture_screen_jpeg", lambda: fake_frame)
    logged = []
    monkeypatch.setattr(memory, "log_activity", lambda entry: logged.append(entry))

    session = FakeSession(events=[
        {"type": "tool_call", "calls": [{"id": "call-1", "name": "look_at_screen", "args": {}}]},
        {"type": "turn_complete"},
    ])

    machine = sm.TronStateMachine(
        api_key="k", model_name="m", voice_name="Charon", persona_text="be TRON",
        silence_timeout_s=0.1,
        on_state_change=states.append,
        audio=audio,
        session_factory=lambda: session,
        cfg=MagicMock(screen_enabled=True, camera_enabled=False),
    )

    machine.trigger()

    assert session.sent_video == [fake_frame]
    assert session.sent_tool_responses == [("call-1", "look_at_screen", "here's what I see, sir")]
    assert logged[0]["tool"] == "look_at_screen"
    assert sm.State.ACTING in states


def test_look_via_camera_capture_failure_returns_apology(monkeypatch):
    audio = FakeAudio()
    audio._mic_chunks = []
    states = []

    def raise_error():
        raise RuntimeError("no camera")
    monkeypatch.setattr(perception, "capture_camera_jpeg", raise_error)

    session = FakeSession(events=[
        {"type": "tool_call", "calls": [{"id": "call-1", "name": "look_via_camera", "args": {}}]},
        {"type": "turn_complete"},
    ])

    machine = sm.TronStateMachine(
        api_key="k", model_name="m", voice_name="Charon", persona_text="be TRON",
        silence_timeout_s=0.1,
        on_state_change=states.append,
        audio=audio,
        session_factory=lambda: session,
        cfg=MagicMock(camera_enabled=True, screen_enabled=False),
    )

    machine.trigger()

    assert session.sent_video == []
    assert "couldn't capture" in session.sent_tool_responses[0][2]


def test_default_session_factory_uses_declarations_for_cfg(monkeypatch):
    captured = {}

    class FakeGeminiLiveSession:
        def __init__(self, api_key, model_name, voice_name, system_instruction, tools=None):
            captured["tools"] = tools

    monkeypatch.setattr(sm, "GeminiLiveSession", FakeGeminiLiveSession)
    monkeypatch.setattr(memory, "recent_context", lambda n=10: "")

    fake_cfg = MagicMock(screen_enabled=True, camera_enabled=False)
    machine = sm.TronStateMachine(
        api_key="k", model_name="m", voice_name="Charon", persona_text="be TRON",
        silence_timeout_s=0.1, cfg=fake_cfg,
    )

    machine._session_factory()

    names = {d["name"] for d in captured["tools"]}
    assert "look_at_screen" in names
    assert "look_via_camera" not in names
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `.venv\Scripts\pytest tests/test_state_manager.py -v`
Expected: FAIL — `state_manager.py` doesn't special-case vision tool names yet, and its default session factory still passes the static `tools.TOOL_DECLARATIONS`

- [ ] **Step 3: Modify `state_manager.py`**

```python
# state_manager.py — three changes to the file from sub-project 4

# 1. Add the import at the top, alongside `import memory` and `import tools`:
import perception

# 2. Change the default session_factory lambda inside __init__ to use declarations_for:
        self._session_factory = session_factory or (
            lambda: GeminiLiveSession(
                self._api_key, self._model_name, self._voice_name,
                self._persona_text + "\n\n" + memory.recent_context(),
                tools=tools.declarations_for(self._cfg),
            )
        )

# 3. In recv_loop's tool_call branch, special-case vision tool names:
                        elif event["type"] == "tool_call":
                            self._set_state(State.ACTING)
                            for call in event["calls"]:
                                if call["name"] in tools.VISION_TOOL_NAMES:
                                    result = await self._handle_vision_tool(call["name"], session)
                                else:
                                    handler = tools.TOOL_DISPATCH[call["name"]]
                                    result = handler(call["args"], self._cfg)
                                memory.log_activity({
                                    "tool": call["name"], "args": call["args"], "result": result
                                })
                                await session.send_tool_response(call["id"], call["name"], result)
                            touch()
```

Add a new method on `TronStateMachine`, alongside `_set_state`/`trigger`:

```python
    async def _handle_vision_tool(self, name: str, session) -> str:
        try:
            frame = perception.capture_screen_jpeg() if name == "look_at_screen" else perception.capture_camera_jpeg()
        except Exception as exc:
            return f"couldn't capture that, sir: {exc}"
        await session.send_video_frame(frame)
        return "here's what I see, sir"
```

Everything else in `state_manager.py` is unchanged from sub-project 4.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest tests/test_state_manager.py -v`
Expected: PASS (8 tests: 5 unchanged + 3 new)

- [ ] **Step 5: Commit**

```bash
git add state_manager.py tests/test_state_manager.py
git commit -m "Wire vision tools into the state machine; gate declarations by consent flags"
```

---

### Task 7: Setup wizard gets camera/screen checkboxes

**Files:**
- Modify: `setup_wizard.py`
- Modify: `tests/test_setup_wizard.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `build_config_dict` now includes `camera_enabled`/`screen_enabled`, defaulting to `False`

- [ ] **Step 1: Add the failing tests to `tests/test_setup_wizard.py`**

```python
def test_build_config_dict_defaults_camera_and_screen_to_false():
    form = {"gemini_api_key": "my-key"}
    result = setup_wizard.build_config_dict(form)
    assert result["camera_enabled"] is False
    assert result["screen_enabled"] is False


def test_build_config_dict_respects_explicit_camera_and_screen_flags():
    form = {"gemini_api_key": "my-key", "camera_enabled": True, "screen_enabled": True}
    result = setup_wizard.build_config_dict(form)
    assert result["camera_enabled"] is True
    assert result["screen_enabled"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest tests/test_setup_wizard.py -v`
Expected: FAIL — `build_config_dict` doesn't produce `camera_enabled`/`screen_enabled` yet

- [ ] **Step 3: Modify `setup_wizard.py`**

Add to `build_config_dict`'s returned dict, after `smtp_app_password`:

```python
        "camera_enabled": bool(form_values.get("camera_enabled", False)),
        "screen_enabled": bool(form_values.get("screen_enabled", False)),
```

In `run_first_time_setup()`, add two more checkboxes after the autostart checkbox (both default unchecked — this is the opt-in UI for the consent model), and include them in `on_save`'s `form_values`:

```python
    camera_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(root, text="Enable camera access", variable=camera_var).grid(
        row=7, column=0, columnspan=2, sticky="w", padx=8, pady=4
    )

    screen_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(root, text="Enable screen reading", variable=screen_var).grid(
        row=8, column=0, columnspan=2, sticky="w", padx=8, pady=4
    )
```

Move the Save button's `grid(row=7, ...)` down to `row=9`. In `on_save`, extend `form_values` with the two new booleans:

```python
        form_values = {key: var.get() for key, var in fields.items()}
        form_values["camera_enabled"] = camera_var.get()
        form_values["screen_enabled"] = screen_var.get()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest tests/test_setup_wizard.py -v`
Expected: PASS (5 tests: 3 existing + 2 new)

- [ ] **Step 5: Commit**

```bash
git add setup_wizard.py tests/test_setup_wizard.py
git commit -m "Add camera/screen opt-in checkboxes to the setup wizard"
```

---

### Task 8: Persona, docs, and final full-program verification

**Files:**
- Modify: `persona.txt`
- Modify: `docs/build_exe.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing (documentation + persona text only)
- Produces: nothing new

- [ ] **Step 1: Modify `persona.txt`** — append after the email confirmation paragraph

```
When asked to look at the screen or through the camera, say something like
"let me take a look, sir" before using the look_at_screen or look_via_camera
tool, so the user always knows when you're about to capture an image. These
tools only exist for you to call at all if the user has explicitly enabled
camera or screen access in setup — if asked to look and you don't have the
tool available, explain that camera or screen access needs to be turned on
first (in settings or by re-running setup).

For malware scans, call scan_for_malware to start a Windows Defender quick
scan when asked, and check_scan_status to report whether a previous scan
has finished.
```

- [ ] **Step 2: Modify `docs/build_exe.md`** — add `--collect-all cv2`, copy nothing new (no new external asset), extend the smoke-test checklist

Add `--collect-all cv2` to the documented `pyinstaller` command (five `--collect-all` flags total now). Add two more smoke-test steps: enabling screen/camera access in setup and confirming `look_at_screen`/`look_via_camera` work when enabled and are refused (or simply unavailable) when not; running `scan_for_malware` and later asking whether it finished.

- [ ] **Step 3: Modify `README.md`** — mark the roadmap complete

Update the header to "All 6 sub-projects complete." Add to "What TRON can do now": vision (screen/camera, off by default — enable in setup) and malware scanning. Add a short "Privacy" section summarizing the consent model: camera/screen access is opt-in and structurally enforced (the tool isn't declared to Gemini unless enabled), no frames are ever saved to disk, and every capture/scan is visible via "what have you been up to."

- [ ] **Step 4: Run the full test suite for the whole program**

Run: `.venv\Scripts\python -m py_compile main.py` then `.venv\Scripts\pytest -v`
Expected: `main.py` compiles; every test across all 6 sub-projects passes.

- [ ] **Step 5: Commit**

```bash
git add persona.txt docs/build_exe.md README.md
git commit -m "Add vision/scan persona rules; document consent model; mark program complete"
```
