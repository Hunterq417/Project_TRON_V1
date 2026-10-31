# memory_service.py
"""What TRON remembers, chosen for the request at hand, and what it learns after each conversation.

Read path: every fact is scored for the current request and only the best few go into the prompt.
    score = w.relevance * relevance + w.importance * importance + w.freshness * freshness
          + w.task * task_relevance + w.confidence * confidence           (each 0..1; weights in config)
Who the user is (identity) always goes in.

Write path: when a conversation ends, the local model proposes durable memories from it; code keeps only
confident, useful ones and never a password, key or token. memory.py stays the store.
"""
import json
import math
import re
import time
from datetime import datetime

import memory

WEIGHTS = {"relevance": 0.45, "importance": 0.20, "freshness": 0.15, "task": 0.10, "confidence": 0.10}
TOP_K = 8
HALF_LIFE_DAYS = 30.0
MIN_CONFIDENCE = 0.75
MAX_NEW_PER_CONVERSATION = 3
_IMPORTANCE = {"identity": 1.0, "preference": 0.8, "workflow": 0.75, "project": 0.7, "task": 0.6, "fact": 0.5}
_STOP_WORDS = set("a an the to of and or in on at for is are was it this that my me i you your please can could "
                  "would will do does be with what how tron hey sir".split())
_SECRET = re.compile(r"(?i)\b(password|passcode|pin|otp|api[ _-]?key|token|secret|credential|cvv|"
                     r"card number|ssn|aadhaar)\b|sk-[A-Za-z0-9]{8,}|\b\d{12,19}\b|AIza[0-9A-Za-z_-]{20,}")
# spec memory types -> memory.py kinds; actions and outcomes already live in the activity log
TYPES = {"USER_PREFERENCE": "preference", "USER_FACT": "fact", "PROJECT_CONTEXT": "project",
         "WORKFLOW_PATTERN": "workflow", "TASK_STATE": "task", "IMPORTANT_DECISION": "fact"}


def _words(text: str) -> set:
    # shortcut: word overlap, not embeddings; good enough for ~120 short facts. Upgrade to Ollama /api/embed
    # (e.g. nomic-embed-text) if the store grows or misses paraphrases.
    return {w.rstrip("s") for w in re.findall(r"[a-z0-9']+", (text or "").lower()) if w not in _STOP_WORDS}


def score(fact: dict, query: set, tail: set, now: float = None, weights: dict = None) -> float:
    w = {**WEIGHTS, **(weights or {})}
    text = _words(f"{fact.get('key', '')} {fact.get('value', '')}")
    relevance = len(text & query) / max(1, min(len(query), 6))
    task = len(text & tail) / max(1, min(len(tail), 10))
    try:
        age_days = ((now or time.time()) - datetime.fromisoformat(fact["at"]).timestamp()) / 86400
    except (KeyError, ValueError):
        age_days = 365.0
    freshness = math.exp(-math.log(2) * max(age_days, 0) / HALF_LIFE_DAYS)
    importance = float(fact.get("importance", _IMPORTANCE.get(fact.get("kind"), 0.5)))
    confidence = float(fact.get("confidence", 0.9))
    parts = {"relevance": min(relevance, 1.0), "importance": importance, "freshness": freshness,
             "task": min(task, 1.0), "confidence": confidence}
    return sum(w[k] * parts[k] for k in WEIGHTS)


def retrieve(query: str, tail: str = "", k: int = TOP_K, weights: dict = None) -> list:
    """The facts worth knowing for this request: identity always, then the best-scoring others."""
    facts = memory.all_facts()
    q, t, now = _words(query), _words(tail), time.time()
    always = [f for f in facts if f.get("kind") == "identity"]
    rest = sorted((f for f in facts if f.get("kind") != "identity"),
                  key=lambda f: score(f, q, t, now, weights), reverse=True)
    return always + rest[:max(0, k - len(always))]


def context(query: str, tail: str = "", weights: dict = None) -> str:
    facts = retrieve(query, tail, weights=weights)
    if not facts:
        return ""
    lines = [f"- {f.get('key')}: {f.get('value')}" + (f" [status: {f['status']}]" if f.get("status") else "")
             for f in facts]
    return ("What you know about the user that may matter here (from long-term memory; correct it with "
            "remember_fact when they say otherwise):\n" + "\n".join(lines))


# --------------------------------------------------------------------------- write path
EXTRACT_SCHEMA = {"type": "object", "properties": {"memories": {"type": "array", "items": {
    "type": "object", "properties": {
        "type": {"type": "string", "enum": list(TYPES)}, "key": {"type": "string"}, "content": {"type": "string"},
        "confidence": {"type": "number"}, "importance": {"type": "number"}},
    "required": ["type", "key", "content", "confidence", "importance"]}}}, "required": ["memories"]}

EXTRACT_PROMPT = (
    "From this conversation between the user and TRON, list only facts worth remembering for future "
    "conversations: lasting preferences, facts about the user, their projects, how they like things done, "
    "ongoing work, and choices they made when TRON asked (TRON asked which Hindi songs, they said Karan "
    "Aujla: remember 'for Hindi music the user likes Karan Aujla'; they picked a specific episode, browser or "
    "app: remember which). Skip one-off commands (opening apps, volume, timers), small talk, guesses, and anything "
    "secret (passwords, keys, codes). Most conversations have nothing worth keeping: then return an empty "
    "list. key: 2-4 words naming the topic. confidence and importance: 0 to 1.")


def gate(candidate: dict, existing: list) -> bool:
    """Code's say over what the model proposed: confident, short, not secret, not already known."""
    content = str(candidate.get("content", "")).strip()
    if candidate.get("type") not in TYPES or not content or len(content) > 200:
        return False
    if float(candidate.get("confidence", 0)) < MIN_CONFIDENCE or _SECRET.search(content + " " + str(candidate.get("key"))):
        return False
    known = {(f.get("value") or "").strip().lower() for f in existing}
    return content.lower() not in known


def extract(lines: list, chat) -> list:
    """Learns from a finished conversation. lines: its transcript ("YOU: ...", "TRON: ..."); chat(messages,
    format) returns the model's reply text. Returns what was stored. Never raises."""
    said = [line for line in lines if line.startswith("YOU:")]
    if len(" ".join(said).split()) < 6:
        return []   # "what time is it" teaches nothing; don't spend the GPU on it
    try:
        reply = chat([{"role": "system", "content": EXTRACT_PROMPT},
                      {"role": "user", "content": "\n".join(lines[-40:])}], EXTRACT_SCHEMA)
        candidates = json.loads(reply).get("memories", [])
    except Exception:
        return []
    existing, stored = memory.all_facts(), []
    for c in candidates:
        if len(stored) >= MAX_NEW_PER_CONVERSATION or not isinstance(c, dict) or not gate(c, existing):
            continue
        memory.remember(TYPES[c["type"]], str(c.get("key") or c["content"])[:60], c["content"],
                        confidence=round(float(c["confidence"]), 2),
                        importance=round(min(max(float(c.get("importance", 0.5)), 0), 1), 2), source="conversation")
        stored.append(c)
    return stored
