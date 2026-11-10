# audio_io.py
import queue
import wave
from typing import Optional

import numpy as np
import sounddevice as sd

SAMPLE_RATE_IN = 16000    # Gemini Live expects 16kHz mono PCM16 input
SAMPLE_RATE_OUT = 24000   # Gemini Live outputs 24kHz mono PCM16
CHANNELS = 1
BLOCK_SIZE = 1600         # 100ms at 16kHz

# There is deliberately no "is this microphone silent?" check here, and one
# should not be added back. It was tried: warn when a short sample reads near
# zero. It fired on a perfectly good headset, because a noise-gated wireless mic
# emits near-digital-silence in a quiet room — measured 0.2 idle on the very
# same device that read 1112 while its owner was speaking, and 0.2 again when
# powered off. Idle level cannot distinguish "muted" from "quiet room", so any
# such check is a coin flip that cries wolf on every launch. The honest way to
# answer "can it hear me" is to watch the level while somebody speaks, which is
# what `--test-mic` does.


def input_devices() -> list[tuple[int, str, int]]:
    """(index, name, channels) for everything that can capture audio."""
    return [(i, d["name"], d["max_input_channels"])
            for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]


def output_devices() -> list[tuple[int, str, int]]:
    """(index, name, channels) for everything that can play audio."""
    return [(i, d["name"], d["max_output_channels"])
            for i, d in enumerate(sd.query_devices()) if d["max_output_channels"] > 0]


def print_audio_devices() -> None:
    """Backs `--list-mics`, which exists so mic_device and speaker_device are
    actually settable — there is otherwise no way to know what to put in them.

    Lists outputs too: TRON replying into a pair of earbuds nobody is wearing
    looks exactly like TRON not replying at all."""
    try:
        default_in, default_out = sd.default.device[0], sd.default.device[1]
    except Exception:
        default_in = default_out = None

    print("Microphones (set as \"mic_device\" in config.json"
          " — index, or any part of the name):\n")
    for index, name, channels in input_devices():
        marker = "  <- Windows default" if index == default_in else ""
        print(f"  [{index:>3}] {name}  ({channels} ch){marker}")

    print("\nSpeakers / headphones (set as \"speaker_device\" — this is where"
          " TRON's voice comes out):\n")
    for index, name, channels in output_devices():
        marker = "  <- Windows default" if index == default_out else ""
        print(f"  [{index:>3}] {name}  ({channels} ch){marker}")


def resolve_input(device):
    """Turn a mic_device setting into something sounddevice can open.

    Passes ints and None through. Resolves a string to the FIRST input device
    whose name contains it, case-insensitively, instead of letting sounddevice
    raise on an ambiguous match — Windows exposes the same physical microphone
    once per audio API, so any name a person would actually type matches several
    devices and would otherwise be unusable. Names are worth supporting because
    indices are not stable: connecting a pair of earbuds renumbered this
    machine's device list mid-session."""
    if isinstance(device, int):
        return device
    if device:
        wanted = str(device).lower()
        for index, name, _channels in input_devices():
            if wanted in name.lower():
                return index
    # Unset, or the named mic isn't connected (a headset unplugged): use what Windows is using right now,
    # never stop to ask. The person picked that default in Windows already.
    return windows_default_input()


def microphone_name(device=None) -> str:
    """Name of the mic TRON will listen on. Raises if it cannot be resolved,
    which is the one microphone problem worth reporting at startup: a
    mic_device naming a device that is not there will never work, whereas a
    quiet one may be perfectly fine."""
    resolved = resolve_input(device)
    return sd.query_devices(resolved if resolved is not None else sd.default.device[0])["name"]


class _Recording:
    """Collects the audio a trigger hears so it can be written out afterwards."""

    def __init__(self):
        self._chunks: list = []

    def add(self, chunk_bytes: bytes) -> None:
        self._chunks.append(chunk_bytes)

    def save(self, path) -> "Optional[str]":
        """Writes a 16 kHz mono PCM16 wav. Returns the path, or None if nothing
        was captured. Uses the stdlib rather than pulling scipy into the app."""
        if not self._chunks:
            return None
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(SAMPLE_RATE_IN)
            out.writeframes(b"".join(self._chunks))
        return str(path)


