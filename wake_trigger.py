# wake_trigger.py
"""
ponytail: hotkey trigger ships first; a wake-word backend (openWakeWord,
listening for "TRON") needs a trained model — see docs/train_wakeword.md —
and can be wired in later behind this same on_trigger() callback shape.
"""
from typing import Callable, Optional

import keyboard


class HotkeyTrigger:
    """Calls on_trigger() every time the configured global hotkey is pressed."""

    def __init__(self, hotkey: str, on_trigger: Callable[[], None]):
        self._hotkey = hotkey
        self._on_trigger = on_trigger
        self._handle: Optional[str] = None

    def start(self) -> None:
        self._handle = keyboard.add_hotkey(self._hotkey, self._on_trigger)

    def stop(self) -> None:
        if self._handle is not None:
            keyboard.remove_hotkey(self._handle)
            self._handle = None
