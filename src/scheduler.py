# scheduler.py
"""Recurring tasks: "every weekday at 9, read me my unread mail", "every day at 11 pm, remind me to sleep".

Kept in memory/schedules.json, so they survive restarts. When one is due TRON opens a conversation by itself
with the task as its instruction and does it with its normal tools, under the same safety rules: anything that
needs the user's spoken yes still waits for it. A task missed while the PC was off runs if TRON starts within
15 minutes of its time, otherwise it waits for the next day.
"""
import datetime
import json
import threading
import time
import uuid

import config

PATH = config.app_dir() / "memory" / "schedules.json"
GRACE = datetime.timedelta(minutes=15)
_lock = threading.Lock()
_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_GROUPS = {"every day": list(range(7)), "daily": list(range(7)), "weekdays": list(range(5)),
           "weekends": [5, 6]}


def _load() -> list:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save(items: list) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(items, indent=1), encoding="utf-8")


def parse_days(days: str) -> list:
    text = (days or "every day").strip().lower()
    if text in _GROUPS:
        return _GROUPS[text]
    found = sorted({i for i, d in enumerate(_DAYS) if d in text})
    if not found:
        raise ValueError(f'"{days}" isn\'t a day I know: use every day, weekdays, weekends or e.g. "mon, thu"')
    return found


def due(items: list, now: datetime.datetime) -> list:
    """Schedules to run now. Doesn't change anything."""
    out = []
    for s in items:
        h, m = map(int, s["time"].split(":"))
        at = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if now.weekday() in s["days"] and at <= now < at + GRACE and s.get("last_run") != now.date().isoformat():
            out.append(s)
    return out


def schedule_task(args, cfg=None) -> str:
    task, at = str(args.get("task", "")).strip(), str(args.get("time", "")).strip()
    try:
        h, m = map(int, at.split(":"))
        assert 0 <= h < 24 and 0 <= m < 60 and task
    except (ValueError, AssertionError, TypeError):
        return 'I need a task and a 24-hour time like "09:00", sir.'
    try:
        days = parse_days(args.get("days", "every day"))
    except ValueError as exc:
        return str(exc)
    with _lock:
        items = _load()
        items.append({"id": uuid.uuid4().hex[:6], "task": task, "time": f"{h:02d}:{m:02d}", "days": days,
                      "last_run": datetime.date.today().isoformat() if datetime.datetime.now().time()
                      >= datetime.time(h, m) else None})   # set after today's time: starts tomorrow
        _save(items)
    return f'Scheduled: "{task}" at {h:02d}:{m:02d} on {_say_days(days)}.'


def _say_days(days: list) -> str:
    for name, group in _GROUPS.items():
        if days == group and name != "daily":
            return name
    return ", ".join(_DAYS[d] for d in days)


def list_schedules(args=None, cfg=None) -> str:
    items = _load()
    if not items:
        return "No recurring tasks, sir."
    return "\n".join(f'[{s["id"]}] {s["time"]} {_say_days(s["days"])}: {s["task"]}' for s in items)


def cancel_schedule(args, cfg=None) -> str:
    what = str(args.get("which", "")).strip().lower()
    with _lock:
        items = _load()
        keep = [s for s in items if not what or (s["id"] != what and what not in s["task"].lower())]
        if len(keep) == len(items) or not what:
            return "I couldn't find that recurring task, sir."
        _save(keep)
    return f"Cancelled {len(items) - len(keep)} recurring task(s)."


def start(run_task) -> None:
    """Calls run_task(task_text) from a background thread whenever a schedule comes due."""
    def loop():
        while True:
            time.sleep(20)
            now = datetime.datetime.now()
            with _lock:
                items = _load()
                ready = due(items, now)
                for s in ready:
                    s["last_run"] = now.date().isoformat()
                if ready:
                    _save(items)
            for s in ready:
                try:
                    run_task(s["task"])
                except Exception as exc:
                    print(f"scheduled task failed: {exc}")
    threading.Thread(target=loop, daemon=True).start()


DECLARATIONS = [
    {"name": "schedule_task",
     "description": "Set up a RECURRING task TRON does by itself: 'every weekday at 9 read my unread mail'. "
                    "For a one-off countdown use set_timer instead.",
     "parameters": {"type": "object", "properties": {
         "task": {"type": "string", "description": "what to do, as an instruction to yourself"},
         "time": {"type": "string", "description": "24-hour HH:MM"},
         "days": {"type": "string", "description": "every day, weekdays, weekends, or days like 'mon, thu'"}},
         "required": ["task", "time"]}},
    {"name": "list_schedules", "description": "The user's recurring tasks.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "cancel_schedule", "description": "Cancel a recurring task by its id or words from it.",
     "parameters": {"type": "object", "properties": {"which": {"type": "string"}}, "required": ["which"]}},
]
