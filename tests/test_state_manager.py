# tests/test_state_manager.py
import asyncio
import threading
import time
from unittest.mock import MagicMock

import numpy as np

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
        # A live connection stays open after its last message; only hanging up
        # ends receive(), and the state machine now treats that as the end.
        await asyncio.Event().wait()


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


def test_default_session_factory_includes_time_context(monkeypatch):
    class FakeDateTime(sm.datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 8, 10, 21, 30)  # 9:30 PM

    monkeypatch.setattr(sm.datetime, "datetime", FakeDateTime)
    monkeypatch.setattr(memory, "recent_context", lambda n=10: "")

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

    assert "Current time:" in captured["system_instruction"]
    assert "09:30 PM" in captured["system_instruction"]


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


def test_audio_event_reports_rms_level(monkeypatch):
    audio = FakeAudio()
    audio._mic_chunks = []
    levels = []

    monkeypatch.setattr(sm, "rms_level", lambda pcm_bytes: 0.73)

    machine = sm.TronStateMachine(
        api_key="k", model_name="m", voice_name="Charon", persona_text="be TRON",
        silence_timeout_s=0.1,
        audio=audio,
        session_factory=lambda: FakeSession(),
        on_audio_level=levels.append,
    )

    machine.trigger()

    assert 0.73 in levels


def test_on_audio_level_defaults_to_a_no_op():
    audio = FakeAudio()
    audio._mic_chunks = []

    machine = sm.TronStateMachine(
        api_key="k", model_name="m", voice_name="Charon", persona_text="be TRON",
        silence_timeout_s=0.1,
        audio=audio,
        session_factory=lambda: FakeSession(),
    )

    machine.trigger()  # must not raise with no on_audio_level provided

    assert machine.state is sm.State.IDLE


def _pcm(amplitude, n=1600):
    return np.full(n, amplitude, dtype=np.int16).tobytes()


def _finishes_within(machine, seconds):
    """Runs a conversation on its own thread and reports whether it ended.

    trigger() blocks its caller (the app gives it a thread of its own), so a
    conversation that never ends would hang the whole suite rather than fail.
    """
    thread = threading.Thread(target=machine.trigger, daemon=True)
    thread.start()
    thread.join(seconds)
    return not thread.is_alive()


class ConstantAudio(FakeAudio):
    """A microphone that never stops producing blocks — i.e. any real one."""

    def __init__(self, amplitude):
        super().__init__()
        self._amplitude = amplitude

    def drain_mic(self):
        return _pcm(self._amplitude)


def test_a_quiet_microphone_lets_the_conversation_end():
    """Regression: the silence timeout reset on *any* mic data, and a live mic
    always produces data, so it never fired once. Conversations ran until the
    process died, and because the wake trigger stays disabled for the duration,
    "hey tron" worked exactly once per launch."""
    audio = ConstantAudio(amplitude=3)  # room tone, far below speech
    machine = sm.TronStateMachine(
        api_key="k", model_name="m", voice_name="v", persona_text="p",
        silence_timeout_s=0.3, audio=audio,
        session_factory=lambda: FakeSession(events=[]),
    )

    assert _finishes_within(machine, 8), "conversation never ended on a quiet mic"
    assert machine.state is sm.State.IDLE
    assert audio.stopped is True


def test_quiet_audio_still_reaches_gemini():
    """Gemini runs its own turn detection and needs an unbroken stream, so quiet
    blocks must still be sent — they just must not count as activity."""
    audio = ConstantAudio(amplitude=3)
    session = FakeSession(events=[])
    machine = sm.TronStateMachine(
        api_key="k", model_name="m", voice_name="v", persona_text="p",
        silence_timeout_s=0.3, audio=audio, session_factory=lambda: session,
    )

    _finishes_within(machine, 8)

    assert session.sent_audio, "quiet audio should still be streamed to Gemini"


def test_loud_audio_alone_no_longer_holds_the_conversation_open():
    """Music playing near the mic is loud, but it isn't the user talking. Loudness used to count as
    activity, and a conversation with Spotify playing never ended — nor was it ever logged."""
    audio = ConstantAudio(amplitude=6000)  # loud: music, not words
    machine = sm.TronStateMachine(
        api_key="k", model_name="m", voice_name="v", persona_text="p",
        silence_timeout_s=0.4, audio=audio,
        session_factory=lambda: FakeSession(events=[]),
    )
    assert _finishes_within(machine, 3.0), "only transcribed words should keep it open"


def test_transcribed_words_hold_the_conversation_open():
    """The other half of the rule: someone actually talking keeps it alive past the silence timeout."""
    class Chatty(FakeSession):
        async def receive(self):
            import asyncio
            for _ in range(8):   # words keep arriving for ~1.6s, four times the timeout
                yield {"type": "transcript", "role": "user", "text": "and another thing "}
                await asyncio.sleep(0.2)
            await asyncio.Event().wait()

    machine = sm.TronStateMachine(
        api_key="k", model_name="m", voice_name="v", persona_text="p",
        silence_timeout_s=0.4, audio=FakeAudio(), session_factory=lambda: Chatty(),
    )
    assert not _finishes_within(machine, 1.2), "speech should have kept the conversation open"
    machine._silence_timeout_s = 0.0  # let the daemon thread wind down



