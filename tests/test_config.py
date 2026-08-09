# tests/test_config.py
import json
from pathlib import Path

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


def test_app_dir_dev_mode(monkeypatch):
    monkeypatch.setattr(config_module.sys, "frozen", False, raising=False)
    assert config_module.app_dir() == Path(config_module.__file__).parent


def test_app_dir_frozen(monkeypatch):
    monkeypatch.setattr(config_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config_module.sys, "executable", "C:\\Apps\\TRON\\TRON.exe", raising=False)

    assert config_module.app_dir() == Path("C:\\Apps\\TRON")


def test_resolve_path_relative_resolves_against_app_dir(monkeypatch):
    monkeypatch.setattr(config_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config_module.sys, "executable", "C:\\Apps\\TRON\\TRON.exe", raising=False)

    assert config_module.resolve_path("persona.txt") == Path("C:\\Apps\\TRON\\persona.txt")


def test_resolve_path_absolute_passes_through(monkeypatch):
    monkeypatch.setattr(config_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config_module.sys, "executable", "C:\\Apps\\TRON\\TRON.exe", raising=False)

    absolute = "D:\\elsewhere\\custom_persona.txt"
    assert config_module.resolve_path(absolute) == Path(absolute)
