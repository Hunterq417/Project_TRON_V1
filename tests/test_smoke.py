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
