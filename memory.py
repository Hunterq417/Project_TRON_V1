# memory.py
import json
from datetime import datetime, timezone

import config

_LOG_PATH = config.app_dir() / "memory" / "activity.jsonl"


def log_activity(entry: dict) -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {**entry, "at": datetime.now(timezone.utc).isoformat()}
    with _LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def recent_context(n: int = 10) -> str:
    if not _LOG_PATH.exists():
        return ""
    lines = _LOG_PATH.read_text(encoding="utf-8").splitlines()
    entries = []
    for line in lines[-n:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not entries:
        return ""
    formatted = "\n".join(
        f"- {e.get('at', '?')}: {e.get('tool', '?')}({e.get('args', {})}) -> {e.get('result', '')}"
        for e in entries
    )
    return f"Recent activity (most recent last):\n{formatted}"


def clear() -> None:
    if _LOG_PATH.exists():
        _LOG_PATH.unlink()
