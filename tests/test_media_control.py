# tests/test_media_control.py
from unittest.mock import MagicMock

import media_control


def test_play_pause_sends_media_key(monkeypatch):
    fake_send = MagicMock()
    monkeypatch.setattr(media_control.keyboard, "send", fake_send)

    result = media_control.play_pause()

    fake_send.assert_called_once_with("play/pause media")
    assert "toggled" in result.lower()


def test_next_and_previous_send_correct_keys(monkeypatch):
    fake_send = MagicMock()
    monkeypatch.setattr(media_control.keyboard, "send", fake_send)

    media_control.next_track()
    fake_send.assert_called_with("next track")

    media_control.previous_track()
    fake_send.assert_called_with("previous track")


def test_seek_within_cap_presses_arrow_key_proportionally(monkeypatch):
    fake_send = MagicMock()
    monkeypatch.setattr(media_control.keyboard, "send", fake_send)
    monkeypatch.setattr(media_control.time, "sleep", MagicMock())

    result = media_control.seek("forward", seconds=15)

    # 15s / 5s-per-press = 3 presses of the right-arrow key
    assert fake_send.call_count == 3
    fake_send.assert_called_with("right")
    assert "forward" in result.lower()


def test_seek_backward_uses_left_arrow(monkeypatch):
    fake_send = MagicMock()
    monkeypatch.setattr(media_control.keyboard, "send", fake_send)
    monkeypatch.setattr(media_control.time, "sleep", MagicMock())

    media_control.seek("backward", seconds=5)

    fake_send.assert_called_with("left")


def test_seek_beyond_cap_explains_instead_of_spamming_keys(monkeypatch):
    fake_send = MagicMock()
    monkeypatch.setattr(media_control.keyboard, "send", fake_send)

    result = media_control.seek("forward", seconds=600)

    fake_send.assert_not_called()
    assert "60" in result or "minute" in result.lower() or "manually" in result.lower()


def test_seek_unknown_direction_returns_explanation(monkeypatch):
    fake_send = MagicMock()
    monkeypatch.setattr(media_control.keyboard, "send", fake_send)

    result = media_control.seek("sideways", seconds=10)

    fake_send.assert_not_called()
    assert "forward" in result.lower() and "backward" in result.lower()
