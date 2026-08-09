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


def _fake_function_call(call_id, name, args):
    # MagicMock(name=...) sets the mock's repr, not a `.name` attribute — set it after construction.
    fc = MagicMock(id=call_id, args=args)
    fc.name = name
    return fc


def _tool_call_response(calls):
    resp = MagicMock()
    resp.data = None
    resp.tool_call = MagicMock()
    resp.tool_call.function_calls = [
        _fake_function_call(c["id"], c["name"], c["args"]) for c in calls
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
