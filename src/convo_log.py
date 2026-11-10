# convo_log.py
"""Every conversation, written out as plain text: what you said, what TRON did, what TRON answered.

Kept for training TRON later, so it records the exact order of events — the words that led to each tool
call matter as much as the call — and every tool's arguments and result, including the failures and the
calls the safety layer refused. One file, appended to, in TRON's folder: logs\\conversation_log.txt.

    ===== 2026-10-07 14:02:11 =====
    YOU:  open spotify and play dancing with your ghost
    DID:  play_music(query="Dancing With Your Ghost") -> playing Sasha Alex Sloan - Dancing With Your Ghost on Spotify, sir
    TRON: Playing it now, sir.
"""
import datetime
import json
import re
import threading

import config

LABELS = {"user": "YOU: ", "assistant": "TRON:", "tool": "DID: ", "note": "NOTE:"}


_lock = threading.Lock()   # appends and the panel's deletes rewrite the same file


def path():
    return config.app_dir() / "logs" / "conversation_log.txt"


def format_events(events) -> list:
    """(role, text) events in arrival order -> log lines. Speech arrives in fragments, so consecutive
    fragments from the same speaker are joined; each tool call stays its own line."""
    lines, current_role, buffer = [], None, ""

    def flush():
        if current_role and buffer.strip():
            lines.append(f"{LABELS[current_role]} {' '.join(buffer.split())}")

    for role, text in events:
        if role in ("tool", "note"):
            flush()
            current_role, buffer = None, ""
            lines.append(f"{LABELS[role]} {text}")
            continue
        if role != current_role:
            flush()
            current_role, buffer = role, ""
        buffer += text
    flush()
    return lines


def tool_line(name: str, args: dict, result: str) -> str:
    shown = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in (args or {}).items())
    return f"{name}({shown}) -> {' '.join(str(result).split())}"


class Session:
    """One conversation's log, written as it goes: each turn is on disk as soon as it's finished, so a
    conversation that runs for an hour (or a TRON that crashes) still leaves its record."""

    def __init__(self, started: datetime.datetime = None):
        self.started = started or datetime.datetime.now()
        self._written = 0
        self._header = False

    def flush(self, events) -> None:
        """Writes the events not yet written. Never raises."""
        try:
            new = events[self._written:]
            lines = format_events(new)
            self._written = len(events)
            if not lines:
                return
            target = path()
            target.parent.mkdir(parents=True, exist_ok=True)
            with _lock, target.open("a", encoding="utf-8") as f:
                if not self._header:
                    f.write(f"\n===== {self.started.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
                    self._header = True
                f.write("\n".join(lines) + "\n")
        except Exception:
            pass


def write(events, started: datetime.datetime = None) -> None:
    """Appends one conversation. Never raises: logging must not break what it records."""
    try:
        lines = format_events(events)
        if not lines:
            return
        stamp = (started or datetime.datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
        target = path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with _lock, target.open("a", encoding="utf-8") as f:
            f.write(f"\n===== {stamp} =====\n" + "\n".join(lines) + "\n")
    except Exception:
        pass


_KINDS = ("YOU:", "TRON", "DID:")


def _rewrite(change) -> bool:
    """Splits the log into [prefix, header, body, header, body, ...], lets change() edit that list, and writes it
    back atomically (a temp file, then replace). False when nothing changed or the log can't be read."""
    with _lock:
        try:
            text = path().read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        parts = re.split(r"(?m)^(===== .+? =====)$", text)
        if not change(parts):
            return False
        tmp = path().with_suffix(".tmp")
        tmp.write_text("".join(parts), encoding="utf-8")
        tmp.replace(path())
        return True


def _find(parts, stamp: str):
    return next((i for i in range(1, len(parts), 2) if parts[i] == f"===== {stamp} ====="), None)


def delete_conversation(stamp: str) -> bool:
    """Deletes one whole conversation, found by its "YYYY-MM-DD HH:MM:SS" header. Permanent.
    shortcut: deleting a conversation still in progress loses its header, so its later lines join the one
    before; fine for a panel that lists finished ones, revisit if live deletion is ever needed."""
    def change(parts):
        i = _find(parts, stamp)
        if i is None:
            return False
        del parts[i:i + 2]
        return True
    return _rewrite(change)


def delete_line(stamp: str, index: int) -> bool:
    """Deletes the index-th line (counting only YOU / TRON / DID lines) of one conversation. Permanent."""
    def change(parts):
        i = _find(parts, stamp)
        if i is None:
            return False
        lines = parts[i + 1].split("\n")
        spoken = [n for n, line in enumerate(lines) if line[:4] in _KINDS]
        if not 0 <= int(index) < len(spoken):
            return False
        del lines[spoken[int(index)]]
        parts[i + 1] = "\n".join(lines)
        return True
    return _rewrite(change)
