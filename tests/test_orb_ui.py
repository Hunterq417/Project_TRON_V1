# tests/test_orb_ui.py
from unittest.mock import MagicMock

import pytest

import orb_ui
import state_manager as sm


@pytest.fixture
def ui(monkeypatch):
    """An OrbUI with the window and the renderer stubbed out.

    Neither is exercised here: creating a real tkinter window needs a desktop
    session, and the renderer has its own tests. What matters at this level is
    the state machine driving visibility, easing and the audio pulse.
    """
    monkeypatch.setattr(orb_ui.tk, "Tk", MagicMock())
    monkeypatch.setattr(orb_ui.orb_render, "OrbRenderer", MagicMock())
    monkeypatch.setattr(orb_ui.user32, "GetSystemMetrics", lambda i: (2560, 1600)[i])
    monkeypatch.setattr(orb_ui.user32, "GetAncestor", lambda h, f: 4242)
    monkeypatch.setattr(orb_ui.user32, "GetWindowLongW", lambda h, i: 0)
    monkeypatch.setattr(orb_ui.user32, "SetWindowLongW", lambda h, i, v: 0)
    monkeypatch.setattr(orb_ui.user32, "SetProcessDPIAware", lambda: 1)
    return orb_ui.OrbUI()


def test_starts_visible(ui):
    # The orb is a permanent desktop ornament, not something that only shows up
    # for the length of a conversation.
    assert ui._visible is True
    assert ui._state == "idle"


def test_state_changes_never_touch_visibility(ui):
    for state in sm.State:
        ui.on_state_change(state)
        assert ui._visible is True
    assert ui._state == list(sm.State)[-1].name.lower()   # the last state applied wins


def test_hiding_from_the_tray_survives_a_conversation(ui):
    ui.toggle_visibility()                      # user hides it
    assert ui._visible is False
    ui.on_state_change(sm.State.LISTENING)      # a conversation starts and ends
    ui.on_state_change(sm.State.SPEAKING)
    ui.on_state_change(sm.State.IDLE)
    assert ui._visible is False                 # still hidden — it must stay away


def test_every_state_is_known_to_the_orb(ui):
    # A state the renderer has no entry for would raise in the tick loop.
    for state in sm.State:
        assert state.name.lower() in orb_ui._STATES


def test_audio_level_is_clamped(ui):
    ui.on_audio_level(5.0)
    assert ui._audio_level == 1.0
    ui.on_audio_level(-2.0)
    assert ui._audio_level == 0.0


def test_toggle_visibility_flips_it(ui):
    assert ui._visible is True          # up by default
    ui.toggle_visibility()
    assert ui._visible is False
    ui.toggle_visibility()
    assert ui._visible is True


def test_quit_only_sets_a_flag(ui):
    # quit() is called from the tray's thread and tkinter is not thread-safe, so
    # it must not touch the window itself — the tick loop tears down on the GUI
    # thread instead.
    ui.quit()
    assert ui._quitting is True
    ui._root.destroy.assert_not_called()


def test_the_default_model_is_the_floating_widget(ui):
    # The compact ring floats over your work and can be dragged; the orb is
    # desktop furniture that sits behind everything and is not interactive.
    assert ui.model == "halo-ring"
    assert ui._topmost is True and ui._draggable is True


def test_the_orb_model_hugs_the_sphere_and_stays_behind(monkeypatch):
    from unittest.mock import MagicMock
    monkeypatch.setattr(orb_ui.tk, "Tk", MagicMock())
    monkeypatch.setattr(orb_ui.orb_render, "OrbRenderer", MagicMock())
    monkeypatch.setattr(orb_ui.user32, "GetSystemMetrics", lambda i: (2560, 1600)[i])
    monkeypatch.setattr(orb_ui.user32, "GetAncestor", lambda h, f: 4242)
    monkeypatch.setattr(orb_ui.user32, "GetWindowLongW", lambda h, i: 0)
    monkeypatch.setattr(orb_ui.user32, "SetWindowLongW", lambda h, i, v: 0)
    monkeypatch.setattr(orb_ui.user32, "SetProcessDPIAware", lambda: 1)
    monkeypatch.setattr(orb_ui.OrbUI, "_config_data", staticmethod(lambda: {"ui_model": "aurora-orb"}))
    ui = orb_ui.OrbUI()
    assert ui._size == int(1600 * orb_ui._RADIUS_FRACTION) * 2 + 8
    assert ui._topmost is False and ui._draggable is False


def test_idle_carries_no_state_colour():
    # At rest the orb must be the untouched replica of the reference.
    assert orb_ui._STATES["idle"]["amt"] == 0.0
    assert all(s["amt"] > 0.0 for name, s in orb_ui._STATES.items() if name != "idle")


def test_dust_orb_assets_are_present_and_states_map():
    import dust_orb
    page = (dust_orb.asset_dir() / "tron.html").read_text(encoding="utf-8")
    for f in ("dust-orb.js", "material.js", "vendor/three-r180.js", "vendor/motion.js", "LICENSE", "vendor/THREE-LICENSE.txt"):
        assert (dust_orb.asset_dir() / f).exists(), f
    for state in ("idle", "listening", "thinking", "speaking", "error"):
        assert state in page
