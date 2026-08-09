# tests/test_tools.py
from pathlib import Path
from unittest.mock import MagicMock

import tools


def test_every_declaration_has_a_matching_dispatch_entry():
    declared_names = {d["name"] for d in tools.TOOL_DECLARATIONS}
    dispatched_names = set(tools.TOOL_DISPATCH.keys())
    assert declared_names == dispatched_names


def test_open_target_found(monkeypatch):
    monkeypatch.setattr(tools, "_APP_INDEX_CACHE", {"notepad": Path("C:/x/notepad.lnk")})
    fake_launch = MagicMock()
    monkeypatch.setattr(tools.app_index, "launch", fake_launch)

    result = tools.TOOL_DISPATCH["open_target"]({"name": "notepad"}, None)

    fake_launch.assert_called_once_with(Path("C:/x/notepad.lnk"))
    assert "notepad" in result.lower()


def test_open_target_not_found(monkeypatch):
    monkeypatch.setattr(tools, "_APP_INDEX_CACHE", {"notepad": Path("C:/x/notepad.lnk")})

    result = tools.TOOL_DISPATCH["open_target"]({"name": "spreadsheet thing"}, None)

    assert "could not find" in result.lower()


def test_web_search_opens_browser(monkeypatch):
    fake_open = MagicMock()
    monkeypatch.setattr(tools.webbrowser, "open", fake_open)

    result = tools.TOOL_DISPATCH["web_search"]({"query": "weather today"}, None)

    (called_url,), _ = fake_open.call_args
    assert "weather" in called_url
    assert "weather" in result.lower()


def test_media_tools_delegate_to_media_control(monkeypatch):
    fake_play_pause = MagicMock(return_value="toggled playback")
    monkeypatch.setattr(tools.media_control, "play_pause", fake_play_pause)

    result = tools.TOOL_DISPATCH["media_play_pause"]({}, None)

    fake_play_pause.assert_called_once()
    assert result == "toggled playback"


def test_media_seek_passes_args_through(monkeypatch):
    fake_seek = MagicMock(return_value="skipped forward about 10 seconds")
    monkeypatch.setattr(tools.media_control, "seek", fake_seek)

    tools.TOOL_DISPATCH["media_seek"]({"direction": "forward", "seconds": 10}, None)

    fake_seek.assert_called_once_with("forward", 10)


def test_draft_email_delegates(monkeypatch):
    fake_draft = MagicMock(return_value="Draft text")
    monkeypatch.setattr(tools.email_client, "draft_email", fake_draft)

    result = tools.TOOL_DISPATCH["draft_email"](
        {"to": "a@b.com", "subject": "s", "body": "b"}, None
    )

    fake_draft.assert_called_once_with("a@b.com", "s", "b")
    assert result == "Draft text"


def test_send_email_uses_cfg_smtp_settings(monkeypatch):
    fake_send = MagicMock(return_value="sent to a@b.com")
    monkeypatch.setattr(tools.email_client, "send_email", fake_send)

    fake_cfg = MagicMock(
        smtp_host="smtp.example.com", smtp_port=465,
        smtp_user="me@example.com", smtp_app_password="pw",
    )

    tools.TOOL_DISPATCH["send_email"]({"to": "a@b.com", "subject": "s", "body": "b"}, fake_cfg)

    fake_send.assert_called_once_with(
        "a@b.com", "s", "b",
        smtp_host="smtp.example.com", smtp_port=465,
        smtp_user="me@example.com", smtp_app_password="pw",
    )
