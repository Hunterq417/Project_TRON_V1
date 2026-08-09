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
