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


def test_load_config_defaults_camera_and_screen_to_disabled(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"gemini_api_key": "k"}))
    monkeypatch.setattr(config_module, "CONFIG_PATH", cfg_path)

    cfg = config_module.load_config()

    assert cfg.camera_enabled is False
    assert cfg.screen_enabled is False


def test_load_config_respects_explicit_camera_and_screen_flags(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "gemini_api_key": "k", "camera_enabled": True, "screen_enabled": True,
    }))
    monkeypatch.setattr(config_module, "CONFIG_PATH", cfg_path)

    cfg = config_module.load_config()

    assert cfg.camera_enabled is True
    assert cfg.screen_enabled is True


def test_app_dir_dev_mode(monkeypatch):
    monkeypatch.setattr(config_module.sys, "frozen", False, raising=False)
    assert config_module.app_dir() == Path(config_module.__file__).resolve().parent.parent   # project root, above src/


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


def _write(tmp_path, monkeypatch, data):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(config_module, "CONFIG_PATH", path)
    monkeypatch.setattr(config_module, "app_dir", lambda: tmp_path)
    return path


def test_a_config_without_assistants_keeps_its_own_voice(tmp_path, monkeypatch):
    # Backward compatibility: an install that never chose a profile must not have
    # its voice quietly replaced by the default profile's.
    _write(tmp_path, monkeypatch, {"gemini_api_key": "k", "voice_name": "Zephyr"})
    assert config_module.load_config().voice_name == "Zephyr"


def test_choosing_an_assistant_takes_over_the_voice(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch,
           {"gemini_api_key": "k", "voice_name": "Zephyr", "active_assistant": "jarvis"})
    assert config_module.load_config().voice_name == "Charon"


def test_a_profile_persona_that_does_not_exist_is_ignored(tmp_path, monkeypatch):
    # Selecting JARVIS before writing its persona should change the voice, not
    # stop TRON from starting.
    _write(tmp_path, monkeypatch,
           {"gemini_api_key": "k", "persona_path": "persona.txt", "active_assistant": "jarvis"})
    cfg = config_module.load_config()
    assert cfg.persona_path == "persona.txt"
    assert cfg.voice_name == "Charon"


def test_a_profile_persona_that_exists_is_used(tmp_path, monkeypatch):
    (tmp_path / "personas").mkdir()
    (tmp_path / "personas" / "friday.txt").write_text("hi", encoding="utf-8")
    _write(tmp_path, monkeypatch,
           {"gemini_api_key": "k", "persona_path": "persona.txt", "active_assistant": "friday"})
    assert config_module.load_config().persona_path == "personas/friday.txt"


def test_an_unknown_active_assistant_falls_back_to_the_first(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, {"gemini_api_key": "k", "active_assistant": "nobody"})
    assert config_module.load_config().voice_name == "Orus"