def record_alongside(trigger) -> _Recording:
    """Tees a wake-word trigger's audio into a _Recording without disturbing it.

    Wraps the trigger's existing on_score hook rather than replacing its audio
    callback, so what gets recorded is exactly the audio the model scored — a
    recording captured through a separate stream would not be the same audio."""
    recording = _Recording()
    original_block = trigger._on_block

    def tee(indata, frames, time_info, status):
        recording.add(bytes(indata))
        return original_block(indata, frames, time_info, status)

    trigger._on_block = tee
    return recording


def resolve_output(device):
    """Same as resolve_input, for where TRON's voice comes out.

    Outputs need this as much as inputs do: Windows lists one endpoint per
    audio API, so "Realtek" matches several devices and sounddevice refuses an
    ambiguous name. Without it speaker_device could only be an index, and
    indices are not stable — plugging in a headset renumbers the list."""
    if isinstance(device, int):
        return device
    if device:
        wanted = str(device).lower()
        for index, name, _channels in output_devices():
            if wanted in name.lower():
                return index
    return windows_default_output()   # unset or not connected: wherever Windows is playing now


def windows_default_input():
    """The microphone Windows is using right now (earbuds, headset, laptop mic...), or None for PortAudio's
    default. Like the speaker: PortAudio fixes its default when it starts, so earbuds connected later were
    never heard. Matched by name on MME (names cut to 31 characters, hence the prefix match)."""
    try:
        from pycaw.pycaw import AudioUtilities
        current = AudioUtilities.GetMicrophone()
        name = getattr(current, "FriendlyName", None)
        if name is None:
            from pycaw.utils import AudioUtilities as AU
            name = AU.CreateDevice(current).FriendlyName
        mme = next(i for i, api in enumerate(sd.query_hostapis()) if api["name"] == "MME")
        for index, device in enumerate(sd.query_devices()):
            if device["hostapi"] == mme and device["max_input_channels"] > 0 \
                    and len(device["name"]) >= 8 and (name or "").startswith(device["name"]):
                return index
    except Exception:
        pass
    return None


def windows_default_output():
    """The device Windows is playing through right now (earbuds, speakers...), or None for PortAudio's own
    default. PortAudio fixes its default when it starts, so switching to Bluetooth earbuds afterwards left
    TRON talking out of the laptop. Matched by name on MME, the API that takes TRON's 24 kHz audio on any
    device; MME cuts names to 31 characters, hence the prefix match."""
    try:
        from pycaw.pycaw import AudioUtilities
        current = AudioUtilities.GetSpeakers().FriendlyName or ""
        mme = next(i for i, api in enumerate(sd.query_hostapis()) if api["name"] == "MME")
        for index, device in enumerate(sd.query_devices()):
            if device["hostapi"] == mme and device["max_output_channels"] > 0                     and len(device["name"]) >= 8 and current.startswith(device["name"]):
                return index
    except Exception:
        pass
    return None


def speaker_name(device=None) -> str:
    """Name of the output TRON's voice will play through."""
    resolved = resolve_output(device)
    return sd.query_devices(resolved if resolved is not None else sd.default.device[1])["name"]


