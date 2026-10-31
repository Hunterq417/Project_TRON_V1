# memory.py
"""What TRON keeps between conversations.

Three separate things, deliberately not merged:

* activity.jsonl - what TRON *did*. An append-only action log, capped.
* facts.json     - what TRON *knows about the user*. Durable, upserted by key.
* last_session.json - what was *last talked about*. One line, read once, then gone.

They are kept apart because they answer different questions and are read in
different places. "What have you been up to?" returns the action log verbatim
(tools._recall_activity), so folding identity into it would answer a question
about TRON's actions with a dossier on its user.
"""
import json
import os
import threading
from datetime import datetime, timezone

import config

_LOG_PATH = config.app_dir() / "memory" / "activity.jsonl"
_FACTS_PATH = config.app_dir() / "memory" / "facts.json"

# (kind, key) identifies a fact, so saying the same thing twice updates in place.
# That is also how corrections work: "actually I prefer tea" overwrites rather
# than accumulating a contradiction.
_KINDS = ("identity", "preference", "project", "workflow", "task", "fact")
_MAX_FACTS = 120        # ~7 KB of system prompt; the whole store fits in context
_MAX_VALUE = 300
_lock = threading.Lock()

_HEADINGS = (
    ("identity", "Who the user is"),
    ("preference", "Their preferences"),
    ("project", "Their projects"),
    ("workflow", "How they like things done"),
    ("task", "Ongoing work"),
    ("fact", "Other things worth remembering"),
)


_MAX_LOG_BYTES = 256 * 1024
_KEEP_LOG_LINES = 400


def log_activity(entry: dict) -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {**entry, "at": datetime.now(timezone.utc).isoformat()}
    with _LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    _trim_log()


def _trim_log() -> None:
    """Keep the activity log from growing without bound.

    recent_context() reads the whole file and keeps the last few lines, at the
    start of every conversation. The file is append-only, so that read gets
    slower forever — it was already 35 KB after a few weeks of ordinary use.

    Trimming happens after the append, never before: doing it first would drop
    the line just written."""
    try:
        if _LOG_PATH.stat().st_size <= _MAX_LOG_BYTES:
            return
        lines = _LOG_PATH.read_text(encoding="utf-8").splitlines()[-_KEEP_LOG_LINES:]
        _LOG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass    # a log that cannot be tidied is not worth failing a conversation over


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


def _load_facts() -> list:
    """Every fact on disk. Never raises: a broken store must not stop TRON."""
    try:
        data = json.loads(_FACTS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception:
        # Unreadable rather than absent. Move it aside so the next write starts
        # clean, but keep it around — it is the only copy of what TRON knew.
        try:
            _FACTS_PATH.replace(_FACTS_PATH.with_suffix(".corrupt"))
        except OSError:
            pass
        return []
    facts = data.get("facts") if isinstance(data, dict) else data
    if not isinstance(facts, list):
        return []
    return [f for f in facts if isinstance(f, dict) and f.get("value")]


def _save_facts(facts: list) -> None:
    """Write atomically — this runs from inside a live conversation, and a
    half-written store read at the next launch would lose everything."""
    try:
        _FACTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _FACTS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, "facts": facts}, indent=2),
                       encoding="utf-8")
        os.replace(tmp, _FACTS_PATH)
    except OSError:
        pass


def remember(kind: str, key: str, value: str, status: str = "", **scores) -> None:
    """Record something durable about the user. Upserts on (kind, key)."""
    if not value:
        return
    kind = kind if kind in _KINDS else "fact"
    key = (key or value)[:60].strip().lower()
    entry = {"kind": kind, "key": key, "value": str(value)[:_MAX_VALUE],
             "at": datetime.now(timezone.utc).isoformat()}
    if status:
        entry["status"] = status
    # confidence / importance / source, from memory_service's extractor; scored on the way back out
    entry.update({k: v for k, v in scores.items() if k in ("confidence", "importance", "source") and v is not None})

    with _lock:
        facts = [f for f in _load_facts()
                 if not (f.get("kind") == kind and f.get("key") == key)]
        facts.append(entry)
        if len(facts) > _MAX_FACTS:
            # Evict oldest first, but never who the user is — a name is worth
            # more than any number of passing remarks.
            facts.sort(key=lambda f: (f.get("kind") == "identity", f.get("at", "")))
            facts = facts[len(facts) - _MAX_FACTS:]
        _save_facts(facts)


def forget(key: str, kind: str = "") -> bool:
    """Drop a fact. False when nothing matched, so TRON can say so rather than
    claim to have forgotten something it never knew."""
    key = (key or "").strip().lower()
    if not key:
        return False
    with _lock:
        facts = _load_facts()
        keep = [f for f in facts
                if f.get("key") != key or (kind and f.get("kind") != kind)]
        if len(keep) == len(facts):
            return False
        _save_facts(keep)
        return True


def all_facts(kind: str = "") -> list:
    """Everything remembered, newest first. Named all_facts because `facts` is
    the local variable inside remember/forget and shadowing that is a 3am bug."""
    facts = [f for f in _load_facts() if not kind or f.get("kind") == kind]
    return sorted(facts, key=lambda f: f.get("at", ""), reverse=True)


def long_term_context() -> str:
    """The store rendered for the system prompt. "" when there is nothing.

    Rendered as "key: value" on purpose — it reads as prose AND shows the model
    the keys already in use, which is what makes it re-use a key to correct a
    fact rather than inventing a second one that contradicts the first."""
    facts = _load_facts()
    if not facts:
        return ""
    sections = []
    for kind, heading in _HEADINGS:
        rows = sorted((f for f in facts if f.get("kind") == kind),
                      key=lambda f: f.get("key", ""))
        if not rows:
            continue
        lines = [heading + ":"]
        for f in rows:
            line = f"- {f.get('key')}: {f.get('value')}"
            if f.get("status"):
                line += f" [status: {f['status']}]"
            lines.append(line)
        sections.append("\n".join(lines))
    if not sections:
        return ""
    return ("What you already know about the user (long-term memory — treat as "
            "true, and correct it with remember_fact when they say otherwise):\n\n"
            + "\n\n".join(sections))


def join_transcript(fragments) -> list:
    """Turn a stream of (role, fragment) into whole turns.

    The Live API emits transcription in pieces as the audio streams — "It's",
    " Friday", ", sir." arrive as three events — so anything that treats one
    event as one utterance ends up with shredded nonsense. Consecutive
    fragments from the same speaker belong to one turn; a change of speaker
    ends it.

    Returns [{"role": "user"|"assistant", "text": str}, ...] with blank turns
    dropped."""
    turns: list = []
    for role, text in fragments:
        if not text:
            continue
        if turns and turns[-1]["role"] == role:
            turns[-1]["text"] += text
        else:
            turns.append({"role": role, "text": text})
    # Fragments carry their own leading spaces, so joining can leave edges ragged.
    for turn in turns:
        turn["text"] = turn["text"].strip()
    return [t for t in turns if t["text"]]
