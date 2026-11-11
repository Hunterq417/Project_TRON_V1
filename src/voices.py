# voices.py
"""Who's speaking: speaker recognition on this PC, the voice counterpart of faces.py.

* Model: 3D-Speaker CAM++ (VoxCeleb, Apache-2.0) via sherpa-onnx - a voiceprint (embedding) of a few seconds
  of speech. models/voices/campplus.onnx next to TRON.
* People: memory/voices.json keeps each enrolled person's voiceprints (never recordings).
* While you talk, TRON collects ~3 s of your speech (not its own: only what the mic hears while TRON is quiet)
  and identifies the speaker in the background; context() tells the brain who it is, together with the face.
"""
import json
import threading
import time

import numpy as np

import config

MATCH = 0.60             # cosine similarity for "same speaker"; your own 3 s clips scored 0.82-0.94
SAMPLE_RATE = 16000
SECONDS_TO_IDENTIFY = 3.0
KEEP_SECONDS = 8.0       # speech kept per conversation, for checking who gave each command
RECENT_SECONDS = 4.0     # the slice a command is checked on
OWNER_MIN_SECONDS = 1.0  # less voice than this can't be told apart reliably
FREE_TOOLS = {"not_for_me"}   # going quiet is always allowed
SAMPLES = 4
_lock = threading.Lock()
_extractor = []
_heard = {"name": None, "sim": 0.0, "at": 0.0}


def _model_path():
    return config.app_dir() / "models" / "voices" / "campplus.onnx"


def extractor():
    import sherpa_onnx
    with _lock:
        if not _extractor:
            path = _model_path()
            if not path.exists():
                raise RuntimeError(f"the voice model isn't in {path.parent}")
            _extractor.append(sherpa_onnx.SpeakerEmbeddingExtractor(
                sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(path), num_threads=2)))
    return _extractor[0]


def embed(audio: np.ndarray) -> np.ndarray:
    """A unit-length voiceprint of float32 16 kHz mono speech (2 s or more is best)."""
    ex = extractor()
    stream = ex.create_stream()
    stream.accept_waveform(SAMPLE_RATE, audio.astype(np.float32))
    stream.input_finished()
    vector = np.array(ex.compute(stream), dtype=np.float32)
    return vector / (np.linalg.norm(vector) + 1e-9)


def _path():
    return config.app_dir() / "memory" / "voices.json"


def gallery() -> dict:
    try:
        return {n: np.array(v, dtype=np.float32) for n, v in json.loads(_path().read_text(encoding="utf-8")).items()}
    except (OSError, ValueError):
        return {}


def _save(people: dict) -> None:
    _path().parent.mkdir(parents=True, exist_ok=True)
    _path().write_text(json.dumps({n: np.round(v, 5).tolist() for n, v in people.items()}), encoding="utf-8")


def identify(vector: np.ndarray, people: dict = None):
    """(name, similarity) of the closest enrolled voice, or (None, best similarity)."""
    people = gallery() if people is None else people
    best, best_sim = None, 0.0
    for name, vectors in people.items():
        sim = float(np.max(vectors @ vector))
        if sim > best_sim:
            best, best_sim = name, sim
    return (best, best_sim) if best_sim >= MATCH else (None, best_sim)


def speech_only(audio: np.ndarray) -> np.ndarray:
    """Drops the quiet stretches (0.1 s blocks), so a voiceprint is made of voice, not room noise."""
    block = SAMPLE_RATE // 10
    blocks = [audio[i:i + block] for i in range(0, len(audio) - block + 1, block)]
    if not blocks:
        return audio[:0]
    levels = np.array([np.sqrt(np.mean(b ** 2)) for b in blocks])
    floor = max(0.008, float(np.percentile(levels, 30)) * 2)    # well above the quiet between words
    if (levels >= floor).sum() < 0.1 * len(levels):              # steady sound with no pauses: keep it
        floor = max(0.008, float(np.median(levels)) * 0.5)
    kept = [b for b, lv in zip(blocks, levels) if lv >= floor]
    return np.concatenate(kept) if kept else audio[:0]


