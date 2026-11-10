# routine.py
"""Learns the user's routine from what they ask TRON to do: the tool, what it was for (an app, a song), the
weekday and the hour. Never what was said. A habit is reported only once it has been seen on MIN_DAYS
different days, and always as an inference ("seen on 4 days"), never as a fact. Paused with the rest of
learning (memory_enabled off); "forget my routine" deletes the file.
"""
import collections
import datetime
import json
import threading

import config

_PATH = config.app_dir() / "memory" / "routine.jsonl"
_lock = threading.Lock()
MIN_DAYS = 3
# Asking about the routine, or anything that only reads, isn't a habit worth reporting.
_SKIP = {"my_routine", "forget_routine", "current_time", "check_timers", "recall_activity", "who_is_here",
         "who_is_speaking", "switch_assistant"}
_DETAIL_KEYS = ("target", "query", "url", "app", "name", "site")


def _part(hour: int) -> str:
    return ("in the morning" if 5 <= hour < 12 else "in the afternoon" if hour < 17
            else "in the evening" if hour < 22 else "at night")


def observe(name: str, args: dict, cfg=None, now: datetime.datetime = None) -> None:
    if name in _SKIP or not getattr(cfg, "memory_enabled", True):
        return
    detail = next((str(args[k]).strip().lower()[:40] for k in _DETAIL_KEYS
                   if isinstance(args, dict) and isinstance(args.get(k), str) and args[k].strip()), "")
    now = now or datetime.datetime.now()
    row = {"tool": name, "detail": detail, "date": now.date().isoformat(), "weekday": now.strftime("%A"),
           "hour": now.hour}
    try:
        with _lock:
            _PATH.parent.mkdir(parents=True, exist_ok=True)
            with _PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
    except OSError:
        pass   # learning is a nicety; it must never break the command it watched


def patterns() -> list:
    """(description, days seen), most-seen first. Only habits seen on MIN_DAYS different days."""
    try:
        rows = [json.loads(line) for line in _PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError):
        return []
    days = collections.defaultdict(set)
    weekdays = collections.defaultdict(set)
    for r in rows:
        key = (r["tool"], r.get("detail", ""), _part(r["hour"]))
        days[key].add(r["date"])
        weekdays[key].add(r["weekday"])
    found = []
    for (tool, detail, part), seen in days.items():
        if len(seen) < MIN_DAYS:
            continue
        what = tool.replace("_", " ") + (f" ({detail})" if detail else "")
        when = f"on {next(iter(weekdays[(tool, detail, part)]))}s {part}" if len(weekdays[(tool, detail, part)]) == 1 \
            else part
        found.append((f"{what} {when}", len(seen)))
    return sorted(found, key=lambda p: -p[1])


def my_routine(args, cfg) -> str:
    found = patterns()[:8]
    if not found:
        return ("I haven't seen a habit often enough yet, sir. I need the same thing on at least "
                f"{MIN_DAYS} different days before I'd call it a routine.")
    return "Inferred from what you've asked me (not confirmed): " + "; ".join(
        f"{what}, seen on {n} days" for what, n in found) + "."


def forget_routine(args, cfg) -> str:
    with _lock:
        try:
            _PATH.unlink()
        except FileNotFoundError:
            return "There was nothing learned about your routine, sir."
    return "Done, sir. Everything I'd learned about your routine is deleted."


DECLARATIONS = [
    {"name": "my_routine",
     "description": "What the user usually does and when (e.g. 'what do I usually do on Monday mornings?'), "
                    "inferred from the commands they've given. Say it's an inference.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "forget_routine",
     "description": "Delete everything learned about the user's routine. Only when they clearly ask.",
     "parameters": {"type": "object", "properties": {}}},
]
