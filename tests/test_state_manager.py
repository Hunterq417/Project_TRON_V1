# tests/test_state_manager.py
from unittest.mock import MagicMock

import memory
import perception
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


def test_tool_call_event_dispatches_sends_response_and_logs_activity(monkeypatch):
    import tools

    audio = FakeAudio()
    audio._mic_chunks = []
    states = []

    fake_tool = MagicMock(return_value='opened "notepad"')
    monkeypatch.setitem(tools.TOOL_DISPATCH, "open_target", fake_tool)
    logged = []
    monkeypatch.setattr(memory, "log_activity", lambda entry: logged.append(entry))

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
    assert logged == [{"tool": "open_target", "args": {"name": "notepad"}, "result": 'opened "notepad"'}]
    assert sm.State.ACTING in states
    assert machine.state is sm.State.IDLE


def test_default_session_factory_injects_recent_activity_context(monkeypatch):
    monkeypatch.setattr(
        memory, "recent_context", lambda n=10: "Recent activity (most recent last):\n- did stuff"
    )

    captured = {}

    class FakeGeminiLiveSession:
        def __init__(self, api_key, model_name, voice_name, system_instruction, tools=None):
            captured["system_instruction"] = system_instruction

    monkeypatch.setattr(sm, "GeminiLiveSession", FakeGeminiLiveSession)

    machine = sm.TronStateMachine(
        api_key="k", model_name="m", voice_name="Charon", persona_text="be TRON",
        silence_timeout_s=0.1,
    )

    machine._session_factory()

    assert "be TRON" in captured["system_instruction"]
    assert "did stuff" in captured["system_instruction"]


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
