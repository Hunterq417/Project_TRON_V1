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
