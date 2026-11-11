import asyncio
import json
from unittest.mock import MagicMock

import numpy as np

import config
import state_manager as sm
import voices

SR = voices.SAMPLE_RATE


def setup(tmp_path, monkeypatch, on=True):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"only_obey_owner": on, "owner": "Shivansh"}), encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    me, other = np.eye(192, dtype=np.float32)[0], np.eye(192, dtype=np.float32)[1]
    monkeypatch.setattr(voices, "gallery", lambda: {"Shivansh": np.array([me]), "Mayukh": np.array([other])})
    return me, other


def collector_with(seconds):
    c = MagicMock()
    c.recent.return_value = np.ones(int(seconds * SR), np.float32)
    return c


def test_obeys_the_owner_and_refuses_anyone_else(tmp_path, monkeypatch):
    me, other = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(voices, "embed", lambda audio: me)
    assert voices.owner_refusal(collector_with(2), "open_target") == ""
    monkeypatch.setattr(voices, "embed", lambda audio: other)
    refusal = voices.owner_refusal(collector_with(2), "open_target")
    assert refusal.startswith("REFUSED") and "Mayukh" in refusal and "Only Shivansh" in refusal
    assert voices.owner_refusal(collector_with(2), "not_for_me") == ""        # going quiet is always fine


def test_too_little_voice_is_not_waved_through(tmp_path, monkeypatch):
    me, _ = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(voices, "embed", lambda audio: me)
    assert "say it again" in voices.owner_refusal(collector_with(0.4), "play_music")
    assert voices.owner_refusal(collector_with(0), "read_mail", self_started=True) == ""   # TRON spoke first


def test_off_or_not_enrolled_means_no_lockout(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, on=False)
    assert voices.owner_refusal(collector_with(0), "open_target") == ""
    setup(tmp_path, monkeypatch)
    monkeypatch.setattr(voices, "gallery", lambda: {})                      # owner's voice never learned
    assert voices.owner_refusal(collector_with(0), "open_target") == ""


def test_collector_keeps_only_the_latest_speech(monkeypatch):
    monkeypatch.setattr(voices, "_path", lambda: type("P", (), {"exists": lambda self: True})())
    monkeypatch.setattr(voices, "speech_only", lambda audio: audio)
    monkeypatch.setattr(voices, "_identify_now", lambda audio: None)
    c = voices.Collector()
    for i in range(12):                                   # 12 one-second chunks, numbered
        c.add(np.full(SR, i, np.float32))
    assert c._seconds <= voices.KEEP_SECONDS + 1
    assert set(np.unique(c.recent(2))) == {10, 11}       # the command just spoken, not the start


def test_learning_a_voice_waits_for_the_mic_to_be_free(monkeypatch):
    """The live conversation holds the microphone: enroll_voice used to record silence there, and the model
    retried it ten times. Now it ends the conversation and records afterwards, once."""
    machine = sm.TronStateMachine(api_key="k", model_name="m", voice_name="v", persona_text="p",
                                  silence_timeout_s=1, audio=MagicMock(), session_factory=MagicMock())
    recorded = []
    monkeypatch.setattr(voices, "enroll_voice", lambda args, cfg=None: recorded.append(args) or "ok")
    reply = asyncio.run(machine._run_tool({"name": "enroll_voice", "args": {"name": "Shivansh"}}, None))
    assert recorded == [] and "chime" in reply and machine._enroll_after == "Shivansh"
    assert machine._end_requested_at > 0                  # the conversation wraps up after this sentence
