# state_manager.py
import asyncio
import time
from enum import Enum, auto

from audio_io import DuplexAudio, SAMPLE_RATE_IN
from gemini_live_client import GeminiLiveSession


class State(Enum):
    IDLE = auto()
    LISTENING = auto()
    THINKING = auto()
    SPEAKING = auto()
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
        audio: DuplexAudio | None = None,
        session_factory=None,
    ):
        self._api_key = api_key
        self._model_name = model_name
        self._voice_name = voice_name
        self._persona_text = persona_text
        self._silence_timeout_s = silence_timeout_s
        self._on_state_change = on_state_change or (lambda state: None)
        self.state = State.IDLE
        self._audio = audio or DuplexAudio()
        self._session_factory = session_factory or (
            lambda: GeminiLiveSession(
                self._api_key, self._model_name, self._voice_name, self._persona_text
            )
        )

    def _set_state(self, state: State) -> None:
        self.state = state
        self._on_state_change(state)

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
                    async for chunk in session.receive():
                        if chunk:
                            self._set_state(State.SPEAKING)
                            self._audio.play_chunk(chunk)
                            touch()
                        else:
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
