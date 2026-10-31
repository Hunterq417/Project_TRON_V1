# tests/test_tray_ui.py
from unittest.mock import MagicMock

import config
import tray_ui
import state_manager as sm


def test_on_state_change_updates_icon_and_title(monkeypatch):
    fake_icon = MagicMock()
    fake_icon_class = MagicMock(return_value=fake_icon)
    monkeypatch.setattr(tray_ui.pystray, "Icon", fake_icon_class)
    monkeypatch.setattr(tray_ui.pystray, "Menu", MagicMock())
    monkeypatch.setattr(tray_ui.pystray, "MenuItem", MagicMock())

    ui = tray_ui.TrayUI(quit_callback=MagicMock())
    ui.on_state_change(sm.State.LISTENING)

    # Derived, not hard-coded, so bumping APP_VERSION doesn't fail the suite.
    assert fake_icon.title == f"{config.APP_LABEL}: listening"
    assert fake_icon.icon is not None


def test_each_state_gets_a_distinct_color(monkeypatch):
    fake_icon = MagicMock()
    monkeypatch.setattr(tray_ui.pystray, "Icon", MagicMock(return_value=fake_icon))
    monkeypatch.setattr(tray_ui.pystray, "Menu", MagicMock())
    monkeypatch.setattr(tray_ui.pystray, "MenuItem", MagicMock())

    ui = tray_ui.TrayUI(quit_callback=MagicMock())

    seen_colors = set()
    for state in sm.State:
        ui.on_state_change(state)
        seen_colors.add(tray_ui._COLORS[state.name.lower()])

    assert len(seen_colors) == len(list(sm.State))  # every state maps to its own color


def test_start_launches_background_thread(monkeypatch):
    fake_icon = MagicMock()
    monkeypatch.setattr(tray_ui.pystray, "Icon", MagicMock(return_value=fake_icon))
    monkeypatch.setattr(tray_ui.pystray, "Menu", MagicMock())
    monkeypatch.setattr(tray_ui.pystray, "MenuItem", MagicMock())

    ui = tray_ui.TrayUI(quit_callback=MagicMock())
    ui.start()

    assert ui._thread.daemon is True
    assert ui._thread.is_alive() or fake_icon.run.called


def test_menu_includes_orb_toggle_when_callback_provided(monkeypatch):
    fake_menu_item = MagicMock(side_effect=lambda *a, **k: MagicMock())
    monkeypatch.setattr(tray_ui.pystray, "Icon", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(tray_ui.pystray, "Menu", MagicMock())
    monkeypatch.setattr(tray_ui.pystray, "MenuItem", fake_menu_item)

    tray_ui.TrayUI(quit_callback=MagicMock(), toggle_orb_callback=MagicMock())

    labels = [call.args[0] for call in fake_menu_item.call_args_list]
    assert "Show/Hide Orb" in labels
    assert "Quit" in labels


def test_menu_omits_orb_toggle_when_callback_not_provided(monkeypatch):
    fake_menu_item = MagicMock(side_effect=lambda *a, **k: MagicMock())
    monkeypatch.setattr(tray_ui.pystray, "Icon", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(tray_ui.pystray, "Menu", MagicMock())
    monkeypatch.setattr(tray_ui.pystray, "MenuItem", fake_menu_item)

    tray_ui.TrayUI(quit_callback=MagicMock())

    labels = [call.args[0] for call in fake_menu_item.call_args_list]
    assert "Show/Hide Orb" not in labels
    assert "Quit" in labels
