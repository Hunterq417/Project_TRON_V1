from types import SimpleNamespace

import numpy as np

import faces
import objects
import tools


def unit(*xs):
    v = np.zeros(512, np.float32)
    v[:len(xs)] = xs
    return v / np.linalg.norm(v)


def scene(monkeypatch, vectors):
    """The camera 'sees' one face per vector."""
    monkeypatch.setattr(faces, "detect", lambda frame: [(None, 0.9, i) for i in range(len(vectors))])
    monkeypatch.setattr(faces, "embed", lambda frame, i: vectors[i])


def test_greets_on_arrival_then_not_again_until_they_were_away(tmp_path, monkeypatch):
    monkeypatch.setattr(faces, "_gallery_path", lambda: tmp_path / "faces.json")
    monkeypatch.setattr(faces, "_seen_path", lambda: tmp_path / "seen.json")
    me = unit(1, 0)
    people = {"Mayukh": np.array([me])}
    scene(monkeypatch, [me])
    mem = {}
    assert faces.observe(None, 1000.0, mem, people) == [("Mayukh", None)]          # first time ever
    assert faces.observe(None, 1030.0, mem, people) == []                          # still here: quiet
    back = 1030.0 + faces.AWAY + 60
    assert faces.observe(None, back, mem, people) == [("Mayukh", faces.AWAY + 60)]  # back after a while
    assert faces._seen["name"] == "Mayukh"                         # what the next conversation is told


def test_a_stranger_needs_two_looks_and_is_asked_only_once(tmp_path, monkeypatch):
    monkeypatch.setattr(faces, "_seen_path", lambda: tmp_path / "seen.json")
    scene(monkeypatch, [unit(0, 1)])
    mem, people = {}, {"Mayukh": np.array([unit(1, 0)])}
    assert faces.observe(None, 1.0, mem, people) == []               # a passer-by, glimpsed once
    assert faces.observe(None, 31.0, mem, people) == [(None, None)]  # still there: ask their name
    assert faces.observe(None, 61.0, mem, people) == []              # asked already


def test_learns_a_known_face_in_new_light(tmp_path, monkeypatch):
    monkeypatch.setattr(faces, "_gallery_path", lambda: tmp_path / "faces.json")
    monkeypatch.setattr(faces, "_seen_path", lambda: tmp_path / "seen.json")
    enrolled = unit(1, 0)
    new_light = unit(1, 1.1)                     # similarity ~0.67: clearly them, but a new look
    people = {"Mayukh": np.array([enrolled])}
    scene(monkeypatch, [new_light])
    faces.observe(None, 1.0, {}, people)
    assert len(faces.gallery()["Mayukh"]) == 2


def test_greeting_note_says_name_and_how_long_away():
    assert "Mayukh" in faces.greeting_note("Mayukh", 2 * 3600) and "2.0 hours" in faces.greeting_note("Mayukh", 7200)
    assert "first time" in faces.greeting_note("Mayukh", None)
    assert "ask their name" in faces.greeting_note(None, None)


def test_identify_object_respects_permissions_and_offline():
    off = SimpleNamespace(camera_enabled=False, screen_enabled=False, gemini_api_key="k")
    assert "switched off" in objects.identify_object({}, off)
    assert "switched off" in objects.identify_object({"source": "screen"}, off)
    nokey = SimpleNamespace(camera_enabled=True, screen_enabled=True, gemini_api_key="")
    assert "Gemini key" in objects.identify_object({}, nokey)
    names = lambda cfg: {d["name"] for d in tools.declarations_for(cfg)}
    assert "identify_object" not in names(off) and "identify_object" in names(nokey)


def test_describe_sends_the_picture_with_search_and_returns_the_answer():
    sent = {}

    def generate_content(model, contents, config):
        sent.update(model=model, contents=contents, tools=config.tools)
        return SimpleNamespace(text="A Logitech MX Master 3S wireless mouse (sure: the logo and thumb wheel).")
    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    answer = objects.describe(b"\xff\xd8jpeg", "what mouse is this", "k", client=client)
    assert "MX Master 3S" in answer
    assert sent["contents"][0].inline_data.data == b"\xff\xd8jpeg" and "what mouse is this" in sent["contents"][1]
    assert sent["tools"][0].google_search is not None


def test_falls_back_to_plain_vision_when_search_quota_is_gone():
    calls = []

    def generate_content(model, contents, config):
        calls.append(config)
        if config is not None:
            raise RuntimeError("429 RESOURCE_EXHAUSTED")
        return SimpleNamespace(text="Logitech MX Master 3S wireless mouse")
    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    assert "MX Master 3S" in objects.describe(b"jpeg", "", "k", client=client) and calls[-1] is None
