# tests/test_orb_ui.py
from unittest.mock import MagicMock

import orb_ui


def test_window_created_hidden(monkeypatch):
    fake_window = MagicMock()
    fake_create_window = MagicMock(return_value=fake_window)
    monkeypatch.setattr(orb_ui.webview, "create_window", fake_create_window)
    monkeypatch.setattr(orb_ui.webview, "start", MagicMock())

    orb_ui.OrbUI()

    _, kwargs = fake_create_window.call_args
    assert kwargs["hidden"] is True


def test_creates_window_with_expected_geometry(monkeypatch):
    fake_window = MagicMock()
    fake_create_window = MagicMock(return_value=fake_window)
    monkeypatch.setattr(orb_ui.webview, "create_window", fake_create_window)
    monkeypatch.setattr(orb_ui.webview, "start", MagicMock())

    orb_ui.OrbUI()

    _, kwargs = fake_create_window.call_args
    assert kwargs["width"] == 400
    assert kwargs["height"] == 400
    assert kwargs["frameless"] is True
    assert kwargs["transparent"] is True
    assert kwargs["on_top"] is True


def test_on_state_change_pushes_js(monkeypatch):
    fake_window = MagicMock()
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))
    monkeypatch.setattr(orb_ui.webview, "start", MagicMock())

    ui = orb_ui.OrbUI()

    class FakeState:
        name = "LISTENING"

    ui.on_state_change(FakeState())

    fake_window.evaluate_js.assert_called_once_with("setState('listening')")


def test_on_state_change_swallows_errors_before_window_ready(monkeypatch):
    fake_window = MagicMock()
    fake_window.evaluate_js.side_effect = Exception("not ready")
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))
    monkeypatch.setattr(orb_ui.webview, "start", MagicMock())

    ui = orb_ui.OrbUI()

    class FakeState:
        name = "IDLE"

    ui.on_state_change(FakeState())  # must not raise


def test_non_idle_state_pops_the_orb_up(monkeypatch):
    fake_window = MagicMock()
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))
    monkeypatch.setattr(orb_ui.webview, "start", MagicMock())

    ui = orb_ui.OrbUI()  # starts hidden (_visible = False)

    class FakeState:
        name = "LISTENING"

    ui.on_state_change(FakeState())

    fake_window.show.assert_called_once()
    fake_window.hide.assert_not_called()


def test_idle_state_hides_the_orb_again(monkeypatch):
    fake_window = MagicMock()
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))
    monkeypatch.setattr(orb_ui.webview, "start", MagicMock())

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
    monkeypatch.setattr(orb_ui.webview, "start", MagicMock())

    ui = orb_ui.OrbUI()

    for name in ("LISTENING", "THINKING", "SPEAKING", "ACTING"):
        state = type("S", (), {"name": name})
        ui.on_state_change(state())

    assert fake_window.show.call_count == 1


def test_toggle_visibility_is_a_manual_override(monkeypatch):
    fake_window = MagicMock()
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))
    monkeypatch.setattr(orb_ui.webview, "start", MagicMock())

    ui = orb_ui.OrbUI()  # hidden by default

    ui.toggle_visibility()
    fake_window.show.assert_called_once()

    ui.toggle_visibility()
    fake_window.hide.assert_called_once()


def test_on_audio_level_pushes_js(monkeypatch):
    fake_window = MagicMock()
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))
    monkeypatch.setattr(orb_ui.webview, "start", MagicMock())

    ui = orb_ui.OrbUI()
    ui.on_audio_level(0.42)

    fake_window.evaluate_js.assert_called_once_with("setAudioLevel(0.42)")


def test_on_audio_level_swallows_errors_before_window_ready(monkeypatch):
    fake_window = MagicMock()
    fake_window.evaluate_js.side_effect = Exception("not ready")
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))
    monkeypatch.setattr(orb_ui.webview, "start", MagicMock())

    ui = orb_ui.OrbUI()
    ui.on_audio_level(0.9)  # must not raise


def test_start_launches_background_thread(monkeypatch):
    fake_window = MagicMock()
    fake_start = MagicMock()
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))
    monkeypatch.setattr(orb_ui.webview, "start", fake_start)

    ui = orb_ui.OrbUI()
    ui.start()

    assert ui._thread.daemon is True
