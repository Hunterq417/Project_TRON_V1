# tts.py
"""TRON's own voice, generated on this PC: Kokoro-82M, the engine inside Voicebox.

Voicebox was tested here first (its PyTorch Kokoro, 2.6x real time on this CPU). Running the whole Voicebox
app as a server just to reach that engine would mean a second program, its own Python 3.12 and several GB
of dependencies; kokoro-onnx runs the same model and voices inside TRON. Measured on this laptop: about a
second per sentence (2.4x real time). The int8 build was slower here (0.6x) and isn't used.

TRON's default voice is Windows' own Microsoft David (SAPI, rendered to memory so it plays through the same
speaker and stops on the same hotkey); set VOICE to a Kokoro voice name such as "am_michael" to use Kokoro.

Long replies are spoken sentence by sentence, so the first words play while the rest is still being made.
"""
import re
import threading

import config

VOICE = "david"          # Microsoft David; "am_michael" is the Kokoro voice closest to TRON's Gemini voice
WINDOWS_VOICES = ("david", "zira", "hazel")   # installed with Windows; anything else is a Kokoro voice
KOKORO_VOICES = ("am_michael", "am_adam", "bm_george", "bm_lewis", "af_heart", "bf_emma")
SPEED = 1.05
_sapi = threading.local()   # SAPI is a COM object: one per thread
_engine = None
_lock = threading.Lock()


def engine():
    global _engine
    with _lock:
        if _engine is None:
            from kokoro_onnx import Kokoro
            folder = config.app_dir() / "models" / "kokoro"
            _engine = Kokoro(str(folder / "kokoro-v1.0.onnx"), str(folder / "voices-v1.0.bin"))
    return _engine


def _windows_voice(sentence: str, name: str):
    import comtypes
    import comtypes.client
    import numpy as np
    if not hasattr(_sapi, "voice"):
        comtypes.CoInitialize()
        _sapi.voice, _sapi.name = comtypes.client.CreateObject("SAPI.SpVoice"), None
    if _sapi.name != name:
        for token in _sapi.voice.GetVoices():
            if name in token.GetDescription().lower():
                _sapi.voice.Voice = token
                break
        _sapi.name = name
    stream = comtypes.client.CreateObject("SAPI.SpMemoryStream")
    stream.Format.Type = 22                  # SAFT22kHz16BitMono
    _sapi.voice.AudioOutputStream = stream
    _sapi.voice.Speak(sentence)
    return np.frombuffer(bytes(stream.GetData()), dtype=np.int16).astype(np.float32) / 32768, 22050


def synth(sentence: str):
    """(audio, sample_rate) for one sentence in TRON's voice."""
    if VOICE in WINDOWS_VOICES:
        return _windows_voice(sentence, VOICE)
    return engine().create(sentence, voice=VOICE, speed=SPEED, lang="en-us")


def sentences(text: str) -> list:
    """Splits on sentence ends; tiny fragments ride along with the next sentence."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]
    merged = []
    for part in parts:
        if merged and len(merged[-1]) < 12:
            merged[-1] += " " + part
        else:
            merged.append(part)
    return merged


def say(text: str, device=None, stop: threading.Event = None) -> None:
    """Speaks text through `device` (None follows Windows' current output). Returns when done, or as soon
    as `stop` is set — the next sentence is never started after an interruption."""
    import queue
    import sounddevice as sd
    import audio_io
    clips: queue.Queue = queue.Queue(maxsize=2)

    def make():
        for sentence in sentences(text):
            if stop is not None and stop.is_set():
                break
            clips.put(synth(sentence))
        clips.put(None)

    threading.Thread(target=make, daemon=True).start()
    output = audio_io.resolve_output(device)
    while True:
        clip = clips.get()
        if clip is None or (stop is not None and stop.is_set()):
            sd.stop()
            return
        sd.play(clip[0], clip[1], device=output)
        sd.wait()
