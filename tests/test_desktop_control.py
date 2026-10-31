# tests/test_desktop_control.py
from unittest.mock import MagicMock

import desktop_control


def _fake_endpoint(monkeypatch, level=0.5, muted=False):
    endpoint = MagicMock()
    endpoint.GetMasterVolumeLevelScalar.return_value = level
    endpoint.GetMute.return_value = 1 if muted else 0
    monkeypatch.setattr(desktop_control, "_endpoint", lambda: endpoint)
    return endpoint


def test_set_volume_sets_the_scalar_level(monkeypatch):
    endpoint = _fake_endpoint(monkeypatch)
    assert desktop_control.set_volume({"level": 30}) == "volume is at 30 percent, sir"
    endpoint.SetMasterVolumeLevelScalar.assert_called_once_with(0.3, None)


def test_setting_a_level_also_unmutes(monkeypatch):
    """Setting a level on a muted device leaves it silent, which reads as the
    command having failed to whoever just asked for volume."""
    endpoint = _fake_endpoint(monkeypatch, muted=True)
    desktop_control.set_volume({"level": 40})
    endpoint.SetMute.assert_called_once_with(0, None)


def test_setting_volume_to_zero_does_not_unmute(monkeypatch):
    endpoint = _fake_endpoint(monkeypatch, muted=True)
    desktop_control.set_volume({"level": 0})
    endpoint.SetMute.assert_not_called()


def test_volume_is_clamped_to_the_valid_range(monkeypatch):
    endpoint = _fake_endpoint(monkeypatch)
    desktop_control.set_volume({"level": 500})
    endpoint.SetMasterVolumeLevelScalar.assert_called_with(1.0, None)
    desktop_control.set_volume({"level": -20})
    endpoint.SetMasterVolumeLevelScalar.assert_called_with(0.0, None)


def test_change_volume_is_relative_to_the_current_level(monkeypatch):
    endpoint = _fake_endpoint(monkeypatch, level=0.5)
    assert desktop_control.change_volume({"delta": 20}) == "volume is at 70 percent, sir"
    endpoint.SetMasterVolumeLevelScalar.assert_called_once_with(0.7, None)


def test_change_volume_clamps_at_the_top(monkeypatch):
    endpoint = _fake_endpoint(monkeypatch, level=0.95)
    assert desktop_control.change_volume({"delta": 50}) == "volume is at 100 percent, sir"


def test_non_numeric_volume_is_rejected(monkeypatch):
    endpoint = _fake_endpoint(monkeypatch)
    assert "between 0 and 100" in desktop_control.set_volume({"level": "loud"})
    endpoint.SetMasterVolumeLevelScalar.assert_not_called()


def test_audio_failure_is_reported_not_raised(monkeypatch):
    def boom():
        raise OSError("no audio endpoint")

    monkeypatch.setattr(desktop_control, "_endpoint", boom)
    assert "couldn't reach the volume" in desktop_control.set_volume({"level": 50})
    assert "couldn't read the volume" in desktop_control.volume_status()


def test_muted_status_mentions_the_level_underneath(monkeypatch):
    _fake_endpoint(monkeypatch, level=0.6, muted=True)
    reply = desktop_control.volume_status()
    assert "muted" in reply and "60 percent" in reply


def test_brightness_reports_when_the_display_does_not_support_it(monkeypatch):
    """External monitors do not expose the WMI brightness interface at all, so
    this is a normal outcome rather than a fault."""
    monkeypatch.setattr(desktop_control, "_powershell", lambda s: "UNSUPPORTED")
    assert "doesn't let me set" in desktop_control.set_brightness({"level": 50})


def test_brightness_success(monkeypatch):
    monkeypatch.setattr(desktop_control, "_powershell", lambda s: "OK")
    assert desktop_control.set_brightness({"level": 70}) == "brightness is at 70 percent, sir"


def test_brightness_status_parses_the_number(monkeypatch):
    monkeypatch.setattr(desktop_control, "_powershell", lambda s: "45")
    assert desktop_control.brightness_status() == "brightness is at 45 percent, sir"


