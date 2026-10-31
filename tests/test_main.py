# tests/test_main.py
from types import SimpleNamespace

import main


def test_report_microphone_names_the_device(monkeypatch):
    monkeypatch.setattr(main.audio_io, "microphone_name", lambda d: "Some Mic")
    boxes = []
    monkeypatch.setattr(main, "_warn_box", lambda title, msg: boxes.append(msg))

    main._report_microphone(SimpleNamespace(mic_device=None))

    assert boxes == []


def test_report_microphone_does_not_warn_about_a_quiet_microphone(monkeypatch):
    """The regression this guards: an idle noise-gated headset reads the same
    near-zero level as a muted one, so judging a mic by its idle level popped a
    'microphone problem' dialog on hardware that was working. Naming the device
    is all this may do."""
    monkeypatch.setattr(main.audio_io, "microphone_name", lambda d: "Quiet Headset")
    boxes = []
    monkeypatch.setattr(main, "_warn_box", lambda title, msg: boxes.append(msg))

    main._report_microphone(SimpleNamespace(mic_device=None))

    assert boxes == []
    assert not hasattr(main.audio_io, "SILENT_LEVEL"), (
        "idle-level silence checks were removed deliberately -- see audio_io"
    )


def test_report_microphone_warns_when_the_device_cannot_be_found(monkeypatch):
    """A mic_device pointing at a device that is not there can never work, which
    unlike a quiet mic is worth interrupting for."""
    def boom(device):
        raise ValueError("no such device")

    monkeypatch.setattr(main.audio_io, "microphone_name", boom)
    boxes = []
    monkeypatch.setattr(main, "_warn_box", lambda title, msg: boxes.append(msg))

    main._report_microphone(SimpleNamespace(mic_device="nope"))  # must not raise

    assert len(boxes) == 1
    assert "--list-mics" in boxes[0]


def test_wake_word_mode_keeps_the_hotkey_live_as_well(monkeypatch):
    """Wake-word recall depends on the speaker's voice and the microphone. When
    it misses, the hotkey is the only way in — so it must not be switched off
    just because a wake word is configured."""
    import main as m

    started = []
    monkeypatch.setattr(m, "_report_microphone", lambda cfg: None)
    monkeypatch.setattr(m, "OrbUI", lambda: SimpleNamespace(
        run=lambda on_ready: on_ready(), quit=lambda: None,
        toggle_visibility=lambda: None, on_state_change=lambda s: None,
        on_audio_level=lambda level: None))
    monkeypatch.setattr(m, "TrayUI", lambda **kw: SimpleNamespace(
        start=lambda: started.append("tray"), stop=lambda: None,
        on_state_change=lambda s: None))
    monkeypatch.setattr(m, "TronStateMachine",
                        lambda **kw: SimpleNamespace(trigger=lambda: None, hotkey=lambda: None,
                                                     greet=lambda note: None))
    monkeypatch.setattr(m.config_module, "CONFIG_PATH", SimpleNamespace(exists=lambda: True))
    monkeypatch.setattr(m.config_module, "load_config", lambda: SimpleNamespace(
        wake_mode="openwakeword", hotkey="ctrl+alt+t", persona_path="persona.txt",
        wakeword_model_path="models/tron.onnx", mic_device=None, speaker_device=None,
        gemini_api_key="k", model_name="m", voice_name="v", silence_timeout_s=45.0))
    monkeypatch.setattr(m.config_module, "resolve_path",
                        lambda p: SimpleNamespace(read_text=lambda encoding=None: "persona"))
    monkeypatch.setattr(m, "OpenWakeWordTrigger",
                        lambda *a, **kw: SimpleNamespace(start=lambda: started.append("wake"),
                                                        stop=lambda: None))
    monkeypatch.setattr(m, "HotkeyTrigger",
                        lambda *a, **kw: SimpleNamespace(start=lambda: started.append("hotkey"),
                                                        stop=lambda: None))

    m.main()

    assert "wake" in started
    assert "hotkey" in started, "the hotkey must stay available in wake-word mode"
