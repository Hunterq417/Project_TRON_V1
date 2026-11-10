# latency.py
"""How fast TRON answers, in microseconds. One line per measurement in logs/latency.jsonl:

  response  end of the user's speech -> first audio of the reply (what you feel as "lag")
  tool      one tool call from start to result

The clock is time.perf_counter_ns(). The start point is the last mic chunk loud enough to be speech; chunks
are read every 50 ms, so a single "response" figure can be off by up to that much. The medians are what count.

    .venv\\Scripts\\python src\\latency.py       summary of everything measured
"""
import json
import statistics
import threading
import time

import config

PATH = config.app_dir() / "logs" / "latency.jsonl"
_lock = threading.Lock()


def now_ns() -> int:
    return time.perf_counter_ns()


def record(kind: str, start_ns: int, brain: str = "gemini", detail: str = "") -> int:
    """Logs now - start_ns as microseconds and returns it."""
    us = (time.perf_counter_ns() - start_ns) // 1000
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind, "brain": brain, "us": us, "detail": detail}
    try:
        with _lock:
            PATH.parent.mkdir(parents=True, exist_ok=True)
            with PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
    except OSError:
        pass   # measuring must never break a conversation
    return us


def summary(path=None) -> str:
    try:
        rows = [json.loads(l) for l in (path or PATH).read_text(encoding="utf-8").splitlines() if l.strip()]
    except (OSError, ValueError):
        return "Nothing measured yet."
    out = []
    for key in sorted({(r["kind"], r["brain"]) for r in rows}):
        us = sorted(r["us"] for r in rows if (r["kind"], r["brain"]) == key)
        p90 = us[min(len(us) - 1, int(len(us) * 0.9))]
        out.append(f"{key[0]:8} {key[1]:7} n={len(us):4}  median {statistics.median(us):>11,.0f} us  "
                   f"p90 {p90:>11,} us  best {us[0]:>11,} us")
    return "\n".join(out)


if __name__ == "__main__":
    print(summary())
