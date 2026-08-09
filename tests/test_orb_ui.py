# tests/test_orb_ui.py
from unittest.mock import MagicMock

import pytest

import orb_ui


@pytest.fixture(autouse=True)
def fixed_screen_size(monkeypatch):
    """Every OrbUI() construction now calls GetSystemMetrics for centering —
    pin it to a fixed size so geometry assertions are deterministic."""
    fake_user32 = MagicMock()
    fake_user32.GetSystemMetrics.side_effect = lambda index: 1920 if index == 0 else 1080
    monkeypatch.setattr(orb_ui.ctypes.windll, "user32", fake_user32)


def test_window_created_hidden(monkeypatch):
    fake_window = MagicMock()
    fake_create_window = MagicMock(return_value=fake_window)
    monkeypatch.setattr(orb_ui.webview, "create_window", fake_create_window)

    orb_ui.OrbUI()

    _, kwargs = fake_create_window.call_args
    assert kwargs["hidden"] is True


def test_creates_window_with_expected_geometry(monkeypatch):
    fake_window = MagicMock()
    fake_create_window = MagicMock(return_value=fake_window)
    monkeypatch.setattr(orb_ui.webview, "create_window", fake_create_window)

    orb_ui.OrbUI()

    _, kwargs = fake_create_window.call_args
    assert kwargs["width"] == 400
    assert kwargs["height"] == 400
    assert kwargs["frameless"] is True
    assert kwargs["transparent"] is True
    assert kwargs["on_top"] is False  # not pinned-on-top; pinned to the desktop layer instead


def test_creates_window_centered_on_the_primary_monitor(monkeypatch):
    fake_create_window = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(orb_ui.webview, "create_window", fake_create_window)

    orb_ui.OrbUI()

    _, kwargs = fake_create_window.call_args
    assert kwargs["x"] == (1920 - 400) // 2
    assert kwargs["y"] == (1080 - 400) // 2


def test_on_state_change_pushes_js(monkeypatch):
    fake_window = MagicMock()
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))

    ui = orb_ui.OrbUI()

    class FakeState:
        name = "LISTENING"

    ui.on_state_change(FakeState())

    fake_window.evaluate_js.assert_called_once_with("setState('listening')")


def test_on_state_change_swallows_errors_before_window_ready(monkeypatch):
    fake_window = MagicMock()
    fake_window.evaluate_js.side_effect = Exception("not ready")
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))

    ui = orb_ui.OrbUI()

    class FakeState:
        name = "IDLE"

    ui.on_state_change(FakeState())  # must not raise


def test_non_idle_state_pops_the_orb_up(monkeypatch):
    fake_window = MagicMock()
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))

    ui = orb_ui.OrbUI()  # starts hidden (_visible = False)

    class FakeState:
        name = "LISTENING"

    ui.on_state_change(FakeState())

    fake_window.show.assert_called_once()
    fake_window.hide.assert_not_called()


def test_idle_state_hides_the_orb_again(monkeypatch):
    fake_window = MagicMock()
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))

    ui = orb_ui.OrbUI()

    class Listening:
        name = "LISTENING"

    class Idle:
        name = "IDLE"

    ui.on_state_change(Listening())  # pops up
    ui.on_state_change(Idle())       # back down

    fake_window.show.assert_called_once()
    fake_window.hide.assert_called_once()


def test_repeated_non_idle_states_only_show_once(monkeypatch):
    """Avoids redundant show() calls flickering the window across LISTENING -> THINKING -> SPEAKING."""
    fake_window = MagicMock()
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))

    ui = orb_ui.OrbUI()

    for name in ("LISTENING", "THINKING", "SPEAKING", "ACTING"):
        state = type("S", (), {"name": name})
        ui.on_state_change(state())

    assert fake_window.show.call_count == 1


def test_toggle_visibility_is_a_manual_override(monkeypatch):
    fake_window = MagicMock()
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))

    ui = orb_ui.OrbUI()  # hidden by default

    ui.toggle_visibility()
    fake_window.show.assert_called_once()

    ui.toggle_visibility()
    fake_window.hide.assert_called_once()


def test_on_audio_level_pushes_js(monkeypatch):
    fake_window = MagicMock()
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))

    ui = orb_ui.OrbUI()
    ui.on_audio_level(0.42)

    fake_window.evaluate_js.assert_called_once_with("setAudioLevel(0.42)")


def test_on_audio_level_swallows_errors_before_window_ready(monkeypatch):
    fake_window = MagicMock()
    fake_window.evaluate_js.side_effect = Exception("not ready")
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))

    ui = orb_ui.OrbUI()
    ui.on_audio_level(0.9)  # must not raise


def test_quit_destroys_the_window(monkeypatch):
    fake_window = MagicMock()
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))

    ui = orb_ui.OrbUI()
    ui.quit()

    fake_window.destroy.assert_called_once()


def test_run_starts_webview_on_the_calling_thread_with_on_ready(monkeypatch):
    fake_window = MagicMock()
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))
    fake_start = MagicMock()
    monkeypatch.setattr(orb_ui.webview, "start", fake_start)
    monkeypatch.setattr(orb_ui.OrbUI, "_pin_to_desktop_when_ready", lambda self: None)

    ui = orb_ui.OrbUI()
    on_ready = MagicMock()
    ui.run(on_ready)

    fake_start.assert_called_once_with(func=on_ready)


def test_run_spawns_a_daemon_thread_for_desktop_pinning(monkeypatch):
    fake_window = MagicMock()
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))
    monkeypatch.setattr(orb_ui.webview, "start", MagicMock())

    captured = {}

    class FakeThread:
        def __init__(self, target, daemon):
            captured["target"] = target
            captured["daemon"] = daemon

        def start(self):
            captured["started"] = True

    monkeypatch.setattr(orb_ui.threading, "Thread", FakeThread)

    ui = orb_ui.OrbUI()
    ui.run(MagicMock())

    assert captured["target"] == ui._pin_to_desktop_when_ready
    assert captured["daemon"] is True
    assert captured["started"] is True


def test_pin_to_desktop_when_ready_gives_up_if_never_shown(monkeypatch):
    fake_window = MagicMock()
    fake_window.events.shown.wait.return_value = False
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))
    fake_pin = MagicMock()
    monkeypatch.setattr(orb_ui.desktop_layer, "pin_to_desktop", fake_pin)

    ui = orb_ui.OrbUI()
    ui._pin_to_desktop_when_ready()

    fake_pin.assert_not_called()


def test_pin_to_desktop_when_ready_pins_using_the_native_handle(monkeypatch):
    fake_window = MagicMock()
    fake_window.events.shown.wait.return_value = True
    fake_window.native.Handle.ToInt64.return_value = 999888
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))
    fake_pin = MagicMock()
    monkeypatch.setattr(orb_ui.desktop_layer, "pin_to_desktop", fake_pin)

    ui = orb_ui.OrbUI()
    ui._pin_to_desktop_when_ready()

    fake_pin.assert_called_once_with(999888)


def test_pin_to_desktop_when_ready_swallows_errors_reading_the_handle(monkeypatch):
    fake_window = MagicMock()
    fake_window.events.shown.wait.return_value = True
    fake_window.native = None  # .Handle access would raise AttributeError
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))
    fake_pin = MagicMock()
    monkeypatch.setattr(orb_ui.desktop_layer, "pin_to_desktop", fake_pin)

    ui = orb_ui.OrbUI()
    ui._pin_to_desktop_when_ready()  # must not raise

    fake_pin.assert_not_called()
