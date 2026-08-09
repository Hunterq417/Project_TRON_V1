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


def test_recall_activity_returns_context(monkeypatch):
    monkeypatch.setattr(tools.memory, "recent_context", lambda n=10: "Recent activity:\n- did stuff")

    result = tools.TOOL_DISPATCH["recall_activity"]({}, None)

    assert "did stuff" in result


def test_recall_activity_handles_empty_log(monkeypatch):
    monkeypatch.setattr(tools.memory, "recent_context", lambda n=10: "")

    result = tools.TOOL_DISPATCH["recall_activity"]({}, None)

    assert "nothing logged" in result.lower()


def test_forget_recent_activity_clears_log(monkeypatch):
    fake_clear = MagicMock()
    monkeypatch.setattr(tools.memory, "clear", fake_clear)

    result = tools.TOOL_DISPATCH["forget_recent_activity"]({}, None)

    fake_clear.assert_called_once()
    assert "cleared" in result.lower()


def test_declarations_for_excludes_vision_tools_by_default():
    cfg = MagicMock(camera_enabled=False, screen_enabled=False)
    names = {d["name"] for d in tools.declarations_for(cfg)}
    assert "look_at_screen" not in names
    assert "look_via_camera" not in names


def test_declarations_for_includes_screen_when_enabled():
    cfg = MagicMock(camera_enabled=False, screen_enabled=True)
    names = {d["name"] for d in tools.declarations_for(cfg)}
    assert "look_at_screen" in names
    assert "look_via_camera" not in names


def test_declarations_for_includes_camera_when_enabled():
    cfg = MagicMock(camera_enabled=True, screen_enabled=False)
    names = {d["name"] for d in tools.declarations_for(cfg)}
    assert "look_via_camera" in names
    assert "look_at_screen" not in names


def test_declarations_for_handles_none_cfg():
    names = {d["name"] for d in tools.declarations_for(None)}
    assert "look_at_screen" not in names
    assert "look_via_camera" not in names


def test_scan_for_malware_delegates(monkeypatch):
    fake_scan = MagicMock(return_value="scan started, sir")
    monkeypatch.setattr(tools.security_scan, "scan_for_malware", fake_scan)

    result = tools.TOOL_DISPATCH["scan_for_malware"]({}, None)

    fake_scan.assert_called_once_with({}, None)
    assert result == "scan started, sir"


def test_check_scan_status_delegates(monkeypatch):
    fake_check = MagicMock(return_value="no scan has been run yet, sir")
    monkeypatch.setattr(tools.security_scan, "check_scan_status", fake_check)

    result = tools.TOOL_DISPATCH["check_scan_status"]({}, None)

    fake_check.assert_called_once_with({}, None)
    assert result == "no scan has been run yet, sir"
