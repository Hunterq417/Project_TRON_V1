# dictation.py
"""Dictation, ported from Hey Jev: TRON records until told to stop, writes it up and pastes it at the cursor.

What changed on the way over:

* Transcription goes to Gemini with the key TRON already has. Jev needed an OpenRouter or OpenAI key for it.
* Stopping is the wake word or the hotkey. Jev ran a second local Whisper model the whole time just to hear
  "stop transcribing"; TRON already has a trigger listening, so that 250MB model buys nothing here.
* Long dictations are cut into chunks at a quiet moment and transcribed while you keep talking, so stopping
  is quick and no request gets near Gemini's size limit.

Kept from Jev: the clean-up prompt, the personal dictionary, the history file, and keeping the audio of any
chunk that failed so nothing said is ever lost.
"""
import collections
import ctypes
import io
import json
import re
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes

import numpy as np

import config

SAMPLE_RATE = 16000
BLOCK = 1600                    # 100ms
CHUNK_SECS = 120                # send audio off in pieces this long while you talk...
CHUNK_GRACE_SECS = 10           # ...waiting up to this much longer for a pause to cut at
MAX_SECS = 15 * 60              # stops by itself, in case the stop never comes
QUIET_RMS = 0.01                # 0-1 loudness under which a block counts as a pause
MODELS = ("gemini-flash-latest", "gemini-flash-lite-latest")  # second is the fallback when the first is busy
SILENCE = "[[no speech]]"
PROMPT = ("Transcribe this recording of one person talking. Remove filler words (um, uh, like) and words "
          "repeated by mistake, and fix obvious mis-starts, but do not reword or summarise anything. If it is "
          "long, split it into paragraphs. Reply with the transcript only, no preamble. If there is no speech "
          f"at all, reply exactly {SILENCE}")


# "hey tron" is how a dictation is stopped, so it's the last thing on the recording. Gemini hears it as
# "hey drone", "hey throne" and so on; strip any of them off the end, like Jev strips "stop transcribing".
_STOP_PHRASE = re.compile(r"[\s,]*\b(?:hey|hi|hay|okay|ok)\W+(?:tron|trons|drone|throne|tran|tram|ron|trawn)\b\W*$",
                          re.I)


def strip_stop_phrase(text: str) -> str:
    return _STOP_PHRASE.sub("", text).rstrip()


def vocab_path():
    return config.app_dir() / "vocabulary.json"


def history_path():
    return config.app_dir() / "memory" / "dictation.jsonl"


def failed_dir():
    return config.app_dir() / "memory" / "dictation_failed"


