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
