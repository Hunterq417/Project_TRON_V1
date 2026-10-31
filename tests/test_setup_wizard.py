# tests/test_setup_wizard.py
import json

import setup_wizard


def test_build_config_dict_fills_required_and_optional_fields():
    form = {
        "gemini_api_key": "  my-key  ",
        "hotkey": "ctrl+alt+j",
        "smtp_host": "smtp.example.com",
        "smtp_port": "587",
        "smtp_user": "me@example.com",
        "smtp_app_password": "pw",
    }

    result = setup_wizard.build_config_dict(form)

    assert result["gemini_api_key"] == "my-key"
    assert result["hotkey"] == "ctrl+alt+j"
    assert result["smtp_port"] == 587
    assert result["smtp_user"] == "me@example.com"


def test_build_config_dict_defaults_when_optional_fields_blank():
    form = {"gemini_api_key": "my-key", "hotkey": ""}

    result = setup_wizard.build_config_dict(form)

    assert result["hotkey"] == "ctrl+alt+t"
    assert result["smtp_port"] == 465
    assert result["smtp_host"] == ""


def test_build_config_dict_defaults_camera_and_screen_to_false():
    form = {"gemini_api_key": "my-key"}
    result = setup_wizard.build_config_dict(form)
    assert result["camera_enabled"] is False
    assert result["screen_enabled"] is False


def test_build_config_dict_respects_explicit_camera_and_screen_flags():
    form = {"gemini_api_key": "my-key", "camera_enabled": True, "screen_enabled": True}
    result = setup_wizard.build_config_dict(form)
    assert result["camera_enabled"] is True
    assert result["screen_enabled"] is True


def test_write_config_file_writes_valid_json(tmp_path):
    path = tmp_path / "config.json"
    config_dict = {"gemini_api_key": "k"}

    setup_wizard.write_config_file(path, config_dict)

    assert json.loads(path.read_text(encoding="utf-8")) == {"gemini_api_key": "k"}


def test_no_gemini_key_means_local_mode():
    assert setup_wizard.build_config_dict({"gemini_api_key": ""})["brain"] == "local"
    assert setup_wizard.build_config_dict({"gemini_api_key": "k"})["brain"] == "gemini"
