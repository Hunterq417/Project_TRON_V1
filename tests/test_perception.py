# tests/test_perception.py
from unittest.mock import MagicMock

import numpy as np
import pytest
from PIL import Image

import perception


def test_capture_screen_jpeg_returns_jpeg_bytes(monkeypatch):
    fake_image = Image.new("RGB", (20, 20), color=(10, 20, 30))
    monkeypatch.setattr(perception.ImageGrab, "grab", lambda: fake_image)

    data = perception.capture_screen_jpeg()

    assert data[:2] == b"\xff\xd8"  # JPEG magic bytes


def test_capture_camera_jpeg_returns_jpeg_bytes(monkeypatch):
    fake_frame = np.zeros((10, 10, 3), dtype=np.uint8)
    fake_cap = MagicMock()
    fake_cap.isOpened.return_value = True
    fake_cap.read.return_value = (True, fake_frame)
    monkeypatch.setattr(perception.cv2, "VideoCapture", MagicMock(return_value=fake_cap))

    data = perception.capture_camera_jpeg()

    assert data[:2] == b"\xff\xd8"
    fake_cap.release.assert_called_once()


def test_capture_camera_jpeg_raises_when_camera_unavailable(monkeypatch):
    fake_cap = MagicMock()
    fake_cap.isOpened.return_value = False
    monkeypatch.setattr(perception.cv2, "VideoCapture", MagicMock(return_value=fake_cap))

    with pytest.raises(RuntimeError):
        perception.capture_camera_jpeg()
    fake_cap.release.assert_called_once()


def test_capture_camera_jpeg_raises_when_read_fails(monkeypatch):
    fake_cap = MagicMock()
    fake_cap.isOpened.return_value = True
    fake_cap.read.return_value = (False, None)
    monkeypatch.setattr(perception.cv2, "VideoCapture", MagicMock(return_value=fake_cap))

    with pytest.raises(RuntimeError):
        perception.capture_camera_jpeg()
