# state_manager.py
import asyncio
import time
from enum import Enum, auto

import memory
import perception
import tools
from audio_io import DuplexAudio, SAMPLE_RATE_IN, rms_level
from gemini_live_client import GeminiLiveSession


class State(Enum):
    IDLE = auto()
    LISTENING = auto()
    THINKING = auto()
    SPEAKING = auto()
    ACTING = auto()
    ERROR = auto()


_RETRIGGERABLE = (State.IDLE, State.ERROR)


class TronStateMachine:
    def __init__(
        self,
        api_key: str,
        model_name: str,
        voice_name: str,
        persona_text: str,
        silence_timeout_s: float,
        on_state_change=None,
        on_audio_level=None,
        audio: DuplexAudio | None = None,
        session_factory=None,
        cfg=None,
    ):
        self._api_key = api_key
        self._model_name = model_name
        self._voice_name = voice_name
        self._persona_text = persona_text
        self._silence_timeout_s = silence_timeout_s
        self._on_state_change = on_state_change or (lambda state: None)
        self._on_audio_level = on_audio_level or (lambda level: None)
        self.state = State.IDLE
        self._audio = audio or DuplexAudio()
        self._cfg = cfg
        self._session_factory = session_factory or (
            lambda: GeminiLiveSession(
                self._api_key, self._model_name, self._voice_name,
                self._persona_text + "\n\n" + memory.recent_context(),
                tools=tools.declarations_for(self._cfg),
            )
        )

    def _set_state(self, state: State) -> None:
        self.state = state
        self._on_state_change(state)

    async def _handle_vision_tool(self, name: str, session) -> str:
        try:
            frame = (
                perception.capture_screen_jpeg() if name == "look_at_screen"
                else perception.capture_camera_jpeg()
            )
        except Exception as exc:
            return f"couldn't capture that, sir: {exc}"
        await session.send_video_frame(frame)
        return "here's what I see, sir"

    def trigger(self) -> None:
        """Called by the trigger (hotkey today, wake-word later). Starts a conversation
        from IDLE or ERROR; a no-op while a conversation is already in progress."""
        if self.state in _RETRIGGERABLE:
            asyncio.run(self._run_conversation())

    async def _run_conversation(self) -> None:
        self._audio.start()
        self._set_state(State.LISTENING)
        last_activity = time.monotonic()
        ended_in_error = False

        def touch() -> None:
            nonlocal last_activity
            last_activity = time.monotonic()

        try:
            async with self._session_factory() as session:

                async def send_loop() -> None:
                    was_listening = True
                    while time.monotonic() - last_activity < self._silence_timeout_s:
                        chunk = self._audio.drain_mic()
                        if chunk:
                            if not was_listening:
                                self._set_state(State.LISTENING)
                                was_listening = True
                            await session.send_audio_chunk(chunk, SAMPLE_RATE_IN)
                            touch()
                        elif was_listening:
                            self._set_state(State.THINKING)
                            was_listening = False
                        await asyncio.sleep(0.05)

                async def recv_loop() -> None:
                    async for event in session.receive():
                        if event["type"] == "audio":
                            self._set_state(State.SPEAKING)
                            self._audio.play_chunk(event["data"])
                            self._on_audio_level(rms_level(event["data"]))
                            touch()
                        elif event["type"] == "tool_call":
                            self._set_state(State.ACTING)
                            for call in event["calls"]:
                                if call["name"] in tools.VISION_TOOL_NAMES:
                                    result = await self._handle_vision_tool(call["name"], session)
                                else:
                                    handler = tools.TOOL_DISPATCH[call["name"]]
                                    result = handler(call["args"], self._cfg)
                                memory.log_activity({
                                    "tool": call["name"], "args": call["args"], "result": result
                                })
                                await session.send_tool_response(call["id"], call["name"], result)
                            touch()
                        elif event["type"] == "turn_complete":
                            self._set_state(State.THINKING)

                recv_task = asyncio.create_task(recv_loop())
                try:
                    await send_loop()
                finally:
                    recv_task.cancel()
        except Exception:
            ended_in_error = True
            self._set_state(State.ERROR)
        finally:
            self._audio.stop()
            if not ended_in_error:
                self._set_state(State.IDLE)
