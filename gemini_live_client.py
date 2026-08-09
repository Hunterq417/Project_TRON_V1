# gemini_live_client.py
from typing import Any, AsyncIterator, Dict, List, Optional

from google import genai
from google.genai import types


class GeminiLiveSession:
    """One Gemini Live conversation: PCM audio in, tagged events (audio/tool_call/turn_complete) out."""

    def __init__(
        self,
        api_key: str,
        model_name: str,
        voice_name: str,
        system_instruction: str,
        tools: Optional[List[Dict[str, Any]]] = None,
    ):
        self._client = genai.Client(api_key=api_key)
        self._model_name = model_name

        live_tools = None
        if tools:
            live_tools = [types.Tool(function_declarations=[
                types.FunctionDeclaration(
                    name=t["name"], description=t["description"], parameters=t.get("parameters")
                )
                for t in tools
            ])]

        self._config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                )
            ),
            system_instruction=types.Content(parts=[types.Part(text=system_instruction)]),
            tools=live_tools,
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

    async def send_video_frame(self, jpeg_bytes: bytes) -> None:
        await self._session.send_realtime_input(
            video=types.Blob(data=jpeg_bytes, mime_type="image/jpeg")
        )

    async def send_tool_response(self, call_id: str, name: str, result: str) -> None:
        await self._session.send_tool_response(
            function_responses=[types.FunctionResponse(id=call_id, name=name, response={"result": result})]
        )

    async def receive(self) -> AsyncIterator[Dict[str, Any]]:
        """Yields tagged events: {"type": "audio", "data": bytes},
        {"type": "tool_call", "calls": [...]}, or {"type": "turn_complete"}."""
        async for response in self._session.receive():
            if response.data:
                yield {"type": "audio", "data": response.data}
            if response.tool_call and response.tool_call.function_calls:
                calls = [
                    {"id": fc.id, "name": fc.name, "args": dict(fc.args or {})}
                    for fc in response.tool_call.function_calls
                ]
                yield {"type": "tool_call", "calls": calls}
            if response.server_content and response.server_content.turn_complete:
                yield {"type": "turn_complete"}
