# tests/test_autostart.py
from unittest.mock import MagicMock

import autostart


def _fake_winreg():
    fake = MagicMock()
    fake.HKEY_CURRENT_USER = "HKCU"
    fake.KEY_SET_VALUE = "SET"
    fake.KEY_READ = "READ"
    fake.REG_SZ = "SZ"
    return fake


def test_enable_writes_command_line_to_registry(monkeypatch):
    fake_winreg = _fake_winreg()
    fake_key = MagicMock()
    fake_winreg.OpenKey.return_value = fake_key
    monkeypatch.setattr(autostart, "winreg", fake_winreg)
    monkeypatch.setattr(autostart.sys, "frozen", True, raising=False)
    monkeypatch.setattr(autostart.sys, "executable", "C:\\Apps\\TRON\\TRON.exe", raising=False)

    autostart.enable()

    fake_winreg.OpenKey.assert_called_once_with("HKCU", autostart._RUN_KEY_PATH, 0, "SET")
    fake_winreg.SetValueEx.assert_called_once_with(
        fake_key, "TRON", 0, "SZ", '"C:\\Apps\\TRON\\TRON.exe"'
    )
    fake_winreg.CloseKey.assert_called_once_with(fake_key)


def test_disable_removes_value_if_present(monkeypatch):
    fake_winreg = _fake_winreg()
    fake_key = MagicMock()
    fake_winreg.OpenKey.return_value = fake_key
    monkeypatch.setattr(autostart, "winreg", fake_winreg)

    autostart.disable()

    fake_winreg.DeleteValue.assert_called_once_with(fake_key, "TRON")
    fake_winreg.CloseKey.assert_called_once_with(fake_key)


def test_disable_is_a_no_op_if_not_present(monkeypatch):
    fake_winreg = _fake_winreg()
    fake_key = MagicMock()
    fake_winreg.OpenKey.return_value = fake_key
    fake_winreg.DeleteValue.side_effect = FileNotFoundError()
    monkeypatch.setattr(autostart, "winreg", fake_winreg)

    autostart.disable()  # must not raise

    fake_winreg.CloseKey.assert_called_once_with(fake_key)


def test_is_enabled_true_when_value_present(monkeypatch):
    fake_winreg = _fake_winreg()
    fake_key = MagicMock()
    fake_winreg.OpenKey.return_value = fake_key
    fake_winreg.QueryValueEx.return_value = ('"C:\\Apps\\TRON\\TRON.exe"', "SZ")
    monkeypatch.setattr(autostart, "winreg", fake_winreg)

    assert autostart.is_enabled() is True


def test_is_enabled_false_when_key_missing(monkeypatch):
    fake_winreg = _fake_winreg()
    fake_winreg.OpenKey.side_effect = FileNotFoundError()
    monkeypatch.setattr(autostart, "winreg", fake_winreg)

    assert autostart.is_enabled() is False


def test_is_enabled_false_when_value_missing(monkeypatch):
    fake_winreg = _fake_winreg()
    fake_key = MagicMock()
    fake_winreg.OpenKey.return_value = fake_key
    fake_winreg.QueryValueEx.side_effect = FileNotFoundError()
    monkeypatch.setattr(autostart, "winreg", fake_winreg)

    assert autostart.is_enabled() is False
