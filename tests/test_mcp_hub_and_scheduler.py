import datetime
import sys
from pathlib import Path

import brain
import latency
import mcp_hub
import scheduler
import tools

ROOT = Path(__file__).parent.parent


def test_tron_uses_a_real_mcp_server_and_guards_its_writes():
    """End to end over stdio, against TRON's own Google server as a stand-in for Notion or Slack."""
    result = mcp_hub.start({"g": {"command": sys.executable, "args": [str(ROOT / "src" / "google_mcp.py")]}})
    assert result == {"g": "ok"}
    assert "g__gmail_search" in tools.TOOL_DISPATCH
    assert "isn't connected" in tools.TOOL_DISPATCH["g__gmail_search"]({"query": "x"}, None)
    assert "g__gmail_send" in brain.DESTRUCTIVE      # not marked read-only: needs a spoken yes


def test_schedules_run_once_at_their_time(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "PATH", tmp_path / "s.json")
    assert "weekdays" in scheduler.schedule_task({"task": "read my mail", "time": "09:00", "days": "weekdays"})
    items = scheduler._load()
    items[0]["last_run"] = None
    monday9 = datetime.datetime(2026, 11, 16, 9, 5)
    assert [s["task"] for s in scheduler.due(items, monday9)] == ["read my mail"]
    assert scheduler.due(items, monday9.replace(hour=10)) == []                  # missed by over 15 minutes
    assert scheduler.due(items, datetime.datetime(2026, 11, 15, 9, 5)) == []      # Sunday
    items[0]["last_run"] = "2026-11-16"
    assert scheduler.due(items, monday9) == []                                    # already ran today
    assert "Cancelled 1" in scheduler.cancel_schedule({"which": "mail"})


def test_bad_schedule_input_is_explained(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "PATH", tmp_path / "s.json")
    assert "24-hour" in scheduler.schedule_task({"task": "x", "time": "9am"})
    assert "isn't a day" in scheduler.schedule_task({"task": "x", "time": "09:00", "days": "someday"})


def test_latency_is_logged_in_microseconds(tmp_path, monkeypatch):
    monkeypatch.setattr(latency, "PATH", tmp_path / "l.jsonl")
    us = latency.record("response", latency.now_ns() - 1_500_000)   # 1.5 ms ago
    assert 1_500 <= us < 1_000_000
    assert "median" in latency.summary()
