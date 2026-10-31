# tests/test_faces.py
"""Face recognition: matching, enrolment rules, forgetting, and the real models when present."""
from pathlib import Path

import numpy as np
import pytest

import brain
import config
import faces


def unit(seed):
    v = np.random.default_rng(seed).normal(size=512).astype(np.float32)
    return v / np.linalg.norm(v)


def test_the_closest_enrolled_person_is_named_and_strangers_are_not():
    me = unit(1)
    near = me + 0.05 * unit(2)
    near /= np.linalg.norm(near)
    people = {"Shivansh": np.stack([me]), "Raj": np.stack([unit(3)])}
    assert faces.identify(near, people)[0] == "Shivansh"
    assert faces.identify(unit(9), people)[0] is None        # a random face is nobody we know


def test_enrolment_needs_exactly_one_face(monkeypatch):
    monkeypatch.setattr(faces, "camera_frames", lambda n, gap=0.2: [np.zeros((10, 10, 3), np.uint8)] * n)
    monkeypatch.setattr(faces, "detect", lambda f: [(None, 0.9, None), (None, 0.9, None)])
    assert "more than one face" in faces.enroll_face({"name": "Raj"})


def test_enrol_identify_forget_round_trip(monkeypatch):
    me = unit(1)
    monkeypatch.setattr(faces, "camera_frames", lambda n, gap=0.2: [np.zeros((10, 10, 3), np.uint8)] * n)
    monkeypatch.setattr(faces, "detect", lambda f: [((0, 0, 1, 1), 0.9, None)])
    monkeypatch.setattr(faces, "embed", lambda f, m: me)
    assert "recognise Shivansh" in faces.enroll_face({"name": "Shivansh"})
    assert "already belongs to Shivansh" in faces.enroll_face({"name": "Someone"})
    assert faces.who_is_here() == "I can see Shivansh, sir"
    assert faces.known_faces() == "I know the faces of Shivansh, sir"
    assert faces.forget_face({"name": "shivansh"}) == "forgot Shivansh's face, sir"
    assert faces.who_is_here() == "I can see 1 person I don't know, sir"


def test_the_camera_switch_is_respected():
    off = type("C", (), {"camera_enabled": False})()
    assert "switched off" in faces.who_is_here({}, off) and "switched off" in faces.enroll_face({"name": "x"}, off)


def test_faces_are_only_forgotten_when_asked():
    guard = brain.Guard()
    guard.user_said("who is this")
    assert guard.check("forget_face", {"name": "Raj"}).startswith("NOT DONE")


def test_the_real_models_find_no_face_in_an_empty_picture(monkeypatch):
    root = Path(__file__).resolve().parent.parent
    if not (root / "models" / "faces" / "det_10g.onnx").exists():
        pytest.skip("face models not downloaded")
    monkeypatch.setattr(config, "app_dir", lambda: root)
    assert faces.detect(np.zeros((480, 640, 3), np.uint8)) == []