# --------------------------------------------------------------------------- while TRON listens
class Collector:
    """Feed it the user's speech as it arrives; once there are ~3 s of it, it identifies the speaker in the
    background, once per conversation. Never raises into the conversation."""

    def __init__(self):
        self._parts, self._seconds, self._done = [], 0.0, False

    def add_pcm16(self, chunk: bytes) -> None:
        if not chunk:
            return
        try:   # a half sample at the end of a chunk must not end the conversation
            self.add(np.frombuffer(chunk[:len(chunk) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0)
        except Exception:
            self._done = True

    def add(self, audio: np.ndarray) -> None:
        if not _path().exists():
            return
        speech = speech_only(audio)
        if len(speech):
            self._parts.append(speech)
            self._seconds += len(speech) / SAMPLE_RATE
            while len(self._parts) > 1 and self._seconds - len(self._parts[0]) / SAMPLE_RATE >= KEEP_SECONDS:
                self._seconds -= len(self._parts.pop(0)) / SAMPLE_RATE   # keep only the latest speech
        if not self._done and self._seconds >= SECONDS_TO_IDENTIFY:
            self._done = True
            audio_all = np.concatenate(self._parts)
            threading.Thread(target=_identify_now, args=(audio_all,), daemon=True).start()

    def recent(self, seconds: float = RECENT_SECONDS) -> np.ndarray:
        """The latest `seconds` of the speaker's voice: what the last command was said in."""
        if not self._parts:
            return np.zeros(0, np.float32)
        return np.concatenate(self._parts)[-int(seconds * SAMPLE_RATE):]


def _identify_now(audio: np.ndarray) -> None:
    try:
        name, sim = identify(embed(audio))
        _heard.update(name=name, sim=round(sim, 2), at=time.time())
    except Exception:
        pass


def heard(max_age: float = 600.0):
    """(name or None, similarity) from the latest voice check, if recent."""
    if time.time() - _heard["at"] < max_age:
        return _heard["name"], _heard["sim"]
    return None, 0.0


def context() -> str:
    """Who's at the PC, by face and voice, as a line for the system prompt ("" when neither knows)."""
    import faces
    face = faces._seen["name"] if time.time() - faces._seen["at"] < 300 else None
    voice, _sim = heard()
    if face and voice and face == voice:
        who, how = face, "recognised by both face and voice"
    elif face and voice:
        return (f"The camera sees {face} but the voice sounds like {voice}: someone else may be talking. Be "
                "careful with anything personal until it's clear who it is.")
    elif face or voice:
        who, how = face or voice, "recognised by " + ("face" if face else "voice")
    else:
        return ""
    return f"The person at the PC is {who} ({how}). Address them by name and use what you know about them."


# --------------------------------------------------------------------------- tools
def record(seconds: float, device=None) -> np.ndarray:
    """Up to `seconds` of the user's speech from the mic (stops early in silence)."""
    import offline
    parts, total, started = [], 0.0, time.time()
    while total < seconds and time.time() - started < seconds + 12:
        audio = offline.listen(device, wait_for_speech=5.0, max_secs=min(10.0, seconds))
        if audio is None:
            break
        speech = speech_only(audio)
        parts.append(speech)
        total += len(speech) / SAMPLE_RATE
    return np.concatenate(parts) if parts else np.zeros(0, np.float32)


def enroll_voice(args, cfg=None) -> str:
    """Tool: learn a person's voice from ~8 s of them talking after the chime."""
    name = str((args or {}).get("name", "")).strip()
    if not name:
        return "whose voice is this, sir?"
    audio = (args or {}).get("_audio")
    if audio is None:
        try:   # the cue to start talking (and a moment for TRON to finish its own sentence)
            import winsound
            time.sleep(1.5)
            winsound.PlaySound(r"C:\Windows\Media\Speech On.wav", winsound.SND_FILENAME)
        except Exception:
            pass
        audio = record(8.0, getattr(cfg, "mic_device", None))
    if len(audio) < SAMPLE_RATE * 4:
        return "I didn't hear enough speech, sir. Talk for about eight seconds and try again."
    third = len(audio) // 3
    vectors = [embed(audio[i * third:(i + 1) * third]) for i in range(3)] + [embed(audio)]
    people = gallery()
    for other, vecs in people.items():
        if other.lower() != name.lower() and float(np.max(vecs @ vectors[-1])) >= MATCH + 0.1:
            return f"that voice already belongs to {other}, sir. Forget {other}'s voice first if that's wrong."
    current = list(people.get(name, np.zeros((0, len(vectors[0])), np.float32)))
    people[name] = np.array((current + vectors)[-SAMPLES * 2:], dtype=np.float32)
    _save(people)
    return f"I'll know {name}'s voice from now on, sir."


def who_is_speaking(args=None, cfg=None) -> str:
    """Tool: who TRON thinks is talking (from the latest few seconds of speech)."""
    name, sim = heard()
    if name:
        return f"the voice I'm hearing is {name}'s (match {sim:.2f}), sir"
    if not gallery():
        return "I don't know anyone's voice yet, sir"
    return "I don't recognise the voice I'm hearing, sir"


def forget_voice(args, cfg=None) -> str:
    name = str((args or {}).get("name", "")).strip()
    people = gallery()
    match = next((n for n in people if n.lower() == name.lower()), None)
    if not match:
        return f"I don't know a voice called {name}, sir"
    del people[match]
    _save(people)
    return f"forgot {match}'s voice, sir"


def known_voices(args=None, cfg=None) -> str:
    people = gallery()
    return ("I know the voices of " + ", ".join(people) + ", sir") if people else "I don't know anyone's voice yet, sir"


# --------------------------------------------------------------------------- only obey the owner
def owner() -> str:
    """Whose voice TRON obeys when only_obey_owner is on: config "owner", else the user's remembered name."""
    try:
        data = json.loads(config.CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not data.get("only_obey_owner"):
        return ""
    if data.get("owner"):
        return str(data["owner"])
    import memory
    return next((str(f["value"]) for f in memory.all_facts() if f.get("key") == "name"), "")


def owner_refusal(collector, tool: str, self_started: bool = False) -> str:
    """"" when the action may run; otherwise why not, phrased for the model to pass on politely.
    Only when only_obey_owner is on and the owner's voice is enrolled: without an enrolled voice there is
    nothing to check against, and locking everyone out (the owner included) would be worse."""
    name = owner()
    people = gallery()
    match = next((n for n in people if n.lower() == name.lower()), None) if name else None
    if match is None or tool in FREE_TOOLS:
        return ""
    audio = collector.recent() if collector is not None else np.zeros(0, np.float32)
    if self_started and not len(audio):
        return ""   # TRON opened this conversation itself (a greeting, a scheduled task) and nobody spoke yet
    if len(audio) < SAMPLE_RATE * OWNER_MIN_SECONDS:
        return (f"REFUSED: I couldn't hear enough of the voice to be sure it's {match}. Ask them to say it again, "
                "a little longer. Do nothing else.")
    heard_name, _sim = identify(embed(audio), people)
    if heard_name == match:
        return ""
    who = f"it sounds like {heard_name}" if heard_name else "it isn't a voice I know"
    return (f"REFUSED: that voice isn't {match}'s ({who}). Only {match} can give me commands: say so politely "
            "in one sentence and do nothing.")
