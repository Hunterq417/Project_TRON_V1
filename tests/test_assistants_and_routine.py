import datetime
import json
from pathlib import Path

import config
import routine
import timers
import tools
import brain


def test_switching_assistant_saves_the_choice_and_changes_voice_and_persona(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"gemini_api_key": "k", "active_assistant": "tron"}), encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    assert "FRIDAY" in tools.TOOL_DISPATCH["switch_assistant"]({"name": "Friday"}, None)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["active_assistant"] == "friday" and data["gemini_api_key"] == "k"   # nothing else touched
    friday = config.active_assistant(data)
    assert friday["voice"] == "Aoede" and friday["local_voice"] == "zira"
    assert "only three" in tools.TOOL_DISPATCH["switch_assistant"]({"name": "siri"}, None)


def test_every_persona_shares_the_email_confirmation_rule():
    for a in config.DEFAULT_ASSISTANTS:
        text = (Path(__file__).parent.parent / a["persona_path"]).read_text(encoding="utf-8")
        assert "send_email" in text and a["name"] in text


def test_a_routine_needs_three_different_days_and_is_called_an_inference(tmp_path, monkeypatch):
    monkeypatch.setattr(routine, "_PATH", tmp_path / "routine.jsonl")
    monday = datetime.datetime(2026, 10, 5, 9)
    for week in range(2):
        routine.observe("open_target", {"target": "Spotify"}, now=monday + datetime.timedelta(weeks=week))
    assert routine.patterns() == []                         # two days is not a habit yet
    routine.observe("open_target", {"target": "Spotify"}, now=monday + datetime.timedelta(weeks=2))
    assert routine.patterns() == [("open target (spotify) on Mondays in the morning", 3)]
    assert "not confirmed" in routine.my_routine({}, None)


def test_paused_learning_records_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(routine, "_PATH", tmp_path / "routine.jsonl")
    routine.observe("open_target", {"target": "x"}, cfg=type("C", (), {"memory_enabled": False})())
    assert not (tmp_path / "routine.jsonl").exists()


def test_forgetting_the_routine_needs_the_users_own_words_and_deletes_it(tmp_path, monkeypatch):
    assert "forget_routine" in brain.FORGETTING
    monkeypatch.setattr(routine, "_PATH", tmp_path / "routine.jsonl")
    routine.observe("lock_pc", {})
    assert "deleted" in routine.forget_routine({}, None)
    assert not (tmp_path / "routine.jsonl").exists()


def test_timers_survive_a_restart(tmp_path, monkeypatch):
    store = tmp_path / "timers.json"
    monkeypatch.setattr(timers, "_timers", [])
    monkeypatch.setattr(timers, "_store", store)
    timers.add(600, "tea")
    monkeypatch.setattr(timers, "_timers", [])              # TRON closed
    monkeypatch.setattr(timers, "start_loop", timers.start_loop)
    timers._store = None
    import threading
    monkeypatch.setattr(threading, "Thread", lambda **kw: type("T", (), {"start": lambda self: None})())
    timers.start_loop(lambda t: None, store)
    assert [label for label, _ in timers.snapshot()] == ["Tea"]


