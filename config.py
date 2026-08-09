# config.py
import json
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"


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
    )
