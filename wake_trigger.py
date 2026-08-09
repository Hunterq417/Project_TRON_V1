# wake_trigger.py
import threading
from pathlib import Path
from typing import Callable, Optional

import keyboard
import numpy as np
import openwakeword
import sounddevice as sd

_WAKE_SAMPLE_RATE = 16000
_WAKE_BLOCK_SIZE = 1280  # 80ms at 16kHz — openWakeWord's recommended chunk size


class HotkeyTrigger:
    """Calls on_trigger() every time the configured global hotkey is pressed."""

    def __init__(self, hotkey: str, on_trigger: Callable[[], None]):
        self._hotkey = hotkey
        self._on_trigger = on_trigger
        self._handle: Optional[str] = None

    def start(self) -> None:
        self._handle = keyboard.add_hotkey(self._hotkey, self._on_trigger)

    def stop(self) -> None:
        if self._handle is not None:
            keyboard.remove_hotkey(self._handle)
            self._handle = None


class OpenWakeWordTrigger:
    """Continuously listens on its own mic stream for a trained "hey tron" wake-word
    model (see docs/train_wakeword.md) and calls on_trigger() past a confidence
    threshold.

    Detection dispatches on_trigger() onto its own thread, never the audio
    callback thread — on_trigger() runs a full conversation and can block for
    tens of seconds, and a real-time audio callback that doesn't return promptly
    risks glitching the stream. While a dispatched trigger is in flight, further
    detections are ignored (self-debouncing) until it completes."""

    def __init__(self, model_path: str, on_trigger: Callable[[], None], threshold: float = 0.5):
        if not Path(model_path).exists():
            raise FileNotFoundError(
                f"No wake-word model at {model_path}. Train one first — see "
                'docs/train_wakeword.md — or set "wake_mode": "hotkey" in config.json '
                "to use the hotkey trigger instead."
            )
        self._model = openwakeword.Model(wakeword_models=[model_path], inference_framework="onnx")
        self._model_key = Path(model_path).stem
        self._on_trigger = on_trigger
        self._threshold = threshold
        self._listening = True
        self._stream: Optional[sd.InputStream] = None

    def start(self) -> None:
        self._stream = sd.InputStream(
            samplerate=_WAKE_SAMPLE_RATE, channels=1, dtype="int16",
            blocksize=_WAKE_BLOCK_SIZE, callback=self._on_block,
        )
        self._stream.start()

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
        score = predictions.get(self._model_key, 0.0)
        if score > self._threshold:
            self._listening = False  # don't spawn another trigger while this one starts/runs
            threading.Thread(target=self._fire, daemon=True).start()

    def _fire(self) -> None:
        try:
            self._on_trigger()
        finally:
            self._listening = True
