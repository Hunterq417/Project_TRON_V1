# Voice Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A running `python main.py` that lets you press a hotkey, talk to "TRON," and get a real-time spoken reply (with barge-in), shown via a system tray icon — per `docs/superpowers/specs/2026-08-09-voice-core-design.md`.

**Architecture:** A `TronStateMachine` with five states (idle, listening, thinking, speaking, error — each its own tray-icon color) is driven by a trigger (hotkey today, wake-word later) and owns one Gemini Live session per conversation, pumping mic audio in and speaker audio out via two concurrent asyncio loops until a silence timeout returns it to idle.

**Tech Stack:** Python 3.11/3.12, `google-genai` (Gemini Live API), `sounddevice` (audio I/O), `keyboard` (global hotkey), `pystray`+`Pillow` (tray icon), `pytest` (tests). Windows target.

## Global Constraints

- Python 3.11 or 3.12, Windows.
- Wake word / assistant name is "TRON"; persona addresses the user as "sir"; formal, economical, dry-witted tone (see spec's Persona section) — lives in `persona.txt`, not hardcoded in Python.
- No camera, screen capture, automation/tool-calling, cross-session memory, or installer packaging in this plan — tray icon + `python main.py` is the shipped form (spec's "Explicitly out of scope").
- `config.json` (containing the API key) is never committed; only `config.example.json` is.
- **Deliberate MVP simplification (ponytail):** the design spec calls for a "TRON" wake word, but training a custom openWakeWord model is a separate offline/data step, not a 2-5 minute coding task. This plan ships a **global hotkey trigger** first (`Ctrl+Alt+T`, configurable) behind the same `on_trigger()` callback shape a wake-word backend would use, so swapping in the trained model later (`docs/train_wakeword.md`) touches only `wake_trigger.py` and `config.json`, not the state machine, audio, or Gemini client.
- **Tray color palette (`tray_ui._COLORS`):** five states now (idle=white/gray, listening=blue, thinking=amber, speaking=green, error=red). Voice Core has no notion of "task difficulty" yet — that concept belongs to sub-project 2 (automation/tools), where a quick "open Notepad" vs. a slow "scan for malware" call could reuse `ERROR`'s red or add a new `INTENSIVE` state. Not built now (YAGNI — there are no tasks to be intensive about yet); the palette dict is the extension point when that need is real.

---

### Task 1: Project scaffolding + config loader

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `config.example.json`
- Create: `persona.txt`
- Create: `config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces: `config.load_config() -> Config` where `Config` has fields `gemini_api_key: str`, `wake_mode: str`, `hotkey: str`, `wakeword_model_path: str`, `persona_path: str`, `silence_timeout_s: float`, `voice_name: str`, `model_name: str`. Also `config.CONFIG_PATH: Path`.

- [ ] **Step 1: Create `requirements.txt`**

```
google-genai>=0.3.0
sounddevice>=0.4.6
numpy>=1.26
keyboard>=0.13.5
pystray>=0.19.5
Pillow>=10.0
pytest>=8.0
```

- [ ] **Step 2: Create `.gitignore`**

```
__pycache__/
*.pyc
.venv/
venv/
config.json
models/*.onnx
```

- [ ] **Step 3: Create `config.example.json`**

```json
{
  "gemini_api_key": "YOUR_GEMINI_API_KEY_HERE",
  "wake_mode": "hotkey",
  "hotkey": "ctrl+alt+t",
  "wakeword_model_path": "models/tron.onnx",
  "persona_path": "persona.txt",
  "silence_timeout_s": 45.0,
  "voice_name": "Charon",
  "model_name": "gemini-2.0-flash-live-001"
}
```

- [ ] **Step 4: Create `persona.txt`**

```
You are TRON, a personal AI assistant running on the user's own computer.

Always address the user as "sir." Keep your tone formal, economical, and
dry-witted — a butler-AI register, not a chatty consumer assistant. Default
to short, direct responses; elaborate only when asked to. Never break
character or mention that you are a language model unless directly asked
about your own nature.
```

- [ ] **Step 5: Write the failing test**

```python
# tests/test_config.py
import json
import pytest
import config as config_module


def test_load_config_reads_fields(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "gemini_api_key": "test-key",
        "wake_mode": "hotkey",
        "hotkey": "ctrl+alt+t",
        "wakeword_model_path": "models/tron.onnx",
        "persona_path": "persona.txt",
        "silence_timeout_s": 30.0,
        "voice_name": "Charon",
        "model_name": "gemini-2.0-flash-live-001",
    }))
    monkeypatch.setattr(config_module, "CONFIG_PATH", cfg_path)

    cfg = config_module.load_config()

    assert cfg.gemini_api_key == "test-key"
    assert cfg.silence_timeout_s == 30.0
    assert cfg.voice_name == "Charon"


def test_load_config_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "does_not_exist.json")

    with pytest.raises(FileNotFoundError):
        config_module.load_config()
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'config'` (file doesn't exist yet)

- [ ] **Step 7: Write `config.py`**

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
    )
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 9: Commit**

```bash
git add requirements.txt .gitignore config.example.json persona.txt config.py tests/test_config.py
git commit -m "Add project scaffolding and config loader"
```

---

### Task 2: Gemini Live client wrapper

**Files:**
- Create: `gemini_live_client.py`
- Test: `tests/test_gemini_live_client.py`

**Interfaces:**
- Consumes: nothing new (takes plain `str`/`float` args)
- Produces: `GeminiLiveSession(api_key: str, model_name: str, voice_name: str, system_instruction: str)`, used as `async with GeminiLiveSession(...) as session:`. Methods: `await session.send_audio_chunk(pcm_bytes: bytes, sample_rate: int = 16000) -> None` and `async for chunk in session.receive():` yielding `bytes` (empty `b""` signals turn complete).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gemini_live_client.py
import asyncio
from unittest.mock import AsyncMock, MagicMock

import gemini_live_client as glc


class FakeLiveSession:
    def __init__(self):
        self.sent = []
        self._responses = [b"hello-audio", b""]

    async def send_realtime_input(self, audio):
        self.sent.append(audio)

    async def receive(self):
        for chunk in self._responses:
            resp = MagicMock()
            resp.data = chunk if chunk else None
            resp.server_content = MagicMock()
            resp.server_content.turn_complete = (chunk == b"")
            yield resp


class FakeConnectCM:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_send_and_receive(monkeypatch):
    fake_session = FakeLiveSession()

    fake_client = MagicMock()
    fake_client.aio.live.connect = MagicMock(return_value=FakeConnectCM(fake_session))
    monkeypatch.setattr(glc.genai, "Client", MagicMock(return_value=fake_client))

    async def run():
        async with glc.GeminiLiveSession(
            api_key="k", model_name="m", voice_name="Charon", system_instruction="be TRON"
        ) as session:
            await session.send_audio_chunk(b"mic-bytes", sample_rate=16000)
            chunks = []
            async for chunk in session.receive():
                chunks.append(chunk)
                if chunk == b"":
                    break
            return chunks

    chunks = asyncio.run(run())

    assert chunks == [b"hello-audio", b""]
    assert len(fake_session.sent) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gemini_live_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gemini_live_client'`

- [ ] **Step 3: Write `gemini_live_client.py`**

```python
# gemini_live_client.py
from typing import AsyncIterator

from google import genai
from google.genai import types


class GeminiLiveSession:
    """One Gemini Live conversation: PCM audio in, PCM audio (+ optional text) out."""

    def __init__(self, api_key: str, model_name: str, voice_name: str, system_instruction: str):
        self._client = genai.Client(api_key=api_key)
        self._model_name = model_name
        self._config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                )
            ),
            system_instruction=types.Content(parts=[types.Part(text=system_instruction)]),
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

    async def receive(self) -> AsyncIterator[bytes]:
        """Yields raw PCM audio chunks as TRON speaks; yields b"" once per completed turn."""
        async for response in self._session.receive():
            if response.data:
                yield response.data
            if response.server_content and response.server_content.turn_complete:
                yield b""
```

Note: `model_name` and `voice_name` defaults in `config.example.json` (`gemini-2.0-flash-live-001`, `Charon`) match the Gemini Live API at time of writing — verify against [ai.google.dev Live API docs](https://ai.google.dev/gemini-api/docs/live) if you get a "model not found" or "invalid voice" error, since Google revises available Live model IDs and voice names periodically.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gemini_live_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add gemini_live_client.py tests/test_gemini_live_client.py
git commit -m "Add Gemini Live session wrapper"
```

---

### Task 3: Duplex audio I/O

**Files:**
- Create: `audio_io.py`
- Test: `tests/test_audio_io.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `audio_io.SAMPLE_RATE_IN = 16000`, `audio_io.SAMPLE_RATE_OUT = 24000`, `audio_io.DuplexAudio` with `.start() -> None`, `.stop() -> None`, `.play_chunk(pcm_bytes: bytes) -> None`, `.drain_mic() -> bytes`, and attribute `.mic_queue: queue.Queue[bytes]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_audio_io.py
from unittest.mock import MagicMock

import numpy as np

import audio_io


def test_drain_mic_joins_queued_chunks():
    audio = audio_io.DuplexAudio()
    audio.mic_queue.put(b"abc")
    audio.mic_queue.put(b"def")

    assert audio.drain_mic() == b"abcdef"
    assert audio.drain_mic() == b""  # empty queue drains to empty bytes


def test_play_chunk_writes_int16_frames_to_out_stream():
    audio = audio_io.DuplexAudio()
    fake_out = MagicMock()
    audio._out_stream = fake_out

    pcm = np.array([1, 2, 3], dtype=np.int16).tobytes()
    audio.play_chunk(pcm)

    written = fake_out.write.call_args[0][0]
    assert written.shape == (3, 1)
    assert written.dtype == np.int16


def test_play_chunk_ignores_empty_bytes():
    audio = audio_io.DuplexAudio()
    fake_out = MagicMock()
    audio._out_stream = fake_out

    audio.play_chunk(b"")

    fake_out.write.assert_not_called()


def test_start_stop_lifecycle(monkeypatch):
    fake_in = MagicMock()
    fake_out = MagicMock()
    monkeypatch.setattr(audio_io.sd, "InputStream", MagicMock(return_value=fake_in))
    monkeypatch.setattr(audio_io.sd, "OutputStream", MagicMock(return_value=fake_out))

    audio = audio_io.DuplexAudio()
    audio.start()
    fake_in.start.assert_called_once()
    fake_out.start.assert_called_once()

    audio.stop()
    fake_in.stop.assert_called_once()
    fake_out.stop.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_audio_io.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'audio_io'`

- [ ] **Step 3: Write `audio_io.py`**

```python
# audio_io.py
import queue
from typing import Optional

import numpy as np
import sounddevice as sd

SAMPLE_RATE_IN = 16000    # Gemini Live expects 16kHz mono PCM16 input
SAMPLE_RATE_OUT = 24000   # Gemini Live outputs 24kHz mono PCM16
CHANNELS = 1
BLOCK_SIZE = 1600         # 100ms at 16kHz


class DuplexAudio:
    """Captures mic audio into a queue and plays back audio pushed to it."""

    def __init__(self) -> None:
        self.mic_queue: "queue.Queue[bytes]" = queue.Queue()
        self._in_stream: Optional[sd.InputStream] = None
        self._out_stream: Optional[sd.OutputStream] = None

    def _on_mic_block(self, indata, frames, time_info, status) -> None:
        self.mic_queue.put(bytes(indata))

    def start(self) -> None:
        self._in_stream = sd.InputStream(
            samplerate=SAMPLE_RATE_IN, channels=CHANNELS, dtype="int16",
            blocksize=BLOCK_SIZE, callback=self._on_mic_block,
        )
        self._out_stream = sd.OutputStream(
            samplerate=SAMPLE_RATE_OUT, channels=CHANNELS, dtype="int16",
        )
        self._in_stream.start()
        self._out_stream.start()

    def stop(self) -> None:
        for stream in (self._in_stream, self._out_stream):
            if stream is not None:
                stream.stop()
                stream.close()
        self._in_stream = None
        self._out_stream = None

    def play_chunk(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes or self._out_stream is None:
            return
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).reshape(-1, 1)
        self._out_stream.write(audio)

    def drain_mic(self) -> bytes:
        """Pop everything currently buffered from the mic queue as one chunk."""
        chunks = []
        while not self.mic_queue.empty():
            chunks.append(self.mic_queue.get_nowait())
        return b"".join(chunks)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_audio_io.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add audio_io.py tests/test_audio_io.py
git commit -m "Add duplex mic/speaker audio I/O"
```

---

### Task 4: Hotkey trigger

**Files:**
- Create: `wake_trigger.py`
- Test: `tests/test_wake_trigger.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `wake_trigger.HotkeyTrigger(hotkey: str, on_trigger: Callable[[], None])` with `.start() -> None` and `.stop() -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wake_trigger.py
from unittest.mock import MagicMock

import wake_trigger


def test_start_registers_hotkey_and_stop_removes_it(monkeypatch):
    fake_keyboard = MagicMock()
    fake_keyboard.add_hotkey.return_value = "handle-123"
    monkeypatch.setattr(wake_trigger, "keyboard", fake_keyboard)

    on_trigger = MagicMock()
    trigger = wake_trigger.HotkeyTrigger("ctrl+alt+t", on_trigger)

    trigger.start()
    fake_keyboard.add_hotkey.assert_called_once_with("ctrl+alt+t", on_trigger)

    trigger.stop()
    fake_keyboard.remove_hotkey.assert_called_once_with("handle-123")


def test_stop_before_start_is_a_no_op(monkeypatch):
    fake_keyboard = MagicMock()
    monkeypatch.setattr(wake_trigger, "keyboard", fake_keyboard)

    trigger = wake_trigger.HotkeyTrigger("ctrl+alt+t", MagicMock())
    trigger.stop()

    fake_keyboard.remove_hotkey.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_wake_trigger.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wake_trigger'`

- [ ] **Step 3: Write `wake_trigger.py`**

```python
# wake_trigger.py
"""
ponytail: hotkey trigger ships first; a wake-word backend (openWakeWord,
listening for "TRON") needs a trained model — see docs/train_wakeword.md —
and can be wired in later behind this same on_trigger() callback shape.
"""
from typing import Callable, Optional

import keyboard


class HotkeyTrigger:
    """Calls on_trigger() every time the configured global hotkey is pressed."""

    def __init__(self, hotkey: str, on_trigger: Callable[[], None]):
        self._hotkey = hotkey
        self._on_trigger = on_trigger
        self._handle: Optional[str] = None

    def start(self) -> None:
        self._handle = keyboard.add_hotkey(self._hotkey, self._on_trigger)

    def stop(self) -> None:
        if self._handle is not None:
            keyboard.remove_hotkey(self._handle)
            self._handle = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_wake_trigger.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add wake_trigger.py tests/test_wake_trigger.py
git commit -m "Add global hotkey trigger"
```

---

### Task 5: State machine tying audio + Gemini + trigger together

**Files:**
- Create: `state_manager.py`
- Test: `tests/test_state_manager.py`

**Interfaces:**
- Consumes: `audio_io.DuplexAudio` (`.start()`, `.stop()`, `.drain_mic()`, `.play_chunk()`), `gemini_live_client.GeminiLiveSession` (async context manager with `.send_audio_chunk()`, `.receive()`), `audio_io.SAMPLE_RATE_IN`
- Produces: `state_manager.State` enum (`IDLE`, `LISTENING`, `THINKING`, `SPEAKING`, `ERROR`), `state_manager.TronStateMachine(api_key, model_name, voice_name, persona_text, silence_timeout_s, on_state_change=None, audio=None, session_factory=None)` with `.state: State` and `.trigger() -> None` (synchronous — safe to call from a hotkey callback; re-triggerable from `IDLE` or `ERROR`, a no-op while `LISTENING`/`THINKING`/`SPEAKING`).

**State meanings (drive the tray icon color in Task 6):**

| State | Meaning | Color |
|---|---|---|
| `IDLE` | Waiting for the hotkey/wake word | White/gray |
| `LISTENING` | Mic is actively capturing your speech | Blue |
| `THINKING` | You've paused or finished talking, waiting on Gemini | Amber/yellow |
| `SPEAKING` | TRON's response audio is playing | Green |
| `ERROR` | Network/API/quota failure this turn (see spec's error table) | Red |

- [ ] **Step 1: Write the failing test**

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
    def __init__(self, *args, **kwargs):
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def send_audio_chunk(self, pcm_bytes, sample_rate=16000):
        self.sent.append(pcm_bytes)

    async def receive(self):
        yield b"reply-audio"
        yield b""


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
    assert states[0] is sm.State.LISTENING  # set synchronously before any awaiting, so this is deterministic
    assert sm.State.SPEAKING in states       # the fake reply audio must have driven a SPEAKING transition
    assert states[-1] is sm.State.IDLE


def test_trigger_is_a_no_op_while_already_in_a_conversation():
    audio = FakeAudio()
    audio._mic_chunks = []  # never sends anything, so the session stays open for the full timeout

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
    machine.state = sm.State.THINKING  # simulate an in-progress conversation

    machine.trigger()

    assert call_count["n"] == 0  # trigger() while not IDLE/ERROR must not open a second session


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

    machine.trigger()  # must be retriggerable straight from ERROR, not just from IDLE
    assert machine.state is sm.State.IDLE
    assert attempts["n"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_state_manager.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'state_manager'`

- [ ] **Step 3: Write `state_manager.py`**

```python
# state_manager.py
import asyncio
import time
from enum import Enum, auto

from audio_io import DuplexAudio, SAMPLE_RATE_IN
from gemini_live_client import GeminiLiveSession


class State(Enum):
    IDLE = auto()
    LISTENING = auto()
    THINKING = auto()
    SPEAKING = auto()
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
    ):
        self._api_key = api_key
        self._model_name = model_name
        self._voice_name = voice_name
        self._persona_text = persona_text
        self._silence_timeout_s = silence_timeout_s
        self._on_state_change = on_state_change or (lambda state: None)
        self.state = State.IDLE
        self._audio = audio or DuplexAudio()
        self._session_factory = session_factory or (
            lambda: GeminiLiveSession(
                self._api_key, self._model_name, self._voice_name, self._persona_text
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
                    async for chunk in session.receive():
                        if chunk:
                            self._set_state(State.SPEAKING)
                            self._audio.play_chunk(chunk)
                            touch()
                        else:
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

Errors are caught and swallowed here (not re-raised) on purpose: per the design spec's error-handling table, a dropped connection or quota error should surface as a tray color, not crash the process — the hotkey must still work for the next attempt.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_state_manager.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add state_manager.py tests/test_state_manager.py
git commit -m "Add TronStateMachine tying audio, Gemini Live, and triggers together"
```

---

### Task 6: Tray icon UI

**Files:**
- Create: `tray_ui.py`
- Test: `tests/test_tray_ui.py`

**Interfaces:**
- Consumes: `state_manager.State` (`.name` used for status text/color)
- Produces: `tray_ui.TrayUI(quit_callback: Callable[[], None])` with `.start() -> None`, `.stop() -> None`, `.on_state_change(state) -> None` (matches the `on_state_change` shape `TronStateMachine` calls).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tray_ui.py
from unittest.mock import MagicMock

import tray_ui
import state_manager as sm


def test_on_state_change_updates_icon_and_title(monkeypatch):
    fake_icon = MagicMock()
    fake_icon_class = MagicMock(return_value=fake_icon)
    monkeypatch.setattr(tray_ui.pystray, "Icon", fake_icon_class)
    monkeypatch.setattr(tray_ui.pystray, "Menu", MagicMock())
    monkeypatch.setattr(tray_ui.pystray, "MenuItem", MagicMock())

    ui = tray_ui.TrayUI(quit_callback=MagicMock())
    ui.on_state_change(sm.State.LISTENING)

    assert fake_icon.title == "TRON: listening"
    assert fake_icon.icon is not None


def test_each_state_gets_a_distinct_color(monkeypatch):
    fake_icon = MagicMock()
    monkeypatch.setattr(tray_ui.pystray, "Icon", MagicMock(return_value=fake_icon))
    monkeypatch.setattr(tray_ui.pystray, "Menu", MagicMock())
    monkeypatch.setattr(tray_ui.pystray, "MenuItem", MagicMock())

    ui = tray_ui.TrayUI(quit_callback=MagicMock())

    seen_colors = set()
    for state in sm.State:
        ui.on_state_change(state)
        seen_colors.add(tray_ui._COLORS[state.name.lower()])

    assert len(seen_colors) == len(list(sm.State))  # every state maps to its own color


def test_start_launches_background_thread(monkeypatch):
    fake_icon = MagicMock()
    monkeypatch.setattr(tray_ui.pystray, "Icon", MagicMock(return_value=fake_icon))
    monkeypatch.setattr(tray_ui.pystray, "Menu", MagicMock())
    monkeypatch.setattr(tray_ui.pystray, "MenuItem", MagicMock())

    ui = tray_ui.TrayUI(quit_callback=MagicMock())
    ui.start()

    assert ui._thread.daemon is True
    assert ui._thread.is_alive() or fake_icon.run.called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tray_ui.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tray_ui'`

Note: `test_each_state_gets_a_distinct_color` also imports `state_manager` (Task 5), which must exist first — it does, since Task 5 runs before Task 6.

- [ ] **Step 3: Write `tray_ui.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tray_ui.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add tray_ui.py tests/test_tray_ui.py
git commit -m "Add system tray status icon"
```

---

### Task 7: Entry point, end-to-end smoke test, and docs

**Files:**
- Create: `main.py`
- Test: `tests/test_smoke.py`
- Create: `docs/train_wakeword.md`
- Create: `README.md`

**Interfaces:**
- Consumes: `config.load_config`, `state_manager.TronStateMachine`, `wake_trigger.HotkeyTrigger`, `tray_ui.TrayUI` (all as produced above)
- Produces: `main.main() -> None` (script entry point; no other module imports from `main`)

- [ ] **Step 1: Write the failing end-to-end smoke test**

This is the smoke test called for in the design spec: feed a canned trigger through the real `TronStateMachine` (Task 5) with the real `audio_io`/`gemini_live_client` interfaces but fake implementations, and assert a non-empty response comes back and the state machine returns to idle.

```python
# tests/test_smoke.py
from unittest.mock import MagicMock

import state_manager as sm


class ScriptedAudio:
    """Feeds one scripted mic utterance, then silence — simulates a real short exchange."""

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
    """Fake Gemini Live session standing in for the real API in dry-run mode."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def send_audio_chunk(self, pcm_bytes, sample_rate=16000):
        pass

    async def receive(self):
        yield b"yes-sir-i-am-here"
        yield b""


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
    assert b"yes-sir-i-am-here" in audio.played
    assert machine.state is sm.State.IDLE
    assert states[0] is sm.State.LISTENING
    assert sm.State.SPEAKING in states
    assert states[-1] is sm.State.IDLE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_smoke.py -v`
Expected: FAIL — `state_manager` exists already (Task 5), so this should actually PASS immediately since it only depends on already-built modules. Run it now to confirm; if it fails, re-check Task 5's `state_manager.py` against the interface above before continuing.

- [ ] **Step 3: Run test to verify it passes**

Run: `pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 4: Write `main.py`**

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

- [ ] **Step 5: Write `docs/train_wakeword.md`**

```markdown
# Upgrading from hotkey to the "TRON" wake word

The MVP ships with a `Ctrl+Alt+T` hotkey trigger (`wake_trigger.HotkeyTrigger`)
instead of true always-listening wake-word detection, because training a
custom wake-word model is a data/offline step, not application code.

## Generating a "TRON" model with openWakeWord

openWakeWord supports fully synthetic training — it generates training audio
for your target phrase with a TTS voice generator plus room/noise
augmentation, so you don't have to record yourself saying "TRON" dozens of
times.

1. `pip install openwakeword` (adds `onnxruntime`)
2. Follow openWakeWord's `notebooks/automatic_model_training.ipynb`
   (https://github.com/dscripka/openWakeWord) with target phrase `"tron"`.
   CPU training works but is slow; a free Colab GPU runtime is much faster.
3. Export the trained model to `models/tron.onnx` in this project.
4. Set `"wake_mode": "openwakeword"` in `config.json`.
5. Add an `OpenWakeWordTrigger` to `wake_trigger.py` with the same shape as
   `HotkeyTrigger` — a constructor taking `on_trigger: Callable[[], None]`,
   plus a `feed(pcm_int16_chunk)` method called from the mic audio callback
   in `audio_io.py` that runs `openwakeword.Model.predict()` and calls
   `on_trigger()` past your chosen confidence threshold.
6. Wire it into `main.py`'s `if cfg.wake_mode != "hotkey"` branch.
```

- [ ] **Step 6: Write `README.md`**

```markdown
# TRON

A personal voice assistant. Sub-project 1/6 (Voice Core) of the larger TRON
program — see `docs/superpowers/specs/2026-08-09-voice-core-design.md` for
the full design and roadmap.

## Setup

1. Python 3.11 or 3.12.
2. `pip install -r requirements.txt`
3. Get a Gemini API key from https://aistudio.google.com/apikey
4. `cp config.example.json config.json` and fill in `gemini_api_key`
5. `python main.py`
6. Press `Ctrl+Alt+T` (configurable in `config.json`) to talk to TRON. Quit
   from the system tray icon.

## Tests

`pytest`

## Upgrading to a real "TRON" wake word (no hotkey)

See `docs/train_wakeword.md`.
```

- [ ] **Step 7: Run the full test suite**

Run: `pytest -v`
Expected: PASS (all tests across all tasks)

- [ ] **Step 8: Commit**

```bash
git add main.py tests/test_smoke.py docs/train_wakeword.md README.md
git commit -m "Add main entry point, end-to-end smoke test, and setup docs"
```
