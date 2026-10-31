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


def test_find_worker_w_falls_back_to_progman_when_no_workerw_exists(monkeypatch):
    """Windows 11 24H2: the spawn message is ignored, SHELLDLL_DefView stays on
    Progman, and every WorkerW is an invisible orphan — so both earlier
    strategies come back empty and pinning used to silently do nothing. Progman
    is itself the desktop window, so it is a valid host."""
    fake_user32 = MagicMock()
    fake_user32.FindWindowW.return_value = 111  # Progman found

    def fake_find_window_ex_w(parent, child_after, class_name, window_name):
        if parent == 111 and class_name == "SHELLDLL_DefView":
            return 1  # icons hang off Progman
        return 0  # and there is no WorkerW anywhere to use

    fake_user32.FindWindowExW.side_effect = fake_find_window_ex_w
    fake_user32.EnumWindows.side_effect = lambda callback, lparam: callback(111, 0)

    monkeypatch.setattr(desktop_layer, "user32", fake_user32)

    assert desktop_layer._find_worker_w() == 111


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


def _centering_user32(rect, screen=(2560, 1600), parent=0):
    """A user32 stub whose GetWindowRect reports `rect` (l, t, r, b)."""
    fake = MagicMock()

    def fake_get_window_rect(hwnd, out):
        out._obj.left, out._obj.top, out._obj.right, out._obj.bottom = rect
        return 1

    fake.GetWindowRect.side_effect = fake_get_window_rect
    fake.GetSystemMetrics.side_effect = lambda i: screen[i]
    fake.GetParent.return_value = parent
    fake.SetWindowPos.return_value = 1
    return fake


def test_center_on_primary_uses_measured_pixels_not_logical_units(monkeypatch):
    """The window manager positions in DPI-scaled units while GetSystemMetrics
    reports physical ones, so centring at creation time lands off-centre on a
    scaled display. Centring from the window's own measured rect is exact."""
    fake_user32 = _centering_user32(rect=(1300, 650, 2148, 1467))  # 848x817, off-centre
    monkeypatch.setattr(desktop_layer, "user32", fake_user32)

    assert desktop_layer.center_on_primary(12345) is True

    args, _ = fake_user32.SetWindowPos.call_args
    assert (args[2], args[3]) == ((2560 - 848) // 2, (1600 - 817) // 2)


def test_center_on_primary_converts_through_the_parent_when_pinned(monkeypatch):
    """Once pinned, the position is parent-relative — screen coordinates would
    put the orb somewhere else entirely."""
    fake_user32 = _centering_user32(rect=(0, 0, 848, 817), parent=999)

    def fake_screen_to_client(hwnd, point):
        point._obj.x -= 40  # pretend the desktop host starts 40px right/down
        point._obj.y -= 25
        return 1

    fake_user32.ScreenToClient.side_effect = fake_screen_to_client
    monkeypatch.setattr(desktop_layer, "user32", fake_user32)

    desktop_layer.center_on_primary(12345)

    args, _ = fake_user32.SetWindowPos.call_args
    assert (args[2], args[3]) == ((2560 - 848) // 2 - 40, (1600 - 817) // 2 - 25)


def test_center_on_primary_returns_false_when_the_rect_is_unreadable(monkeypatch):
    fake_user32 = MagicMock()
    fake_user32.GetWindowRect.return_value = 0
    monkeypatch.setattr(desktop_layer, "user32", fake_user32)

    assert desktop_layer.center_on_primary(12345) is False
    fake_user32.SetWindowPos.assert_not_called()
