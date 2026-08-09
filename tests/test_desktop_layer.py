# tests/test_desktop_layer.py
from unittest.mock import MagicMock

import desktop_layer


def test_find_worker_w_returns_none_if_progman_missing(monkeypatch):
    fake_user32 = MagicMock()
    fake_user32.FindWindowW.return_value = 0
    monkeypatch.setattr(desktop_layer, "user32", fake_user32)

    assert desktop_layer._find_worker_w() is None
    fake_user32.SendMessageTimeoutW.assert_not_called()


def test_find_worker_w_locates_the_sibling_workerw(monkeypatch):
    fake_user32 = MagicMock()
    fake_user32.FindWindowW.return_value = 111  # Progman found

    def fake_find_window_ex_w(parent, child_after, class_name, window_name):
        if parent == 999 and class_name == "SHELLDLL_DefView":
            return 1  # window 999 hosts the desktop icons
        if parent is None and child_after == 999 and class_name == "WorkerW":
            return 777  # the blank WorkerW right after it in z-order
        return 0

    fake_user32.FindWindowExW.side_effect = fake_find_window_ex_w

    def fake_enum_windows(callback, lparam):
        callback(500, 0)  # an unrelated top-level window
        callback(999, 0)  # the one hosting the icons
        return True

    fake_user32.EnumWindows.side_effect = fake_enum_windows

    monkeypatch.setattr(desktop_layer, "user32", fake_user32)

    result = desktop_layer._find_worker_w()

    assert result == 777
    fake_user32.SendMessageTimeoutW.assert_called_once()


def test_find_worker_w_falls_back_when_shelldll_defview_is_under_progman(monkeypatch):
    """Some Windows builds never relocate SHELLDLL_DefView out of Progman, so the
    classic sibling lookup finds nothing — fall back to the WorkerW right after
    Progman itself, if one exists."""
    fake_user32 = MagicMock()
    fake_user32.FindWindowW.return_value = 111  # Progman found

    def fake_find_window_ex_w(parent, child_after, class_name, window_name):
        if parent == 111 and class_name == "SHELLDLL_DefView":
            return 1  # SHELLDLL_DefView is a direct child of Progman
        if parent is None and child_after == 111 and class_name == "WorkerW":
            return 888  # fallback target
        return 0

    fake_user32.FindWindowExW.side_effect = fake_find_window_ex_w
    fake_user32.EnumWindows.side_effect = lambda callback, lparam: True  # nothing else enumerated

    monkeypatch.setattr(desktop_layer, "user32", fake_user32)

    assert desktop_layer._find_worker_w() == 888


def test_find_worker_w_returns_none_when_no_strategy_finds_a_target(monkeypatch):
    fake_user32 = MagicMock()
    fake_user32.FindWindowW.return_value = 111
    fake_user32.FindWindowExW.return_value = 0
    fake_user32.EnumWindows.side_effect = lambda callback, lparam: True

    monkeypatch.setattr(desktop_layer, "user32", fake_user32)

    assert desktop_layer._find_worker_w() is None


def test_pin_to_desktop_calls_set_parent_when_worker_w_found(monkeypatch):
    monkeypatch.setattr(desktop_layer, "_find_worker_w", lambda: 777)
    fake_user32 = MagicMock()
    fake_user32.SetParent.return_value = 1
    monkeypatch.setattr(desktop_layer, "user32", fake_user32)

    result = desktop_layer.pin_to_desktop(12345)

    assert result is True
    args, kwargs = fake_user32.SetParent.call_args
    assert args[0].value == 12345
    assert args[1] == 777


def test_pin_to_desktop_returns_false_when_worker_w_not_found(monkeypatch):
    monkeypatch.setattr(desktop_layer, "_find_worker_w", lambda: None)
    fake_user32 = MagicMock()
    monkeypatch.setattr(desktop_layer, "user32", fake_user32)

    result = desktop_layer.pin_to_desktop(12345)

    assert result is False
    fake_user32.SetParent.assert_not_called()


def test_pin_to_desktop_returns_false_when_set_parent_fails(monkeypatch):
    monkeypatch.setattr(desktop_layer, "_find_worker_w", lambda: 777)
    fake_user32 = MagicMock()
    fake_user32.SetParent.return_value = 0
    monkeypatch.setattr(desktop_layer, "user32", fake_user32)

    result = desktop_layer.pin_to_desktop(12345)

    assert result is False