# --------------------------------------------------------------------------- personal dictionary
def read_vocab() -> dict:
    """{"Word": ["how it gets misheard", ...]}. Empty when there's no dictionary yet."""
    try:
        return json.loads(vocab_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_vocab(words: dict) -> None:
    vocab_path().write_text(json.dumps(words, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def fix_vocab(text: str, words: dict = None) -> str:
    for word, heard in (read_vocab() if words is None else words).items():
        for alt in heard:
            text = re.sub(r"\b" + re.escape(alt) + r"\b", word, text, flags=re.I)
    return text


# --------------------------------------------------------------------------- clipboard and paste
def copy(text: str) -> None:
    """Puts text on the clipboard through Win32 directly (clip.exe leaves a stray byte-order mark)."""
    user32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    k32.GlobalAlloc.restype = k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    data = text.encode("utf-16-le") + bytes(2)  # two zero bytes end a UTF-16 string
    for _ in range(10):  # another app can be holding the clipboard for a moment
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("the clipboard is busy")
    try:
        user32.EmptyClipboard()
        handle = k32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        ctypes.memmove(k32.GlobalLock(handle), data, len(data))
        k32.GlobalUnlock(handle)
        user32.SetClipboardData(13, handle)  # CF_UNICODETEXT; Windows owns the memory from here
    finally:
        user32.CloseClipboard()


def paste(text: str) -> None:
    import keyboard
    copy(text)  # stays on the clipboard too, in case the paste misses
    time.sleep(0.2)
    keyboard.send("ctrl+v")


# --------------------------------------------------------------------------- transcription
def to_wav(pcm16: bytes) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm16)
    return out.getvalue()


def gemini_transcriber(api_key: str):
    """A transcribe(wav_bytes) -> text function using Gemini, retrying and falling back to a lighter model."""
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=api_key)

    def transcribe(wav: bytes) -> str:
        last = None
        for attempt in range(3):
            for model in MODELS:
                try:
                    reply = client.models.generate_content(
                        model=model, contents=[PROMPT, types.Part.from_bytes(data=wav, mime_type="audio/wav")])
                    text = (reply.text or "").strip()
                    return "" if SILENCE in text else text
                except Exception as exc:  # busy or briefly unreachable: try the other model, then again
                    last = exc
            time.sleep(2 ** attempt)
        raise last
    return transcribe


OPENROUTER_MODEL = "openai/gpt-4o-mini-transcribe"
# A hint for a transcription model, not an instruction to a chat model: same wording Jev used.
OPENROUTER_PROMPT = ("The following is a transcript of a person talking, you can remove and duplicated words and "
                     "any fillers words. If its a longer transcript put into paragraphs for better readability.")


def _strip_prompt(text: str) -> str:
    """gpt-4o transcribers sometimes echo their prompt back; Jev's filter, unchanged."""
    cleaned = text
    for part in (OPENROUTER_PROMPT, *OPENROUTER_PROMPT.split(", "), *OPENROUTER_PROMPT.split(". ")):
        cleaned = re.sub(re.escape(part.strip(" .")), "", cleaned, flags=re.I)
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip(" ,.")
    return cleaned if cleaned else text


def openrouter_transcriber(api_key: str):
    """transcribe(wav_bytes) -> text through OpenRouter, the way Hey Jev did it."""
    import base64
    import requests

    def transcribe(wav: bytes) -> str:
        reply = requests.post(
            "https://openrouter.ai/api/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": OPENROUTER_MODEL, "language": "en",
                  "provider": {"options": {"openai": {"prompt": OPENROUTER_PROMPT}}},  # how OpenRouter passes it on
                  "input_audio": {"data": base64.b64encode(wav).decode(), "format": "wav"}},
            timeout=120)
        if not reply.ok:
            raise RuntimeError(f"OpenRouter said {reply.status_code}: {reply.text[:200]}")
        return _strip_prompt(reply.json().get("text", "").strip())
    return transcribe


def local_transcriber():
    """Parakeet on this PC: no internet, no key. Plain words (no tidying of ums) — the cloud ones do that."""
    import offline

    def transcribe(wav: bytes) -> str:
        with wave.open(io.BytesIO(wav)) as w:
            audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        return offline.transcribe(audio)
    return transcribe


def best_transcriber(gemini_key: str, openrouter_key: str = "", local_first: bool = False):
    """OpenRouter first when there's a key for it, Gemini as the fallback.

    Two providers rather than one because each has bad moments — Gemini's flash model answered 503
    "high demand" during testing — and a dictation that can't be transcribed is a lost dictation."""
    providers = []
    if openrouter_key:
        providers.append(("OpenRouter", openrouter_transcriber(openrouter_key)))
    if gemini_key:
        providers.append(("Gemini", gemini_transcriber(gemini_key)))
    # Last resort, or first when TRON runs locally: a dictation must not be lost to a missing connection.
    providers.insert(0 if local_first else len(providers), ("this PC", local_transcriber()))

    def transcribe(wav: bytes) -> str:
        errors = []
        for entry in list(providers):
            name, provider = entry
            try:
                return provider(wav)
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                if " 402" in str(exc) and len(providers) > 1:
                    # Out of credit (OpenRouter wants $0.50 on the account for audio). That won't change
                    # mid-dictation, so stop paying a round trip for it on every chunk.
                    providers.remove(entry)
        raise RuntimeError("; ".join(errors) or "no transcription key set")
    return transcribe


