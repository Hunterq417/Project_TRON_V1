# tests/test_tools.py
from pathlib import Path
from unittest.mock import MagicMock

import tools


def test_every_declaration_has_a_matching_dispatch_entry():
    declared_names = {d["name"] for d in tools.TOOL_DECLARATIONS}
    dispatched_names = set(tools.TOOL_DISPATCH.keys())
    # control tools (start_dictation) are handled by the state machine, not the dispatch table
    assert declared_names == dispatched_names | tools.CONTROL_TOOL_NAMES


def test_open_target_uses_direct_launch_as_a_last_resort(monkeypatch):
    """Direct launch runs only after the Windows app list and the shortcut
    index. It used to run first, which was wrong twice over: os.startfile
    succeeds for some bare names without starting anything, and going first let
    it swallow requests the app list would have answered correctly."""
    monkeypatch.setattr(tools.app_index, "resolve_start_app", lambda name: None)
    monkeypatch.setattr(tools.app_index, "resolve", lambda name, index: None)
    fake_try_direct = MagicMock(return_value=True)
    monkeypatch.setattr(tools.app_index, "try_direct_launch", fake_try_direct)

    result = tools.TOOL_DISPATCH["open_target"]({"name": "regedit"}, None)

    fake_try_direct.assert_called_once_with("regedit")
    assert "regedit" in result.lower()


def test_open_target_found(monkeypatch):
    monkeypatch.setattr(tools.app_index, "resolve_start_app", lambda name: None)
    monkeypatch.setattr(tools.app_index, "try_direct_launch", lambda name: False)
    monkeypatch.setattr(tools, "_APP_INDEX_CACHE", {"chrome": Path("C:/x/chrome.lnk")})
    fake_launch = MagicMock()
    monkeypatch.setattr(tools.app_index, "launch", fake_launch)

    result = tools.TOOL_DISPATCH["open_target"]({"name": "chrome"}, None)

    fake_launch.assert_called_once_with(Path("C:/x/chrome.lnk"))
    assert "chrome" in result.lower()


def test_open_target_not_found(monkeypatch):
    monkeypatch.setattr(tools.app_index, "resolve_start_app", lambda name: None)
    monkeypatch.setattr(tools.app_index, "try_direct_launch", lambda name: False)
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


def test_shutdown_pc_delegates(monkeypatch):
    fake_shutdown = MagicMock(return_value="shutting down in 30 seconds, sir")
    monkeypatch.setattr(tools.system_control, "shutdown_pc", fake_shutdown)

    result = tools.TOOL_DISPATCH["shutdown_pc"]({}, None)

    fake_shutdown.assert_called_once_with({}, None)
    assert result == "shutting down in 30 seconds, sir"


def test_restart_pc_delegates(monkeypatch):
    fake_restart = MagicMock(return_value="restarting in 30 seconds, sir")
    monkeypatch.setattr(tools.system_control, "restart_pc", fake_restart)

    result = tools.TOOL_DISPATCH["restart_pc"]({}, None)

    fake_restart.assert_called_once_with({}, None)
    assert result == "restarting in 30 seconds, sir"


def test_cancel_shutdown_delegates(monkeypatch):
    fake_cancel = MagicMock(return_value="cancelled, sir")
    monkeypatch.setattr(tools.system_control, "cancel_shutdown", fake_cancel)

    result = tools.TOOL_DISPATCH["cancel_shutdown"]({}, None)

    fake_cancel.assert_called_once_with({}, None)
    assert result == "cancelled, sir"


def test_open_target_prefers_the_windows_app_list(monkeypatch):
    """The regression this exists for: "open the calculator" reported that it
    could not be located, because Calculator is a Store app with no .lnk and the
    shortcut index was the only thing consulted."""
    monkeypatch.setattr(tools.app_index, "resolve_start_app", lambda n: "Calc!App")
    launched = []
    monkeypatch.setattr(tools.app_index, "launch_start_app", lambda i: launched.append(i))
    monkeypatch.setattr(tools.app_index, "resolve", lambda n, i: None)

    assert "calculator" in tools.TOOL_DISPATCH["open_target"]({"name": "calculator"}, None)
    assert launched == ["Calc!App"]


def test_open_target_falls_back_to_shortcuts_then_direct_launch(monkeypatch):
    """try_direct_launch has to be last: os.startfile succeeds for some bare
    names without starting anything, so trying it first reported success for a
    window that never appeared."""
    order = []
    monkeypatch.setattr(tools.app_index, "resolve_start_app", lambda n: order.append("apps"))
    monkeypatch.setattr(tools.app_index, "resolve", lambda n, i: order.append("shortcuts"))
    monkeypatch.setattr(tools.app_index, "try_direct_launch",
                        lambda n: order.append("direct") or True)

    tools.TOOL_DISPATCH["open_target"]({"name": "regedit"}, None)

    assert order == ["apps", "shortcuts", "direct"]


def test_open_target_reports_honestly_when_nothing_matches(monkeypatch):
    monkeypatch.setattr(tools.app_index, "resolve_start_app", lambda n: None)
    monkeypatch.setattr(tools.app_index, "resolve", lambda n, i: None)
    monkeypatch.setattr(tools.app_index, "try_direct_launch", lambda n: False)

    reply = tools.TOOL_DISPATCH["open_target"]({"name": "nonexistent app"}, None)
    assert "could not find" in reply


def test_remember_fact_stores_what_the_model_was_told(monkeypatch):
    recorded = []
    monkeypatch.setattr(tools.memory, "remember",
                        lambda kind, key, value, status="": recorded.append((kind, key, value, status)))

    reply = tools.TOOL_DISPATCH["remember_fact"](
        {"kind": "preference", "key": "browser", "value": "Firefox"}, None)

    assert recorded == [("preference", "browser", "Firefox", "")]
    assert reply == "noted, sir"


def test_forget_fact_says_so_when_there_was_nothing_to_forget(monkeypatch):
    """Otherwise TRON claims to have forgotten something it never knew, and the
    user believes a fact was removed when it was not."""
    monkeypatch.setattr(tools.memory, "forget", lambda key, kind="": False)
    assert "don't have anything" in tools.TOOL_DISPATCH["forget_fact"]({"key": "nope"}, None)

    monkeypatch.setattr(tools.memory, "forget", lambda key, kind="": True)
    assert tools.TOOL_DISPATCH["forget_fact"]({"key": "browser"}, None) == "forgotten, sir"


def test_recalling_activity_does_not_leak_the_user_dossier(monkeypatch):
    """"What have you been up to?" asks about TRON's ACTIONS. Long-term facts
    are about the user, and are kept in a separate block for exactly this
    reason — this test fails if the two are ever merged."""
    monkeypatch.setattr(tools.memory, "recent_context", lambda: "- opened notepad")
    monkeypatch.setattr(tools.memory, "long_term_context",
                        lambda: "Who the user is:\n- name: Shivansh")

    reply = tools.TOOL_DISPATCH["recall_activity"]({}, None)

    assert "notepad" in reply
    assert "Shivansh" not in reply
