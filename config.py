# config.py
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Union


def app_dir() -> Path:
    """Directory config/persona files live in: next to the .exe when frozen
    (PyInstaller --onefile extracts to a temp dir, so __file__ is unusable
    there), next to this script in dev mode."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def resolve_path(path_str: Union[str, Path]) -> Path:
    """Resolves a config path string against app_dir(), unless it's already absolute."""
    path = Path(path_str)
    return path if path.is_absolute() else app_dir() / path


CONFIG_PATH = app_dir() / "config.json"


@dataclass
class Config:
    gemini_api_key: str
    wake_mode: str
    hotkey: str
    wakeword_model_path: str
    persona_path: str
    silence_timeout_s: float
    voice_name: str
    model_name: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_app_password: str
    camera_enabled: bool
    screen_enabled: bool


def load_config() -> Config:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Missing {CONFIG_PATH}. Copy config.example.json to config.json "
            "and fill in gemini_api_key."
        )
    data = json.loads(CONFIG_PATH.read_text())
    return Config(
        gemini_api_key=data["gemini_api_key"],
        wake_mode=data.get("wake_mode", "hotkey"),
        hotkey=data.get("hotkey", "ctrl+alt+t"),
        wakeword_model_path=data.get("wakeword_model_path", "models/tron.onnx"),
        persona_path=data.get("persona_path", "persona.txt"),
        silence_timeout_s=data.get("silence_timeout_s", 45.0),
        voice_name=data.get("voice_name", "Charon"),
        model_name=data.get("model_name", "gemini-2.0-flash-live-001"),
        smtp_host=data.get("smtp_host", ""),
        smtp_port=data.get("smtp_port", 465),
        smtp_user=data.get("smtp_user", ""),
        smtp_app_password=data.get("smtp_app_password", ""),
        camera_enabled=data.get("camera_enabled", False),
        screen_enabled=data.get("screen_enabled", False),
    )
