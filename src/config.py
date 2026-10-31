# config.py
import json
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Union

APP_NAME = "TRON"
APP_VERSION = "0.1"
# What the app calls itself anywhere a human reads it: tray tooltip, orb window
# title, startup line. Single source of truth — bump APP_VERSION only.
APP_LABEL = f"{APP_NAME} v{APP_VERSION}"


def app_dir() -> Path:
    """Directory config/persona files live in: next to the .exe when frozen
    (PyInstaller --onefile extracts to a temp dir, so __file__ is unusable
    there), the project root (one above src/) in dev mode."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def resolve_path(path_str: Union[str, Path]) -> Path:
    """Resolves a config path string against app_dir(), unless it's already absolute."""
    path = Path(path_str)
    return path if path.is_absolute() else app_dir() / path


CONFIG_PATH = app_dir() / "config.json"

_write_lock = threading.Lock()


def update_config_file(patch: dict) -> dict:
    """Merge patch into config.json atomically and return the result.

    The only writer of config.json — the orb (widget position) and the
    dashboard both come through here, serialised by one lock so they cannot
    trample each other's temp file. Raises if the existing file cannot be read:
    the orb used to treat that as "empty" and write back a config holding only
    the widget position, wiping the API key and every other setting."""
    with _write_lock:
        data = (json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                if CONFIG_PATH.exists() else {})
        if not isinstance(data, dict):
            raise ValueError("config.json is not a JSON object")
        data.update(patch)
        tmp = CONFIG_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(CONFIG_PATH)
        return data

# Assistant profiles. Each is a name, a voice and optionally its own persona, so
# one install can answer as more than one character. Only the active one is
# loaded; switching is done from the dashboard (and, later, by voice).
#
# Personas are optional on purpose: a profile with no persona file of its own
# falls back to the default one, so selecting JARVIS changes the voice
# immediately and picks up its own character as soon as you write it.
DEFAULT_ASSISTANTS = [
    {"id": "tron", "name": "TRON", "voice": "Orus", "persona_path": "persona.txt"},
    {"id": "jarvis", "name": "JARVIS", "voice": "Charon", "persona_path": "personas/jarvis.txt"},
    {"id": "friday", "name": "FRIDAY", "voice": "Aoede", "persona_path": "personas/friday.txt"},
]


def active_assistant(data: dict) -> dict:
    """The profile currently in charge, from raw config data."""
    assistants = data.get("assistants") or DEFAULT_ASSISTANTS
    wanted = data.get("active_assistant")
    for assistant in assistants:
        if assistant.get("id") == wanted:
            return assistant
    return assistants[0]


@dataclass
class Config:
    gemini_api_key: str
    wake_mode: str
    hotkey: str
    wakeword_model_path: str
    mic_device: Union[int, str, None]
    speaker_device: Union[int, str, None]
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
    # Optional. Dictation is transcribed through OpenRouter when this is set, with Gemini as the backup.
    openrouter_api_key: str = ""
    # "gemini": Gemini Live hears, thinks and speaks (needs the internet). "local": everything on this PC —
    # Parakeet hears, a model in Ollama thinks, Kokoro speaks. Gemini mode falls back to local when offline.
    brain: str = "gemini"
    local_model: str = "qwen3.5:4b"
    local_voice: str = "david"   # a Windows voice (david, zira, hazel) or a Kokoro voice (e.g. am_michael)
    # The local brain's limits and switches (see local_brain.py). brain_debug writes each decision into the
    # conversation log; memory_weights overrides memory_service.WEIGHTS.
    brain_max_tool_calls: int = 8
    brain_max_replans: int = 2
    brain_debug: bool = False
    memory_enabled: bool = True
    memory_weights: dict = None


def load_config() -> Config:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Missing {CONFIG_PATH}. Copy config.example.json to config.json "
            "and fill in gemini_api_key."
        )
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cfg = Config(
        gemini_api_key=data.get("gemini_api_key", ""),   # empty is fine in Local mode
        wake_mode=data.get("wake_mode", "hotkey"),
        hotkey=data.get("hotkey", "ctrl+alt+t"),
        wakeword_model_path=data.get("wakeword_model_path", "models/tron.onnx"),
        # null = whatever Windows calls the default input. Set it when the
        # default is the wrong device: an int index or any substring of the
        # device name ("HyperX"), which sounddevice matches itself. A name is
        # the safer choice — indices shift as devices come and go.
        # `TRON.exe --list-mics` prints the options.
        mic_device=data.get("mic_device", None),
        # Where TRON's voice comes out. Same rules as mic_device. Worth setting
        # when the Windows default is a bluetooth headset that is not always
        # in your ears — TRON answering into a disconnected earbud is
        # indistinguishable from TRON not answering.
        speaker_device=data.get("speaker_device", None),
        persona_path=data.get("persona_path", "persona.txt"),
        silence_timeout_s=data.get("silence_timeout_s", 45.0),
        voice_name=data.get("voice_name", "Orus"),
        model_name=data.get("model_name", "gemini-3.1-flash-live-preview"),
        smtp_host=data.get("smtp_host", ""),
        smtp_port=data.get("smtp_port", 465),
        smtp_user=data.get("smtp_user", ""),
        smtp_app_password=data.get("smtp_app_password", ""),
        camera_enabled=data.get("camera_enabled", False),
        screen_enabled=data.get("screen_enabled", False),
        openrouter_api_key=data.get("openrouter_api_key", ""),
        brain=data.get("brain", "gemini"),
        local_model=data.get("local_model", "qwen3.5:4b"),
        local_voice=data.get("local_voice", "david"),
        brain_max_tool_calls=int(data.get("brain_max_tool_calls", 8)),
        brain_max_replans=int(data.get("brain_max_replans", 2)),
        brain_debug=bool(data.get("brain_debug", False)),
        memory_enabled=bool(data.get("memory_enabled", True)),
        memory_weights=data.get("memory_weights") or None,
    )
    # Only overlay a profile once the config has actually opted into assistants.
    # Otherwise a plain config.json that sets voice_name would silently have it
    # replaced by the default profile's voice — which an existing install would
    # experience as TRON changing voice for no reason.
    if data.get("active_assistant") or data.get("assistants"):
        return _apply_assistant(cfg, active_assistant(data))
    return cfg


def _apply_assistant(cfg: "Config", assistant: dict) -> "Config":
    """Overlays the active profile's voice and persona onto the base config.

    Everything downstream keeps reading cfg.voice_name and cfg.persona_path, so
    switching assistant needs no changes anywhere else. A persona the profile
    names but has not been written yet is ignored rather than fatal — a missing
    file should change the character, not stop TRON from starting."""
    voice = assistant.get("voice")
    if voice:
        cfg.voice_name = voice
    persona = assistant.get("persona_path")
    if persona and resolve_path(persona).is_file():
        cfg.persona_path = persona
    return cfg
