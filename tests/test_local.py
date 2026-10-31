# tests/test_local.py
"""TRON with no Gemini: the local brain's tool loop, the voice's sentence splitting, and the speaker that
follows Windows."""
import datetime
from types import SimpleNamespace

import pytest

import audio_io
import brain
import local_brain
import state_manager as sm
import tts
from tests.test_state_manager import FakeAudio


class FakeOllama:
    """Plays back scripted /api/chat replies and remembers what TRON sent."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.sent = []

    def __call__(self, url, json, timeout):
        self.sent.append(json)
        message = self.replies.pop(0)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"message": message})


def call(name, **args):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}


def test_a_tool_that_already_speaks_is_said_without_asking_the_model_again():
    ollama = FakeOllama(call("set_radio", kind="bluetooth", enabled=False))
    ran = []
    reply = local_brain.LocalBrain(post=ollama).reply(
        "turn off bluetooth", brain.Guard(), lambda n, a: ran.append((n, a)) or "Bluetooth is off, sir")
    assert reply == "Bluetooth is off, sir"
    assert ran == [("set_radio", {"kind": "bluetooth", "enabled": False})]
    assert len(ollama.sent) == 1          # one model round, not two


def test_a_tool_returning_data_goes_back_to_the_model_to_answer():
    ollama = FakeOllama(call("hardware_status"), {"role": "assistant", "content": "Your CPU is fine, sir."})
    reply = local_brain.LocalBrain(post=ollama).reply(
        "how is my pc doing", brain.Guard(), lambda n, a: "CPU is at 9 percent, memory 42 percent, ...")
    assert reply == "Your CPU is fine, sir."
    assert ollama.sent[1]["messages"][-1]["role"] == "tool"


def test_the_safety_check_still_guards_the_local_brain():
    ollama = FakeOllama(call("shutdown_pc"), {"role": "assistant", "content": "Shall I shut down the PC?"})
    ran = []
    guard = brain.Guard()
    guard.user_said("shut down my pc")
    reply = local_brain.LocalBrain(post=ollama).reply("shut down my pc", guard, lambda n, a: ran.append(n) or "x")
    assert ran == [] and reply == "Shall I shut down the PC?"


def test_every_request_carries_the_real_time_and_a_big_enough_context():
    """A local model has no clock (Qwen3.5-9B said "10:45 AM, 2023"), and at Ollama's default context the
    52 tool descriptions were cut off and the model answered nonsense."""
    ollama = FakeOllama({"role": "assistant", "content": "Hello, sir."})
    local_brain.LocalBrain(post=ollama).reply("hi", brain.Guard(), lambda n, a: "")
    body = ollama.sent[0]
    assert datetime.datetime.now().strftime("%d %B %Y") in body["messages"][0]["content"]
    assert body["options"]["num_ctx"] >= 16384 and body["think"] is False
    assert len(body["tools"]) > 40


def test_a_local_session_hears_thinks_and_speaks_until_shut_up(monkeypatch):
    ollama = FakeOllama(call("current_time"))
    said = iter(["what time is it", "shut up"])
    spoken = []
    session = local_brain.LocalSession(
        SimpleNamespace(mic_device=None), hear=lambda: next(said, None), speak=spoken.append,
        local_brain=local_brain.LocalBrain(post=ollama))
    monkeypatch.setitem(local_brain.tools.TOOL_DISPATCH, "current_time", lambda a, c: "it's 10:36 PM, sir")
    monkeypatch.setattr("winsound.PlaySound", lambda *a: None)
    session.run()
    assert spoken == ["it's 10:36 PM, sir"]
    assert ("note", 'stopped: "shut up" means stop talking') in session.log


def test_local_mode_never_touches_gemini(monkeypatch):
    ran = []
    monkeypatch.setattr(sm.TronStateMachine, "_run_local", lambda self: ran.append("local"))
    machine = sm.TronStateMachine("k", "m", "v", "p", 1, audio=FakeAudio(), cfg=SimpleNamespace(brain="local"),
                                  session_factory=lambda: pytest.fail("Gemini must not be used in local mode"))
    machine.trigger()
    assert ran == ["local"]


def test_kokoro_gets_whole_sentences_and_no_tiny_fragments():
    assert tts.sentences("Bluetooth is off, sir. Anything else?") == ["Bluetooth is off, sir.", "Anything else?"]
    assert tts.sentences("Ok. Done, sir.") == ["Ok. Done, sir."]


def test_the_speaker_follows_windows_when_not_pinned(monkeypatch):
    monkeypatch.setattr(audio_io, "windows_default_output", lambda: 7)
    assert audio_io.resolve_output(None) == 7
    assert audio_io.resolve_output(3) == 3


def test_microsoft_david_is_the_default_voice():
    audio, rate = tts.synth("Ready.")
    assert tts.VOICE == "david" and rate == 22050 and 0.3 < len(audio) / rate < 3


def test_a_request_cut_off_mid_sentence_keeps_listening(monkeypatch):
    import offline
    heard = iter(["Open Spotify and play", "blinding lights"])
    monkeypatch.setattr(offline, "listen", lambda *a, **k: "audio")
    monkeypatch.setattr(offline, "transcribe", lambda audio: next(heard))
    session = local_brain.LocalSession(SimpleNamespace(mic_device=None), local_brain=local_brain.LocalBrain(post=FakeOllama()))
    assert session._listen(offline) == "Open Spotify and play blinding lights"


def test_sending_an_email_needs_a_spoken_yes():
    guard = brain.Guard()
    guard.user_said("show me first")
    assert guard.check("send_email", {"to": "Mayuk"}).startswith("NOT DONE")


def test_the_song_asked_for_beats_its_remix():
    import music
    assert music.choose("blinding lights", ["Blinding Lights - Instrumental", "Blinding Lights"]) == 1
    assert music.choose("blinding lights remix", ["Blinding Lights", "Blinding Lights - Remix"]) == 1
    assert music.choose("blinding lights", ["Blinding Lights - Instrumental", "Starboy"]) == 0


def test_the_local_brain_switch_stops_ollama_being_started(tmp_path, monkeypatch):
    import config
    import json
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"local_brain_enabled": False}), encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    started = []
    monkeypatch.setattr(local_brain.subprocess, "Popen", lambda *a, **k: started.append(a))
    assert not local_brain.enabled() and local_brain.ensure_server() is False and started == []
    path.write_text("{}", encoding="utf-8")
    assert local_brain.enabled()
