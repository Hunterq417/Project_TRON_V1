# wake_trigger.py
import threading
from pathlib import Path
from typing import Callable, Optional

import keyboard
import numpy as np
import openwakeword
import sounddevice as sd

import audio_io

_WAKE_SAMPLE_RATE = 16000
_WAKE_BLOCK_SIZE = 1280  # 80ms at 16kHz — openWakeWord's recommended chunk size


class HotkeyTrigger:
    """Calls on_trigger() every time the configured global hotkey is pressed."""

    def __init__(self, hotkey: str, on_trigger: Callable[[], None]):
        self._hotkey = hotkey
        self._on_trigger = on_trigger
        self._handle: Optional[str] = None

    def start(self) -> None:
        self._handle = keyboard.add_hotkey(self._hotkey, self._dispatch)

    def _dispatch(self) -> None:
        # Own thread: on_trigger() runs a whole conversation, and blocking the
        # keyboard library's callback thread queued every press made meanwhile —
        # they then fired after the conversation ended and started another.
        threading.Thread(target=self._on_trigger, daemon=True).start()

    def stop(self) -> None:
        if self._handle is not None:
            keyboard.remove_hotkey(self._handle)
            self._handle = None


def persona_wake_models() -> dict:
    """{model path: assistant id} for the assistants' own wake words. "hey jarvis" ships with openWakeWord;
    nobody publishes "hey friday", so it's used once models/hey_friday.onnx has been trained
    (docs/train_wakeword.md). Missing files are skipped."""
    import config
    jarvis = Path(openwakeword.__file__).parent / "resources" / "models" / "hey_jarvis_v0.1.onnx"
    return {str(jarvis): "jarvis", str(config.app_dir() / "models" / "hey_friday.onnx"): "friday"}


class OpenWakeWordTrigger:
    """Continuously listens on its own mic stream for a trained "hey tron" wake-word
    model (see docs/train_wakeword.md) and calls on_trigger() past a confidence
    threshold.

    Detection dispatches on_trigger() onto its own thread, never the audio
    callback thread — on_trigger() runs a full conversation and can block for
    tens of seconds, and a real-time audio callback that doesn't return promptly
    risks glitching the stream. While a dispatched trigger is in flight, further
    detections are ignored (self-debouncing) until it completes."""

    def __init__(self, model_path: str, on_trigger: Callable[[], None],
                 threshold: float = 0.5, device=None,
                 on_score: Optional[Callable[[float, float], None]] = None,
                 extra_models: Optional[dict] = None, on_assistant: Optional[Callable[[str], None]] = None):
        """extra_models: {model path: assistant id}, e.g. "hey jarvis" -> "jarvis". Hearing one of those
        calls on_assistant(id) before on_trigger(), so the conversation starts as that assistant. "hey tron"
        just wakes whoever is active."""
        if not Path(model_path).exists():
            raise FileNotFoundError(
                f"No wake-word model at {model_path}. Train one first — see "
                'docs/train_wakeword.md — or set "wake_mode": "hotkey" in config.json '
                "to use the hotkey trigger instead."
            )
        extra_models = {p: a for p, a in (extra_models or {}).items() if Path(p).exists()}
        self._model = openwakeword.Model(wakeword_models=[model_path, *extra_models], inference_framework="onnx")
        self._model_key = Path(model_path).stem
        self._assistant_for = {Path(p).stem: a for p, a in extra_models.items()}
        self._on_assistant = on_assistant or (lambda assistant: None)
        self._on_trigger = on_trigger
        self._threshold = threshold
        self._device = device
        # Lets --test-mic watch every block's loudness and score without
        # reaching into this class's internals. None in normal operation.
        self._on_score = on_score
        self._listening = True
        self._stream: Optional[sd.InputStream] = None

    def start(self) -> None:
        self._open()
        threading.Thread(target=self._follow_windows, daemon=True).start()

    def _open(self) -> None:
        self._mic = audio_io.resolve_input(self._device)
        self._stream = sd.InputStream(
            samplerate=_WAKE_SAMPLE_RATE, channels=1, dtype="int16",
            blocksize=_WAKE_BLOCK_SIZE, callback=self._on_block, device=self._mic,
        )
        self._stream.start()

    def _follow_windows(self) -> None:
        """Earbuds connected (or a headset unplugged) after TRON started: Windows switches its default mic,
        and "hey tron" has to be heard on the new one. Checks every few seconds; reopens only on a change."""
        import time
        while self._stream is not None:
            time.sleep(3)
            try:
                mic = audio_io.resolve_input(self._device)
                if mic != self._mic and self._stream is not None:
                    self._stream.stop()
                    self._stream.close()
                    self._open()
            except Exception:
                pass     # a device mid-switch: try again on the next check

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def pause(self) -> None:
        self._listening = False

    def resume(self) -> None:
        self._listening = True

    def _on_block(self, indata, frames, time_info, status) -> None:
        if not self._listening:
            return
        chunk = np.frombuffer(bytes(indata), dtype=np.int16)
        predictions = self._model.predict(chunk)
        key = max([self._model_key, *self._assistant_for], key=lambda k: predictions.get(k, 0.0))
        score = predictions.get(key, 0.0)
        if self._on_score is not None:
            self._on_score(float(np.abs(chunk).mean()), float(score))
        if score > self._threshold:
            self._listening = False  # don't spawn another trigger while this one starts/runs
            threading.Thread(target=lambda: self._fire(key), daemon=True).start()

    def _fire(self, key: str = "") -> None:
        try:
            if key in self._assistant_for:
                try:
                    self._on_assistant(self._assistant_for[key])
                except Exception:
                    pass   # couldn't switch: still answer, as whoever is active
            self._on_trigger()
        finally:
            # The model still holds the audio that fired it; without a reset
            # the first blocks after a conversation can score it again.
            try:
                self._model.reset()
            except Exception:
                pass
            self._listening = True
