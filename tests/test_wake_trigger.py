# tests/test_wake_trigger.py
from unittest.mock import MagicMock

import wake_trigger


def test_start_registers_hotkey_and_stop_removes_it(monkeypatch):
    fake_keyboard = MagicMock()
    fake_keyboard.add_hotkey.return_value = "handle-123"
    monkeypatch.setattr(wake_trigger, "keyboard", fake_keyboard)

    on_trigger = MagicMock()
    trigger = wake_trigger.HotkeyTrigger("ctrl+alt+t", on_trigger)

    trigger.start()
    fake_keyboard.add_hotkey.assert_called_once_with("ctrl+alt+t", on_trigger)

    trigger.stop()
    fake_keyboard.remove_hotkey.assert_called_once_with("handle-123")


def test_stop_before_start_is_a_no_op(monkeypatch):
    fake_keyboard = MagicMock()
    monkeypatch.setattr(wake_trigger, "keyboard", fake_keyboard)

    trigger = wake_trigger.HotkeyTrigger("ctrl+alt+t", MagicMock())
    trigger.stop()

    fake_keyboard.remove_hotkey.assert_not_called()
