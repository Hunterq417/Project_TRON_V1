# Memory/Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** TRON logs every tool call it makes to a local JSON Lines file, folds a "recent activity" digest into its context at the start of each conversation, and can recite or clear that log on request — per `docs/superpowers/specs/2026-08-09-memory-learning-design.md`.

**Architecture:** `memory.py` is a small append-only-log module. `state_manager.py` calls `memory.log_activity()` after every tool dispatch and builds each new conversation's system prompt as `persona_text + "\n\n" + memory.recent_context()`, computed fresh per `trigger()`. Two new tools (`recall_activity`, `forget_recent_activity`) expose the log to voice.

**Tech Stack:** stdlib only (`json`, `pathlib`, `datetime`).

## Global Constraints

- `memory.py`'s log path resolves via `config.app_dir()`, same as `config.json` — must work correctly both frozen and in dev mode (established in sub-project 3).
- No log rotation/pruning/size limits — full history stays on disk (see spec's scope decision).
- `recent_context()` never raises on a corrupted log line — skips it and keeps going.

---

### Task 1: Activity log module

**Files:**
- Create: `memory.py`
- Test: `tests/test_memory.py`

**Interfaces:**
- Consumes: `config.app_dir()`
- Produces: `memory.log_activity(entry: dict) -> None`, `memory.recent_context(n: int = 10) -> str`, `memory.clear() -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_memory.py
import json

import memory


def test_log_activity_appends_json_line(tmp_path, monkeypatch):
    log_path = tmp_path / "activity.jsonl"
    monkeypatch.setattr(memory, "_LOG_PATH", log_path)

    memory.log_activity({"tool": "open_target", "args": {"name": "notepad"}, "result": 'opened "notepad"'})

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["tool"] == "open_target"
    assert "at" in record


def test_log_activity_creates_parent_directory(tmp_path, monkeypatch):
    log_path = tmp_path / "nested" / "activity.jsonl"
    monkeypatch.setattr(memory, "_LOG_PATH", log_path)

    memory.log_activity({"tool": "web_search", "args": {}, "result": "ok"})

    assert log_path.exists()


def test_recent_context_empty_when_no_log(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "_LOG_PATH", tmp_path / "does_not_exist.jsonl")
    assert memory.recent_context() == ""


def test_recent_context_formats_recent_entries(tmp_path, monkeypatch):
    log_path = tmp_path / "activity.jsonl"
    monkeypatch.setattr(memory, "_LOG_PATH", log_path)
    memory.log_activity({"tool": "open_target", "args": {"name": "notepad"}, "result": 'opened "notepad"'})
    memory.log_activity({"tool": "web_search", "args": {"query": "weather"}, "result": 'opened a search for "weather"'})

    context = memory.recent_context()

    assert "open_target" in context
    assert "web_search" in context
    assert "notepad" in context


def test_recent_context_limits_to_n_most_recent(tmp_path, monkeypatch):
    log_path = tmp_path / "activity.jsonl"
    monkeypatch.setattr(memory, "_LOG_PATH", log_path)
    for i in range(5):
        memory.log_activity({"tool": f"tool_{i}", "args": {}, "result": "ok"})

    context = memory.recent_context(n=2)

    assert "tool_3" in context
    assert "tool_4" in context
    assert "tool_0" not in context


def test_recent_context_skips_corrupted_lines(tmp_path, monkeypatch):
    log_path = tmp_path / "activity.jsonl"
    monkeypatch.setattr(memory, "_LOG_PATH", log_path)
    good = json.dumps({"tool": "web_search", "args": {}, "result": "ok", "at": "t"})
    log_path.write_text("not valid json\n" + good + "\n")

    context = memory.recent_context()

    assert "web_search" in context


def test_clear_removes_log_file(tmp_path, monkeypatch):
    log_path = tmp_path / "activity.jsonl"
    monkeypatch.setattr(memory, "_LOG_PATH", log_path)
    memory.log_activity({"tool": "x", "args": {}, "result": "ok"})
    assert log_path.exists()

    memory.clear()

    assert not log_path.exists()


def test_clear_is_a_no_op_when_no_log(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "_LOG_PATH", tmp_path / "does_not_exist.jsonl")
    memory.clear()  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\pytest tests/test_memory.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'memory'`

- [ ] **Step 3: Write `memory.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\pytest tests/test_memory.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add memory.py tests/test_memory.py
git commit -m "Add append-only activity log with recent-context digest"
```

---

### Task 2: Wire logging + context injection into the state machine

**Files:**
- Modify: `state_manager.py`
- Modify: `tests/test_state_manager.py`

**Interfaces:**
- Consumes: `memory.log_activity`, `memory.recent_context`
- Produces: no new public interface — the default session factory's system prompt now includes recent activity, and every tool dispatch is logged

- [ ] **Step 1: Add the new failing tests to `tests/test_state_manager.py`**

```python
# add near the top, alongside the existing imports
import memory


# add these two new tests to the file

def test_default_session_factory_injects_recent_activity_context(monkeypatch):
    monkeypatch.setattr(
        memory, "recent_context", lambda n=10: "Recent activity (most recent last):\n- did stuff"
    )

    captured = {}

    class FakeGeminiLiveSession:
        def __init__(self, api_key, model_name, voice_name, system_instruction, tools=None):
            captured["system_instruction"] = system_instruction

    monkeypatch.setattr(sm, "GeminiLiveSession", FakeGeminiLiveSession)

    machine = sm.TronStateMachine(
        api_key="k", model_name="m", voice_name="Charon", persona_text="be TRON",
        silence_timeout_s=0.1,
    )

    machine._session_factory()

    assert "be TRON" in captured["system_instruction"]
    assert "did stuff" in captured["system_instruction"]
```

And modify the existing `test_tool_call_event_dispatches_and_sends_response` test to also assert logging happened — replace it with:

```python
def test_tool_call_event_dispatches_sends_response_and_logs_activity(monkeypatch):
    import tools

    audio = FakeAudio()
    audio._mic_chunks = []
    states = []

    fake_tool = MagicMock(return_value='opened "notepad"')
    monkeypatch.setitem(tools.TOOL_DISPATCH, "open_target", fake_tool)
    logged = []
    monkeypatch.setattr(memory, "log_activity", lambda entry: logged.append(entry))

    session = FakeSession(events=[
        {"type": "tool_call", "calls": [{"id": "call-1", "name": "open_target", "args": {"name": "notepad"}}]},
        {"type": "turn_complete"},
    ])
    fake_cfg = MagicMock()

    machine = sm.TronStateMachine(
        api_key="k", model_name="m", voice_name="Charon", persona_text="be TRON",
        silence_timeout_s=0.1,
        on_state_change=states.append,
        audio=audio,
        session_factory=lambda: session,
        cfg=fake_cfg,
    )

    machine.trigger()

    fake_tool.assert_called_once_with({"name": "notepad"}, fake_cfg)
    assert session.sent_tool_responses == [("call-1", "open_target", 'opened "notepad"')]
    assert logged == [{"tool": "open_target", "args": {"name": "notepad"}, "result": 'opened "notepad"'}]
    assert sm.State.ACTING in states
    assert machine.state is sm.State.IDLE
```

- [ ] **Step 2: Run tests to verify the new/changed ones fail**

Run: `.venv\Scripts\pytest tests/test_state_manager.py -v`
Expected: FAIL — `test_default_session_factory_injects_recent_activity_context` fails because the current default factory doesn't call `memory.recent_context()`; `test_tool_call_event_dispatches_sends_response_and_logs_activity` fails because `logged` stays empty (no `memory.log_activity` call yet)

- [ ] **Step 3: Modify `state_manager.py`**

```python
# state_manager.py — two changes to the existing file from sub-project 2

# 1. Add the import at the top, alongside `import tools`:
import memory

# 2. Change the default session_factory lambda inside __init__:
        self._session_factory = session_factory or (
            lambda: GeminiLiveSession(
                self._api_key, self._model_name, self._voice_name,
                self._persona_text + "\n\n" + memory.recent_context(),
                tools=tools.TOOL_DECLARATIONS,
            )
        )

# 3. In recv_loop's tool_call branch, log each dispatch result:
                        elif event["type"] == "tool_call":
                            self._set_state(State.ACTING)
                            for call in event["calls"]:
                                handler = tools.TOOL_DISPATCH[call["name"]]
                                result = handler(call["args"], self._cfg)
                                memory.log_activity({
                                    "tool": call["name"], "args": call["args"], "result": result
                                })
                                await session.send_tool_response(call["id"], call["name"], result)
                            touch()
```

Everything else in `state_manager.py` (the `State` enum, `_run_conversation`'s send_loop, error handling) is unchanged from sub-project 2.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest tests/test_state_manager.py -v`
Expected: PASS (5 tests: 3 unchanged + 1 modified + 1 new)

- [ ] **Step 5: Commit**

```bash
git add state_manager.py tests/test_state_manager.py
git commit -m "Log tool activity and inject recent-context digest into persona"
```

---

### Task 3: `recall_activity` / `forget_recent_activity` tools

**Files:**
- Modify: `tools.py`
- Modify: `tests/test_tools.py`

**Interfaces:**
- Consumes: `memory.recent_context`, `memory.clear`
- Produces: `TOOL_DISPATCH["recall_activity"]`, `TOOL_DISPATCH["forget_recent_activity"]`, matching declarations in `TOOL_DECLARATIONS`

- [ ] **Step 1: Add the failing tests to `tests/test_tools.py`**

```python
# add near the top with the other imports
# (tools.py already imports app_index, email_client, media_control this way —
# add `import memory` there too in Step 3 below)


def test_recall_activity_returns_context(monkeypatch):
    monkeypatch.setattr(tools.memory, "recent_context", lambda n=10: "Recent activity:\n- did stuff")

    result = tools.TOOL_DISPATCH["recall_activity"]({}, None)

    assert "did stuff" in result


def test_recall_activity_handles_empty_log(monkeypatch):
    monkeypatch.setattr(tools.memory, "recent_context", lambda n=10: "")

    result = tools.TOOL_DISPATCH["recall_activity"]({}, None)

    assert "nothing logged" in result.lower()


def test_forget_recent_activity_clears_log(monkeypatch):
    fake_clear = MagicMock()
    monkeypatch.setattr(tools.memory, "clear", fake_clear)

    result = tools.TOOL_DISPATCH["forget_recent_activity"]({}, None)

    fake_clear.assert_called_once()
    assert "cleared" in result.lower()
```

(`test_every_declaration_has_a_matching_dispatch_entry`, already in the file, automatically covers the two new entries once they're added — no change needed there.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\pytest tests/test_tools.py -v`
Expected: FAIL with `AttributeError: module 'tools' has no attribute 'memory'` (or `KeyError` on the new dispatch keys)

- [ ] **Step 3: Modify `tools.py`**

```python
# tools.py — add to the imports at the top:
import memory

# add these two functions alongside the other _xxx handlers:
def _recall_activity(args, cfg):
    context = memory.recent_context()
    if not context:
        return "nothing logged yet, sir"
    return context


def _forget_recent_activity(args, cfg):
    memory.clear()
    return "recent activity log cleared, sir"

# add to TOOL_DISPATCH:
    "recall_activity": _recall_activity,
    "forget_recent_activity": _forget_recent_activity,

# add to TOOL_DECLARATIONS:
    {
        "name": "recall_activity",
        "description": (
            "Get a summary of recent actions TRON has taken (apps opened, searches, "
            "emails, etc.) to answer questions like 'what have you been up to'."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "forget_recent_activity",
        "description": "Clear TRON's recent activity log. Use when the user explicitly asks to forget or clear recent activity.",
        "parameters": {"type": "object", "properties": {}},
    },
```

- [ ] **Step 4: Run the full test suite**

Run: `.venv\Scripts\pytest -v`
Expected: PASS — all tests across every sub-project so far.

- [ ] **Step 5: Commit**

```bash
git add tools.py tests/test_tools.py
git commit -m "Add recall_activity and forget_recent_activity tools"
```