def test_close_uses_wm_close_rather_than_killing_the_process(monkeypatch):
    """WM_CLOSE is what clicking the X does, so the app can still prompt about
    unsaved work. Terminating it would lose that work silently."""
    fake_user32 = MagicMock()
    fake_user32.GetForegroundWindow.return_value = 1234
    monkeypatch.setattr(desktop_control, "user32", fake_user32)

    assert desktop_control.window_action({"action": "close"}) == "closed it, sir"
    fake_user32.PostMessageW.assert_called_once()
    assert fake_user32.PostMessageW.call_args[0][1] == desktop_control._WM_CLOSE


def test_show_desktop_uses_the_shell_hotkey(monkeypatch):
    fake_keyboard = MagicMock()
    monkeypatch.setattr(desktop_control, "keyboard", fake_keyboard)
    assert "desktop" in desktop_control.window_action({"action": "show desktop"})
    fake_keyboard.send.assert_called_once_with("windows+d")


def test_unknown_window_action_lists_what_is_possible(monkeypatch):
    monkeypatch.setattr(desktop_control, "user32", MagicMock())
    reply = desktop_control.window_action({"action": "juggle"})
    assert "minimise" in reply and "close" in reply


def test_window_action_tolerates_underscores_and_case(monkeypatch):
    """Tool arguments arrive from a language model, which is inconsistent about
    'show desktop' vs 'show_desktop'."""
    fake_keyboard = MagicMock()
    monkeypatch.setattr(desktop_control, "keyboard", fake_keyboard)
    assert "desktop" in desktop_control.window_action({"action": "Show_Desktop"})


def _windows(monkeypatch, entries):
    monkeypatch.setattr(desktop_control, "_open_windows", lambda: entries)


def test_close_app_matches_on_process_name_not_just_title(monkeypatch):
    """The regression this exists for: asking to close File Explorer opened a
    second one, because no tool could close a NAMED app and the model fell back
    to open_target. A folder window's title is the folder, so the app name only
    appears in the process name."""
    entries = [(11, "Downloads", "explorer.exe"), (22, "Untitled - Notepad", "notepad.exe")]
    assert [h for h, _, _ in desktop_control._matches("File Explorer", entries)] == [11]


def test_longer_words_decide_the_match(monkeypatch):
    """"file explorer" must be settled by "explorer", not drag in every window
    with "file" in its title."""
    entries = [(11, "Downloads", "explorer.exe"), (22, "File List - Editor", "editor.exe")]
    assert [h for h, _, _ in desktop_control._matches("file explorer", entries)] == [11]


def test_filler_words_never_match_everything(monkeypatch):
    entries = [(11, "Some Window", "app.exe"), (22, "Another", "thing.exe")]
    assert desktop_control._matches("the window", entries) == []


def test_close_app_sends_wm_close_to_each_match(monkeypatch):
    fake_user32 = MagicMock()
    monkeypatch.setattr(desktop_control, "user32", fake_user32)
    _windows(monkeypatch, [(11, "Downloads", "explorer.exe"),
                           (12, "Documents", "explorer.exe")])
    monkeypatch.setattr(desktop_control.os, "getpid", lambda: 999)

    reply = desktop_control.close_app({"name": "explorer"})

    assert "2" in reply
    assert fake_user32.PostMessageW.call_count == 2
    assert fake_user32.PostMessageW.call_args[0][1] == desktop_control._WM_CLOSE


def test_close_app_reports_when_nothing_matches(monkeypatch):
    monkeypatch.setattr(desktop_control, "user32", MagicMock())
    _windows(monkeypatch, [(11, "Downloads", "explorer.exe")])
    assert "can't find" in desktop_control.close_app({"name": "Photoshop"})


def test_close_app_needs_a_name(monkeypatch):
    fake_user32 = MagicMock()
    monkeypatch.setattr(desktop_control, "user32", fake_user32)
    assert "which app" in desktop_control.close_app({"name": "  "})
    fake_user32.PostMessageW.assert_not_called()


def test_shell_windows_are_never_closable():
    """Folder windows and the taskbar are the same process, so "close explorer"
    would otherwise be able to take the desktop down with it."""
    assert "Progman" in desktop_control._SHELL_CLASSES
    assert "Shell_TrayWnd" in desktop_control._SHELL_CLASSES
