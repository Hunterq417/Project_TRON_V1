# tests/test_voices.py
"""Voice recognition: matching, collecting speech while TRON listens, face + voice together, enrolment."""
import time
from pathlib import Path

import numpy as np
import pytest

import brain
import config
import faces
import voices


def unit(seed, dim=512):
    v = np.random.default_rng(seed).normal(size=dim).astype(np.float32)
    return v / np.linalg.norm(v)


def test_the_closest_enrolled_voice_is_named_and_strangers_are_not():
    people = {"Shivansh": np.stack([unit(1)]), "Raj": np.stack([unit(2)])}
    near = unit(1) + 0.05 * unit(3)
    assert voices.identify(near / np.linalg.norm(near), people)[0] == "Shivansh"
    assert voices.identify(unit(9), people)[0] is None


def test_enrolment_and_forgetting(monkeypatch):
    monkeypatch.setattr(voices, "embed", lambda audio: unit(1))
    speech = np.ones(voices.SAMPLE_RATE * 8, np.float32)
    assert "know Shivansh's voice" in voices.enroll_voice({"name": "Shivansh", "_audio": speech})
    assert "already belongs to Shivansh" in voices.enroll_voice({"name": "Other", "_audio": speech})
    assert "didn't hear enough" in voices.enroll_voice({"name": "X", "_audio": speech[:100]})
    assert voices.known_voices() == "I know the voices of Shivansh, sir"
    assert voices.forget_voice({"name": "shivansh"}) == "forgot Shivansh's voice, sir"


def test_three_seconds_of_speech_identify_the_speaker_once(monkeypatch):
    monkeypatch.setattr(voices, "embed", lambda audio: unit(1))
    voices._save({"Shivansh": np.stack([unit(1)])})
    voices._heard.update(name=None, at=0.0)
    c = voices.Collector()
    tone = (0.2 * np.sin(np.arange(voices.SAMPLE_RATE) / 5)).astype(np.float32)
    for _ in range(4):
        c.add(tone)
    deadline = time.time() + 3
    while voices.heard()[0] is None and time.time() < deadline:
        time.sleep(0.02)
    assert voices.heard()[0] == "Shivansh"


def test_face_and_voice_together(monkeypatch):
    now = time.time()
    faces._seen.update(name="Shivansh", at=now)
    voices._heard.update(name="Shivansh", sim=0.8, at=now)
    assert "recognised by both face and voice" in voices.context()
    voices._heard.update(name="Raj")
    assert "someone else may be talking" in voices.context()
    faces._seen.update(name=None, at=0.0)
    assert "recognised by voice" in voices.context()
    voices._heard.update(at=0.0)
    assert voices.context() == ""


def test_voices_are_only_forgotten_when_asked():
    guard = brain.Guard()
    guard.user_said("whose voice is that")
    assert guard.check("forget_voice", {"name": "Raj"}).startswith("NOT DONE")


def test_the_real_model_tells_a_voice_from_noise(monkeypatch):
    root = Path(__file__).resolve().parent.parent
    if not (root / "models" / "voices" / "campplus.onnx").exists() or not (root / "mic_test.wav").exists():
        pytest.skip("voice model or recording not present")
    import wave
    monkeypatch.setattr(config, "app_dir", lambda: root)
    with wave.open(str(root / "mic_test.wav")) as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    speech = voices.speech_only(audio)
    a, b = voices.embed(speech[:48000]), voices.embed(speech[96000:144000])
    noise = voices.embed(np.random.default_rng(0).normal(0, 0.05, 48000).astype(np.float32))
    assert float(a @ b) > float(a @ noise) + 0.2
