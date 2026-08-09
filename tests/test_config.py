# tests/test_config.py
import json
import pytest
import config as config_module


def test_load_config_reads_fields(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "gemini_api_key": "test-key",
        "wake_mode": "hotkey",
        "hotkey": "ctrl+alt+t",
        "wakeword_model_path": "models/tron.onnx",
        "persona_path": "persona.txt",
        "silence_timeout_s": 30.0,
        "voice_name": "Charon",
        "model_name": "gemini-2.0-flash-live-001",
    }))
    monkeypatch.setattr(config_module, "CONFIG_PATH", cfg_path)

    cfg = config_module.load_config()

    assert cfg.gemini_api_key == "test-key"
    assert cfg.silence_timeout_s == 30.0
    assert cfg.voice_name == "Charon"


def test_load_config_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "does_not_exist.json")

    with pytest.raises(FileNotFoundError):
        config_module.load_config()