# --------------------------------------------------------------------------- one dictation
class Session:
    """Records from the mic until stop() (or MAX_SECS), transcribing chunks as it goes.

    run() blocks and returns (text, failed_chunks, total_chunks). levels holds recent loudness for the
    waveform bubble."""

    def __init__(self, transcribe, device=None, stream_factory=None):
        self._transcribe = transcribe
        self._device = device
        self._stream_factory = stream_factory or self._open_stream
        self._stop = threading.Event()
        self._pool = ThreadPoolExecutor(3)
        self._lock = threading.Lock()
        self._buffer: list = []
        self._chunks: list = []
        self._last_rms = 0.0
        self.levels = collections.deque(maxlen=40)
        self.stamp = time.strftime("%Y-%m-%d %H-%M-%S")

    def stop(self) -> None:
        self._stop.set()

    @property
    def active(self) -> bool:
        return not self._stop.is_set()

    def _open_stream(self, callback):
        import sounddevice as sd
        import audio_io
        return sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=BLOCK,
                              callback=callback, device=audio_io.resolve_input(self._device))

    def _on_block(self, indata, *_):
        block = bytes(indata)
        samples = np.frombuffer(block, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(samples ** 2))) if samples.size else 0.0
        with self._lock:
            self._buffer.append(block)
            self._last_rms = rms
        self.levels.append(rms)

    def _buffered_secs(self) -> float:
        with self._lock:
            return sum(map(len, self._buffer)) / 2 / SAMPLE_RATE

    def _send(self) -> None:
        with self._lock:
            pcm, self._buffer = b"".join(self._buffer), []
        if pcm:
            part = len(self._chunks) + 1
            self._chunks.append(self._pool.submit(self._transcribe_part, pcm, part))

    def _transcribe_part(self, pcm: bytes, part: int) -> str:
        try:
            return self._transcribe(to_wav(pcm))
        except Exception:
            folder = failed_dir()  # keep the audio so nothing said is lost
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{self.stamp} part {part}.wav").write_bytes(to_wav(pcm))
            raise

    def run(self, poll: float = 0.1, on_stopped=None):
        started = time.time()
        with self._stream_factory(self._on_block):
            while not self._stop.wait(poll):
                if time.time() - started > MAX_SECS:
                    break
                secs = self._buffered_secs()
                quiet = self._last_rms < QUIET_RMS
                if secs >= CHUNK_SECS + CHUNK_GRACE_SECS or (secs >= CHUNK_SECS and quiet):
                    self._send()
        self._stop.set()
        if on_stopped:
            on_stopped()  # mic is closed; what's left is waiting on the transcription
        self._send()
        return self._finish()

    def _finish(self):
        parts, failed = [], 0
        for i, chunk in enumerate(self._chunks):
            try:
                parts.append(chunk.result())
            except Exception as exc:
                failed += 1
                parts.append("[missing part]")  # marks the gap, so it's obvious something is missing
                print(f"dictation chunk {i + 1} of {len(self._chunks)} failed: {exc}")
        self._pool.shutdown(wait=False)
        text = fix_vocab(strip_stop_phrase("\n\n".join(p for p in parts if p).strip()))
        if text and not failed:
            record(text)
        return text, failed, len(self._chunks)


def record(text: str) -> None:
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "text": text}, ensure_ascii=False) + "\n")


def history() -> list:
    """Every dictation, newest first."""
    items = []
    try:
        with history_path().open(encoding="utf-8") as f:
            for line in f:
                try:
                    item = json.loads(line)
                    items.append({"time": item["time"][:16], "text": item["text"]})
                except (ValueError, KeyError):
                    continue  # skip a half-written line
    except OSError:
        pass
    return items[::-1]
