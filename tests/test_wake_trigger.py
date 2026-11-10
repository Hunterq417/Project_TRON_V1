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
    fake_keyboard.add_hotkey.assert_called_once_with("ctrl+alt+t", trigger._dispatch)

    # The callback must hand off to a thread, not run the conversation inline.
    trigger._dispatch()
    for t in __import__("threading").enumerate():
        if t is not __import__("threading").current_thread() and t.daemon:
            t.join(timeout=1)
    on_trigger.assert_called_once()

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


def test_openwakeword_trigger_uses_the_configured_device(tmp_path, monkeypatch):
    """Same reason as DuplexAudio: the wake word is deaf if it opens the wrong
    microphone, and it looks like a model failure rather than a device one."""
    model_path = tmp_path / "tron.onnx"
    model_path.write_bytes(b"fake")
    monkeypatch.setattr(wake_trigger.openwakeword, "Model", MagicMock())
    fake_sd = MagicMock()
    monkeypatch.setattr(wake_trigger, "sd", fake_sd)

    monkeypatch.setattr(wake_trigger.audio_io, "input_devices",
                        lambda: [(9, "HyperX Cloud II", 1)])

    trigger = wake_trigger.OpenWakeWordTrigger(
        str(model_path), on_trigger=MagicMock(), device="HyperX"
    )
    trigger.start()

    # Same resolution as DuplexAudio: the wake word and the conversation must
    # end up on the same physical microphone.
    assert fake_sd.InputStream.call_args.kwargs["device"] == 9


def test_openwakeword_trigger_defaults_to_the_system_device(tmp_path, monkeypatch):
    model_path = tmp_path / "tron.onnx"
    model_path.write_bytes(b"fake")
    monkeypatch.setattr(wake_trigger.openwakeword, "Model", MagicMock())
    fake_sd = MagicMock()
    monkeypatch.setattr(wake_trigger, "sd", fake_sd)
    monkeypatch.setattr(wake_trigger.audio_io, "windows_default_input", lambda: 6)

    trigger = wake_trigger.OpenWakeWordTrigger(str(model_path), on_trigger=MagicMock())
    trigger.start()

    assert fake_sd.InputStream.call_args.kwargs["device"] == 6     # Windows' current mic
    trigger.stop()


def test_the_wake_word_moves_to_a_new_default_mic(tmp_path, monkeypatch):
    """Earbuds connected after TRON started: "hey tron" must be heard on them."""
    model_path = tmp_path / "tron.onnx"
    model_path.write_bytes(b"fake")
    monkeypatch.setattr(wake_trigger.openwakeword, "Model", MagicMock())
    fake_sd = MagicMock()
    monkeypatch.setattr(wake_trigger, "sd", fake_sd)
    mics = iter([6, 9, 9, 9, 9])
    monkeypatch.setattr(wake_trigger.audio_io, "resolve_input", lambda d: next(mics, 9))
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None if s == 3 else None)
    trigger = wake_trigger.OpenWakeWordTrigger(str(model_path), on_trigger=MagicMock())
    trigger._open()
    assert trigger._mic == 6
    trigger._stream = fake_sd.InputStream.return_value
    calls = []
    original = trigger._open
    trigger._open = lambda: (calls.append(1), original(), setattr(trigger, "_stream", None))
    trigger._follow_windows()
    assert calls and trigger._mic == 9


def test_on_score_receives_level_and_score_for_every_block(tmp_path, monkeypatch):
    """Backs --test-mic. Without this the only way to watch the meter was to
    monkeypatch the callback, which meant the diagnostic tested a different code
    path than the one that actually runs."""
    model_path = tmp_path / "tron.onnx"
    model_path.write_bytes(b"fake")
    fake_model = MagicMock()
    fake_model.predict.return_value = {"tron": 0.42}
    monkeypatch.setattr(wake_trigger.openwakeword, "Model", MagicMock(return_value=fake_model))

    seen = []
    trigger = wake_trigger.OpenWakeWordTrigger(
        str(model_path), on_trigger=MagicMock(), on_score=lambda lvl, s: seen.append((lvl, s))
    )
    block = np.array([100, -100, 100, -100], dtype=np.int16)
    trigger._on_block(block.tobytes(), 4, None, None)

    assert seen == [(100.0, 0.42)]


def test_on_score_is_optional(tmp_path, monkeypatch):
    model_path = tmp_path / "tron.onnx"
    model_path.write_bytes(b"fake")
    fake_model = MagicMock()
    fake_model.predict.return_value = {"tron": 0.1}
    monkeypatch.setattr(wake_trigger.openwakeword, "Model", MagicMock(return_value=fake_model))

    trigger = wake_trigger.OpenWakeWordTrigger(str(model_path), on_trigger=MagicMock())
    block = np.array([1, 2], dtype=np.int16)
    trigger._on_block(block.tobytes(), 2, None, None)  # must not raise


def test_hey_jarvis_wakes_tron_as_jarvis(tmp_path, monkeypatch):
    model_path = tmp_path / "tron.onnx"
    model_path.write_bytes(b"fake")
    jarvis = tmp_path / "hey_jarvis_v0.1.onnx"
    jarvis.write_bytes(b"fake")
    monkeypatch.setattr(wake_trigger.openwakeword, "Model", MagicMock())
    order = []
    trigger = wake_trigger.OpenWakeWordTrigger(
        str(model_path), on_trigger=lambda: order.append("wake"),
        extra_models={str(jarvis): "jarvis", str(tmp_path / "hey_friday.onnx"): "friday"},   # friday not trained
        on_assistant=order.append)
    assert trigger._assistant_for == {"hey_jarvis_v0.1": "jarvis"}
    trigger._fire("hey_jarvis_v0.1")
    trigger._fire("tron")                     # "hey tron" wakes whoever is active, no switch
    assert order == ["jarvis", "wake", "wake"]
