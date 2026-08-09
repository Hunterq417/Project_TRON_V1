# audio_io.py
import queue
from typing import Optional

import numpy as np
import sounddevice as sd

SAMPLE_RATE_IN = 16000    # Gemini Live expects 16kHz mono PCM16 input
SAMPLE_RATE_OUT = 24000   # Gemini Live outputs 24kHz mono PCM16
CHANNELS = 1
BLOCK_SIZE = 1600         # 100ms at 16kHz


class DuplexAudio:
    """Captures mic audio into a queue and plays back audio pushed to it."""

    def __init__(self) -> None:
        self.mic_queue: "queue.Queue[bytes]" = queue.Queue()
        self._in_stream: Optional[sd.InputStream] = None
        self._out_stream: Optional[sd.OutputStream] = None

    def _on_mic_block(self, indata, frames, time_info, status) -> None:
        self.mic_queue.put(bytes(indata))

    def start(self) -> None:
        self._in_stream = sd.InputStream(
            samplerate=SAMPLE_RATE_IN, channels=CHANNELS, dtype="int16",
            blocksize=BLOCK_SIZE, callback=self._on_mic_block,
        )
        self._out_stream = sd.OutputStream(
            samplerate=SAMPLE_RATE_OUT, channels=CHANNELS, dtype="int16",
        )
        self._in_stream.start()
        self._out_stream.start()

    def stop(self) -> None:
        for stream in (self._in_stream, self._out_stream):
            if stream is not None:
                stream.stop()
                stream.close()
        self._in_stream = None
        self._out_stream = None

    def play_chunk(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes or self._out_stream is None:
            return
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).reshape(-1, 1)
        self._out_stream.write(audio)

    def drain_mic(self) -> bytes:
        """Pop everything currently buffered from the mic queue as one chunk."""
        chunks = []
        while not self.mic_queue.empty():
            chunks.append(self.mic_queue.get_nowait())
        return b"".join(chunks)
