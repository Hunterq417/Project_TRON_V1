# media_control.py
import time

import keyboard

_SEEK_KEY = {"forward": "right", "backward": "left"}
_MAX_SEEK_SECONDS = 60
_SECONDS_PER_KEYPRESS = 5
_KEYPRESS_DELAY_S = 0.05


def play_pause() -> str:
    keyboard.send("play/pause media")
    return "toggled playback"


def next_track() -> str:
    keyboard.send("next track")
    return "skipped to the next track"


def previous_track() -> str:
    keyboard.send("previous track")
    return "went back to the previous track"


def seek(direction: str, seconds: int = 10) -> str:
    if direction not in _SEEK_KEY:
        return f'unknown seek direction "{direction}", sir — use "forward" or "backward"'
    if seconds > _MAX_SEEK_SECONDS:
        return (
            f"I can only nudge playback by simulated keystrokes, up to about "
            f"{_MAX_SEEK_SECONDS} seconds, sir — a jump that large will need to be done manually."
        )
    presses = max(1, round(seconds / _SECONDS_PER_KEYPRESS))
    key = _SEEK_KEY[direction]
    for _ in range(presses):
        keyboard.send(key)
        time.sleep(_KEYPRESS_DELAY_S)
    return f"skipped {direction} about {presses * _SECONDS_PER_KEYPRESS} seconds"
