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
            # Ask for text alongside the speech. A Live session is audio in,
            # audio out, so without this nothing that happens in a conversation
            # leaves any record at all — there is nothing to summarise, nothing
            # to remember, and the only trace of a session is which tools it
            # happened to call. Verified against the real API before relying on
            # it: the model's reply comes back as text as well as audio.
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
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
        {"type": "tool_call", "calls": [...]}, {"type": "turn_complete"}, or
        {"type": "transcript", "role": "user"|"assistant", "text": str}.

        Transcripts arrive in fragments as the audio streams, not one line per
        turn, so callers must accumulate them rather than treating each event as
        a complete utterance.

        Spans the whole session, not one turn. The SDK's receive() stops at
        each turn_complete, so iterating it once heard exactly one reply and
        then went deaf for the rest of the conversation. It is re-entered after
        every turn; a pass that yields nothing means the connection is done."""
        while True:
            got_any = False
            async for response in self._session.receive():
                got_any = True
                for event in self._events(response):
                    yield event
            if not got_any:
                return

    @staticmethod
    def _events(response):
        """One server message as zero or more tagged events."""
        if response.data:
            yield {"type": "audio", "data": response.data}
        if response.tool_call and response.tool_call.function_calls:
            calls = [
                {"id": fc.id, "name": fc.name, "args": dict(fc.args or {})}
                for fc in response.tool_call.function_calls
            ]
            yield {"type": "tool_call", "calls": calls}

        if getattr(response, "go_away", None) is not None:
            # The session is about to hit its time limit. The client has to close it; one that doesn't is
            # cut off as a "policy violation" (seen 2026-10-07 after a long conversation).
            yield {"type": "go_away"}
        content = response.server_content
        if not content:
            return
        # Only the settled transcription: interim_input_transcription revises
        # itself as the model hears more, so recording it would fill memory
        # with half-heard guesses.
        if content.input_transcription and content.input_transcription.text:
            yield {"type": "transcript", "role": "user",
                   "text": content.input_transcription.text}
        if content.output_transcription and content.output_transcription.text:
            yield {"type": "transcript", "role": "assistant",
                   "text": content.output_transcription.text}
        if content.turn_complete:
            yield {"type": "turn_complete"}
