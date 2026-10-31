# timers.py
"""Timers and reminders, ported from Hey Jev.

Jev parsed "twenty five minutes" itself because its brain only answered multiple-choice questions. TRON's
brain is Gemini, which turns speech into a number of seconds on its own, so only the store and the
countdown loop came across — the duration parser stayed behind.
"""
import threading
import time

_timers: list = []
_lock = threading.Lock()


def add(seconds: float, label: str = "") -> dict:
    timer = {"end": time.time() + seconds, "secs": seconds, "label": label.strip()}
    with _lock:
        _timers.append(timer)
        _timers.sort(key=lambda t: t["end"])
    return timer


def snapshot() -> list:
    """(name, seconds left) for each running timer, soonest first."""
    now = time.time()
    with _lock:
        return [(t["label"].capitalize() or short_duration(t["secs"]) + " timer", max(0.0, t["end"] - now))
                for t in _timers]


def cancel(everything: bool = False) -> int:
    """Cancels the most recently set timer, or all of them. Returns how many went."""
    with _lock:
        if not _timers:
            return 0
        if everything:
            n = len(_timers)
            _timers.clear()
            return n
        _timers.remove(max(_timers, key=lambda t: t["end"] - t["secs"]))  # the one set most recently
        return 1


def due(now: float = None) -> list:
    """Removes and returns every timer that has run out."""
    now = time.time() if now is None else now
    with _lock:
        done = [t for t in _timers if t["end"] <= now]
        for t in done:
            _timers.remove(t)
    return done


def start_loop(on_done) -> None:
    """Calls on_done(timer) from a background thread as each timer runs out."""
    def loop():
        while True:
            time.sleep(0.25)
            for timer in due():
                try:
                    on_done(timer)
                except Exception as exc:  # one bad alert must not stop every later timer
                    print(f"timer alert failed: {exc}")
    threading.Thread(target=loop, daemon=True).start()


def short_duration(secs: float) -> str:
    h, rem = divmod(int(secs), 3600)
    m, s = divmod(rem, 60)
    return " ".join(f"{n} {u}" for n, u in ((h, "hr"), (m, "min"), (s, "sec")) if n) or "0 sec"


def say_duration(secs: float) -> str:
    """"4 minutes and 10 seconds", dropping seconds once the wait is long."""
    secs = max(0, int(round(secs)))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    parts = [f"{n} {u}{'' if n == 1 else 's'}" for n, u in ((h, "hour"), (m, "minute"), (s, "second")) if n]
    if h or m >= 10:
        parts = parts[:2] if h else parts[:1]
    return " and ".join(parts) or "no time"
