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


def test_write_config_file_writes_valid_json(tmp_path):
    path = tmp_path / "config.json"
    config_dict = {"gemini_api_key": "k"}

    setup_wizard.write_config_file(path, config_dict)

    assert json.loads(path.read_text(encoding="utf-8")) == {"gemini_api_key": "k"}
