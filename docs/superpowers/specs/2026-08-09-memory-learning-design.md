# Memory/Learning — Design Spec

**Sub-project 4 of 6** in the TRON program. Gives TRON continuity across conversations: it remembers what it's done for you recently and can tell you or forget on request.

## Goal

Every tool call TRON makes gets logged locally with a timestamp. At the start of each new conversation, a short digest of recent activity is folded into TRON's context, so it can say things like "you asked me to open Chrome twice this morning, sir" without being asked. You can also ask "what have you been up to" or "forget recent activity" directly.

## Scope decision: logs TRON's own actions, not passive activity monitoring

"Learning from your actions" could mean two different things: (a) TRON remembering what *it* did for you, or (b) TRON continuously watching what *you* do system-wide (focused app, browsing, etc.) even when it wasn't invoked. This sub-project is (a) only — logging tool-call events already flowing through `state_manager.py`. Passive/continuous observation is sub-project 6's territory (perception) and carries far more privacy weight; conflating the two here would smuggle scope into what should be a deliberate, separately-designed decision.

No summarization LLM call is used. Structured tool-call events (name, args, result, timestamp) are logged directly and formatted into text — an extra Gemini round-trip to summarize freeform conversation content would add cost and complexity for a personal-scale log that's already small and structured.

## Components

| Component | Responsibility | Notes |
|---|---|---|
| `memory.py` | `log_activity(entry: dict) -> None` appends one JSON line to `memory/activity.jsonl` (path via `config.app_dir()`, so it lives correctly whether frozen or dev-mode). `recent_context(n=10) -> str` reads the last `n` entries and formats them into a short readable block. `clear() -> None` truncates the log. | Stdlib only (`json`, `pathlib`, `datetime`). No pruning/rotation for old entries — full history stays on disk; revisit if the file ever becomes a real problem (unlikely at personal single-user scale). |
| `state_manager.py` (modified) | After each tool dispatch in `recv_loop`, calls `memory.log_activity(...)`. The session factory now builds `persona_text + "\n\n" + memory.recent_context()` fresh on every `trigger()` call, not once at startup. | |
| `tools.py` (modified) | Two new tools: `recall_activity` (returns `memory.recent_context()` for Gemini to read back) and `forget_recent_activity` (calls `memory.clear()`, returns confirmation text). | Both follow the existing `(args, cfg) -> str` dispatch signature. |

## Data flow

1. A tool call completes in `recv_loop` (unchanged from sub-project 2) → its `{tool, args, result}` plus a timestamp is appended to `activity.jsonl`.
2. Next time `trigger()` fires (a new conversation), the session factory reads `memory.recent_context()` and prepends it to the static persona text before opening the Gemini Live session.
3. If the user asks "what have you been up to," Gemini calls `recall_activity`, gets the same formatted text back as a tool result, and reads it aloud.
4. If the user asks to forget, Gemini calls `forget_recent_activity`, which truncates the log file; the next conversation's context digest is empty again.

## Error handling

| Condition | Behavior |
|---|---|
| `memory/` directory or `activity.jsonl` doesn't exist yet | Created on first `log_activity()` call — no setup step required. |
| Log file corrupted (unreadable line) | `recent_context()` skips unparseable lines rather than crashing the whole read. |
| `recall_activity` called with an empty log | Returns a clear "nothing logged yet, sir" string rather than an empty/confusing block. |

## Testing

`memory.py`'s functions are pure file I/O against a `tmp_path`-based log file — directly testable, no mocking needed beyond controlling the path. `state_manager.py`'s injection of `recent_context()` into the persona is tested by asserting the session factory's constructed text contains the digest (using a fake `memory.recent_context` via monkeypatch, consistent with how `tools.TOOL_DISPATCH` was tested in sub-project 2). The two new tools are tested the same way the existing eight are in `tests/test_tools.py`.

## Explicitly out of scope

- Passive/continuous system-wide activity monitoring (sub-project 6)
- Conversation-content summarization via an LLM call
- Log rotation, pruning, or size limits
- Any cross-device or cloud sync of memory (stays local, per the existing "runs locally" design throughout this program)
