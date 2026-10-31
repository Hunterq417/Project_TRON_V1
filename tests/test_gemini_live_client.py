# tests/test_gemini_live_client.py
import asyncio
from unittest.mock import MagicMock

import gemini_live_client as glc


def _server_content(**kwargs):
    """server_content with every branch off unless a test turns one on.

    A bare MagicMock answers truthily to every attribute, so leaving
    input_transcription/output_transcription unset made responses that carry no
    transcript at all yield transcript events."""
    content = MagicMock()
    content.turn_complete = False
    content.input_transcription = None
    content.output_transcription = None
    for key, value in kwargs.items():
        setattr(content, key, value)
    return content


def _transcription(text):
    fragment = MagicMock()
    fragment.text = text
    return fragment


def _audio_response(data):
    resp = MagicMock()
    resp.go_away = None   # a real response only has one when the session is ending
    resp.data = data
    resp.tool_call = None
    resp.server_content = _server_content()
    return resp


def _fake_function_call(call_id, name, args):
    # MagicMock(name=...) sets the mock's repr, not a `.name` attribute — set it after construction.
    fc = MagicMock(id=call_id, args=args)
    fc.name = name
    return fc


def _tool_call_response(calls):
    resp = MagicMock()
    resp.go_away = None   # a real response only has one when the session is ending
    resp.data = None
    resp.tool_call = MagicMock()
    resp.tool_call.function_calls = [
        _fake_function_call(c["id"], c["name"], c["args"]) for c in calls
    ]
    resp.server_content = None
    return resp


def _turn_complete_response():
    resp = MagicMock()
    resp.go_away = None   # a real response only has one when the session is ending
    resp.data = None
    resp.tool_call = None
    resp.server_content = _server_content(turn_complete=True)
    return resp


def _transcript_response(role, text):
    resp = MagicMock()
    resp.go_away = None   # a real response only has one when the session is ending
    resp.data = None
    resp.tool_call = None
    key = "input_transcription" if role == "user" else "output_transcription"
    resp.server_content = _server_content(**{key: _transcription(text)})
    return resp


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
        # Consumed, like a real socket: a second call must not replay them.
        responses, self._responses = self._responses, []
        for resp in responses:
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


def test_receive_yields_transcripts_for_both_sides(monkeypatch):
    """A Live session is audio in, audio out. Without transcripts nothing that
    happens in a conversation leaves any record, so there is nothing to
    summarise or remember afterwards."""
    fake_session = FakeLiveSession([
        _transcript_response("user", "what is the date"),
        _transcript_response("assistant", "It's Friday, sir."),
        _turn_complete_response(),
    ])
    _connect(monkeypatch, fake_session)

    async def run():
        async with glc.GeminiLiveSession(
            api_key="k", model_name="m", voice_name="Charon", system_instruction="be TRON"
        ) as session:
            return [event async for event in session.receive()]

    assert asyncio.run(run()) == [
        {"type": "transcript", "role": "user", "text": "what is the date"},
        {"type": "transcript", "role": "assistant", "text": "It's Friday, sir."},
        {"type": "turn_complete"},
    ]


def test_transcription_is_requested_in_the_session_config(monkeypatch):
    """Transcripts only arrive if both directions are asked for up front; there
    is no way to turn them on once the session is open."""
    _connect(monkeypatch, FakeLiveSession([]))
    session = glc.GeminiLiveSession(
        api_key="k", model_name="m", voice_name="Charon", system_instruction="be TRON"
    )
    assert session._config.input_audio_transcription is not None
    assert session._config.output_audio_transcription is not None
