# tests/test_wake_trigger.py
from unittest.mock import MagicMock

import numpy as np
import pytest

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


def test_openwakeword_trigger_raises_if_model_missing(tmp_path):
    missing = tmp_path / "does_not_exist.onnx"

    with pytest.raises(FileNotFoundError):
        wake_trigger.OpenWakeWordTrigger(str(missing), on_trigger=MagicMock())


def test_openwakeword_trigger_loads_model(tmp_path, monkeypatch):
    model_path = tmp_path / "hey_tron.onnx"
    model_path.write_bytes(b"fake-onnx-bytes")

    fake_model = MagicMock()
    fake_model_class = MagicMock(return_value=fake_model)
    monkeypatch.setattr(wake_trigger.openwakeword, "Model", fake_model_class)

    trigger = wake_trigger.OpenWakeWordTrigger(str(model_path), on_trigger=MagicMock())

    fake_model_class.assert_called_once_with(
        wakeword_models=[str(model_path)], inference_framework="onnx"
    )
    assert trigger._model_key == "hey_tron"


def test_openwakeword_trigger_start_stop_lifecycle(tmp_path, monkeypatch):
    model_path = tmp_path / "hey_tron.onnx"
    model_path.write_bytes(b"fake")
    monkeypatch.setattr(wake_trigger.openwakeword, "Model", MagicMock(return_value=MagicMock()))

    fake_stream = MagicMock()
    monkeypatch.setattr(wake_trigger.sd, "InputStream", MagicMock(return_value=fake_stream))

    trigger = wake_trigger.OpenWakeWordTrigger(str(model_path), on_trigger=MagicMock())
    trigger.start()
    fake_stream.start.assert_called_once()

    trigger.stop()
    fake_stream.stop.assert_called_once()
    fake_stream.close.assert_called_once()


def test_openwakeword_trigger_below_threshold_does_not_fire(tmp_path, monkeypatch):
    model_path = tmp_path / "hey_tron.onnx"
    model_path.write_bytes(b"fake")
    fake_model = MagicMock()
    fake_model.predict.return_value = {"hey_tron": 0.1}
    monkeypatch.setattr(wake_trigger.openwakeword, "Model", MagicMock(return_value=fake_model))
    fake_thread = MagicMock()
    monkeypatch.setattr(wake_trigger.threading, "Thread", fake_thread)

    trigger = wake_trigger.OpenWakeWordTrigger(str(model_path), on_trigger=MagicMock(), threshold=0.5)

    chunk = np.zeros(1280, dtype=np.int16).tobytes()
    trigger._on_block(chunk, 1280, None, None)

    fake_thread.assert_not_called()


def test_openwakeword_trigger_above_threshold_fires_on_a_thread(tmp_path, monkeypatch):
    model_path = tmp_path / "hey_tron.onnx"
    model_path.write_bytes(b"fake")
    fake_model = MagicMock()
    fake_model.predict.return_value = {"hey_tron": 0.9}
    monkeypatch.setattr(wake_trigger.openwakeword, "Model", MagicMock(return_value=fake_model))

    started = {}

    def fake_thread_factory(target, daemon):
        started["target"] = target
        started["daemon"] = daemon
        return MagicMock(start=lambda: target())

    monkeypatch.setattr(wake_trigger.threading, "Thread", fake_thread_factory)

    on_trigger = MagicMock()
    trigger = wake_trigger.OpenWakeWordTrigger(str(model_path), on_trigger=on_trigger, threshold=0.5)

    chunk = np.zeros(1280, dtype=np.int16).tobytes()
    trigger._on_block(chunk, 1280, None, None)

    on_trigger.assert_called_once()
    assert started["daemon"] is True
    assert trigger._listening is True  # resumed after on_trigger returns (fake thread ran synchronously)


def test_openwakeword_trigger_ignores_blocks_while_paused(tmp_path, monkeypatch):
    model_path = tmp_path / "hey_tron.onnx"
    model_path.write_bytes(b"fake")
    fake_model = MagicMock()
    monkeypatch.setattr(wake_trigger.openwakeword, "Model", MagicMock(return_value=fake_model))

    trigger = wake_trigger.OpenWakeWordTrigger(str(model_path), on_trigger=MagicMock())
    trigger.pause()

    chunk = np.zeros(1280, dtype=np.int16).tobytes()
    trigger._on_block(chunk, 1280, None, None)

    fake_model.predict.assert_not_called()


def test_openwakeword_trigger_resume_reenables_listening(tmp_path, monkeypatch):
    model_path = tmp_path / "hey_tron.onnx"
    model_path.write_bytes(b"fake")
    monkeypatch.setattr(wake_trigger.openwakeword, "Model", MagicMock(return_value=MagicMock()))

    trigger = wake_trigger.OpenWakeWordTrigger(str(model_path), on_trigger=MagicMock())
    trigger.pause()
    trigger.resume()

    assert trigger._listening is True