def test_a_conversation_records_what_was_said():
    """Before transcripts were surfaced, a finished conversation left no trace
    of its content at all — only which tools it happened to call. Nothing could
    be summarised or remembered from that."""
    ended = []
    machine = sm.TronStateMachine(
        api_key="k", model_name="m", voice_name="Charon", persona_text="be TRON",
        silence_timeout_s=0.1,
        audio=FakeAudio(),
        on_conversation_end=ended.append,
        session_factory=lambda: FakeSession([
            {"type": "transcript", "role": "user", "text": "what is"},
            {"type": "transcript", "role": "user", "text": " the date"},
            {"type": "transcript", "role": "assistant", "text": "It's Friday, sir."},
            {"type": "turn_complete"},
        ]),
    )

    machine.trigger()

    assert machine.last_turns == [
        {"role": "user", "text": "what is the date"},
        {"role": "assistant", "text": "It's Friday, sir."},
    ]
    assert ended == [machine.last_turns]


def test_a_conversation_that_errors_still_records_what_was_said():
    """A session that drops mid-way still happened, and what was said before it
    broke is exactly the context needed to pick the thread back up."""
    class ExplodingSession(FakeSession):
        async def receive(self):
            yield {"type": "transcript", "role": "user", "text": "remind me about the deploy"}
            raise RuntimeError("connection dropped")

    ended = []
    machine = sm.TronStateMachine(
        api_key="k", model_name="m", voice_name="Charon", persona_text="be TRON",
        silence_timeout_s=0.1,
        audio=FakeAudio(),
        on_conversation_end=ended.append,
        session_factory=ExplodingSession,
    )

    machine.trigger()

    assert ended == [[{"role": "user", "text": "remind me about the deploy"}]]


def test_a_failing_end_hook_never_breaks_the_conversation():
    """Saving memory is a side errand. If it throws, the conversation must still
    finish cleanly and return to idle."""
    def boom(turns):
        raise RuntimeError("memory disk full")

    machine = sm.TronStateMachine(
        api_key="k", model_name="m", voice_name="Charon", persona_text="be TRON",
        silence_timeout_s=0.1,
        audio=FakeAudio(),
        on_conversation_end=boom,
        session_factory=lambda: FakeSession(),
    )

    machine.trigger()

    assert machine.state is sm.State.IDLE


def test_the_system_prompt_carries_long_term_memory(monkeypatch):
    monkeypatch.setattr(sm.memory, "long_term_context",
                        lambda: "Who the user is:\n- name: Shivansh")
    monkeypatch.setattr(sm.memory, "recent_context", lambda: "")

    machine = sm.TronStateMachine(
        api_key="k", model_name="m", voice_name="Charon", persona_text="be TRON",
        silence_timeout_s=1.0, audio=FakeAudio(),
    )

    assert "name: Shivansh" in machine._system_prompt()


def test_empty_memory_blocks_leave_no_gaps_in_the_prompt(monkeypatch):
    """Most blocks are empty most of the time. An unfiltered join leaves blank
    stretches that read to the model as missing instructions — and a block
    returning None instead of "" would raise here and kill every conversation."""
    monkeypatch.setattr(sm.memory, "long_term_context", lambda: "")
    monkeypatch.setattr(sm.memory, "recent_context", lambda: "")
    monkeypatch.setattr(sm, "_time_context", lambda: "")

    machine = sm.TronStateMachine(
        api_key="k", model_name="m", voice_name="Charon", persona_text="be TRON",
        silence_timeout_s=1.0, audio=FakeAudio(),
    )

    assert machine._system_prompt() == "be TRON\n\n" + sm.brain.HOUSE_RULES


def test_greet_puts_its_instruction_in_the_prompt_then_drops_it():
    """The note is for one conversation. If it stayed set, TRON would open every
    later conversation by greeting you again."""
    machine = sm.TronStateMachine(
        api_key="k", model_name="m", voice_name="Charon", persona_text="be TRON",
        silence_timeout_s=0.1, audio=FakeAudio(),
        session_factory=lambda: FakeSession(),
    )

    machine._pending_note = "greet the user now"
    assert "greet the user now" in machine._system_prompt()
    assert "greet the user now" not in machine._system_prompt()


def test_greet_starts_a_conversation():
    prompts = []

    def factory():
        prompts.append(machine._system_prompt())
        return FakeSession()

    machine = sm.TronStateMachine(
        api_key="k", model_name="m", voice_name="Charon", persona_text="be TRON",
        silence_timeout_s=0.1, audio=FakeAudio(), session_factory=factory,
    )

    machine.greet("say good morning")

    assert prompts and "say good morning" in prompts[0]
    assert machine.state is sm.State.IDLE