class EchoCanceller:
    """WebRTC echo cancellation, the same processing browsers apply to a microphone, via LiveKit's
    AudioProcessingModule. It is told everything TRON plays and removes that from what the mic hears.

    Measured on this laptop's own speakers and mic: TRON's voice in the mic went from level 482 to 32,
    a 23.7 dB reduction. Without it TRON heard itself and replied to its own sentences ("That would be
    fortune, sir"), and Gemini rarely heard the silence that ends the user's turn. Noise suppression and
    a high-pass filter come with it, for fans and hum."""

    IN_FRAME = SAMPLE_RATE_IN // 100     # 10 ms, the only frame size the module accepts
    OUT_FRAME = SAMPLE_RATE_OUT // 100

    def __init__(self):
        from livekit import rtc
        self._rtc = rtc
        self._apm = rtc.AudioProcessingModule(echo_cancellation=True, noise_suppression=True,
                                              high_pass_filter=True)
        self._leftover = b""   # playback samples short of a whole 10 ms frame

    def set_delay(self, seconds: float) -> None:
        self._apm.set_stream_delay_ms(int(seconds * 1000))

    def played(self, pcm: bytes) -> None:
        """Feed what is about to go to the speakers (24 kHz int16)."""
        data, step = self._leftover + pcm, self.OUT_FRAME * 2
        whole = len(data) - len(data) % step
        for i in range(0, whole, step):
            self._apm.process_reverse_stream(self._rtc.AudioFrame(data[i:i + step], SAMPLE_RATE_OUT, 1, self.OUT_FRAME))
        self._leftover = data[whole:]

    def clean(self, pcm: bytes) -> bytes:
        """The mic block (16 kHz int16) with TRON's own voice taken out."""
        step = self.IN_FRAME * 2
        if len(pcm) % step:
            return pcm   # never happens with BLOCK_SIZE; better unprocessed than misaligned
        out = bytearray()
        for i in range(0, len(pcm), step):
            frame = self._rtc.AudioFrame(pcm[i:i + step], SAMPLE_RATE_IN, 1, self.IN_FRAME)
            self._apm.process_stream(frame)
            out += bytes(frame.data)
        return bytes(out)


def make_echo_canceller():
    """An EchoCanceller, or None when LiveKit isn't installed: TRON then runs as before, on the echo gate."""
    try:
        return EchoCanceller()
    except Exception:
        return None


class DuplexAudio:
    """Captures mic audio into a queue and plays back audio pushed to it."""

    def __init__(self, device=None, output_device=None, echo_canceller="auto") -> None:
        self.mic_queue: "queue.Queue[bytes]" = queue.Queue()
        self._device = device
        self._output_device = output_device
        self._in_stream: Optional[sd.InputStream] = None
        self._out_stream: Optional[sd.OutputStream] = None
        # One for the app's lifetime: it keeps learning the room across conversations.
        self._echo = make_echo_canceller() if echo_canceller == "auto" else echo_canceller

    def _on_mic_block(self, indata, frames, time_info, status) -> None:
        data = bytes(indata)
        if self._echo is not None:
            try:
                data = self._echo.clean(data)
            except Exception:
                pass   # an audio callback must never raise; the raw block is still usable
        self.mic_queue.put(data)

    def start(self) -> None:
        self._in_stream = sd.InputStream(
            samplerate=SAMPLE_RATE_IN, channels=CHANNELS, dtype="int16",
            blocksize=BLOCK_SIZE, callback=self._on_mic_block,
            device=resolve_input(self._device),
        )
        self._out_stream = sd.OutputStream(
            samplerate=SAMPLE_RATE_OUT, channels=CHANNELS, dtype="int16",
            device=resolve_output(self._output_device),
        )
        self._in_stream.start()
        self._out_stream.start()
        if self._echo is not None:
            # How long a played sound takes to come back in through the mic.
            self._echo.set_delay(self._in_stream.latency + self._out_stream.latency)

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
        if self._echo is not None:
            try:
                self._echo.played(pcm_bytes)
            except Exception:
                pass
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).reshape(-1, 1)
        self._out_stream.write(audio)

    def drain_mic(self) -> bytes:
        """Pop everything currently buffered from the mic queue as one chunk."""
        chunks = []
        while not self.mic_queue.empty():
            chunks.append(self.mic_queue.get_nowait())
        return b"".join(chunks)


def rms_level(pcm_bytes: bytes) -> float:
    """Normalized loudness (roughly 0-1) of a PCM16 chunk, for driving audio-reactive UI.
    Speech RMS rarely approaches full-scale, so this is boosted and clamped rather than
    a strict physical measurement — tuned to look right, not to be an accurate meter."""
    if not pcm_bytes:
        return 0.0
    # Drop a trailing odd byte rather than letting frombuffer raise. This is
    # called on audio arriving from the network as well as from the mic, and it
    # now gates the conversation's silence timeout — an exception here would
    # take down the whole conversation over one malformed packet.
    if len(pcm_bytes) % 2:
        pcm_bytes = pcm_bytes[:-1]
        if not pcm_bytes:
            return 0.0
    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
    rms = np.sqrt(np.mean(audio ** 2))
    return min(rms / 32768.0 * 4.0, 1.0)
