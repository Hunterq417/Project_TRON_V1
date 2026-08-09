# tests/test_memory.py
import json

import memory


def test_log_activity_appends_json_line(tmp_path, monkeypatch):
    log_path = tmp_path / "activity.jsonl"
    monkeypatch.setattr(memory, "_LOG_PATH", log_path)

    memory.log_activity({"tool": "open_target", "args": {"name": "notepad"}, "result": 'opened "notepad"'})

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["tool"] == "open_target"
    assert "at" in record


def test_log_activity_creates_parent_directory(tmp_path, monkeypatch):
    log_path = tmp_path / "nested" / "activity.jsonl"
    monkeypatch.setattr(memory, "_LOG_PATH", log_path)

    memory.log_activity({"tool": "web_search", "args": {}, "result": "ok"})

    assert log_path.exists()


def test_recent_context_empty_when_no_log(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "_LOG_PATH", tmp_path / "does_not_exist.jsonl")
    assert memory.recent_context() == ""


def test_recent_context_formats_recent_entries(tmp_path, monkeypatch):
    log_path = tmp_path / "activity.jsonl"
    monkeypatch.setattr(memory, "_LOG_PATH", log_path)
    memory.log_activity({"tool": "open_target", "args": {"name": "notepad"}, "result": 'opened "notepad"'})
    memory.log_activity({"tool": "web_search", "args": {"query": "weather"}, "result": 'opened a search for "weather"'})

    context = memory.recent_context()

    assert "open_target" in context
    assert "web_search" in context
    assert "notepad" in context


def test_recent_context_limits_to_n_most_recent(tmp_path, monkeypatch):
    log_path = tmp_path / "activity.jsonl"
    monkeypatch.setattr(memory, "_LOG_PATH", log_path)
    for i in range(5):
        memory.log_activity({"tool": f"tool_{i}", "args": {}, "result": "ok"})

    context = memory.recent_context(n=2)

    assert "tool_3" in context
    assert "tool_4" in context
    assert "tool_0" not in context


def test_recent_context_skips_corrupted_lines(tmp_path, monkeypatch):
    log_path = tmp_path / "activity.jsonl"
    monkeypatch.setattr(memory, "_LOG_PATH", log_path)
    good = json.dumps({"tool": "web_search", "args": {}, "result": "ok", "at": "t"})
    log_path.write_text("not valid json\n" + good + "\n")

    context = memory.recent_context()

    assert "web_search" in context


def test_clear_removes_log_file(tmp_path, monkeypatch):
    log_path = tmp_path / "activity.jsonl"
    monkeypatch.setattr(memory, "_LOG_PATH", log_path)
    memory.log_activity({"tool": "x", "args": {}, "result": "ok"})
    assert log_path.exists()

    memory.clear()

    assert not log_path.exists()


def test_clear_is_a_no_op_when_no_log(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "_LOG_PATH", tmp_path / "does_not_exist.jsonl")
    memory.clear()  # must not raise
