# Automation/Tools — Design Spec

**Sub-project 2 of 6** in the TRON personal-assistant program (see Voice Core's spec for the full roadmap). This spec gives TRON "hands": launching apps/files, controlling media playback, web search, and email — routed through Gemini Live's native tool-calling, on top of the Voice Core built in sub-project 1.

## Goal

While talking to TRON, you can say things like "open Notepad," "skip forward a bit," "look up the weather," or "email Alex that I'm running late," and it actually does them — asking for confirmation only where an action can't be undone (sending an email). Success criteria: the five tools below work reliably from natural phrasing, unresolvable requests fail with a spoken explanation rather than a crash, and email never sends without an explicit spoken "yes" first.

## Architecture — tool-calling loop

Gemini Live supports function-calling natively: tool schemas are declared on session connect, and mid-conversation the model can emit a tool-call event instead of (or interleaved with) audio. `GeminiLiveSession.receive()` changes from yielding raw audio bytes to yielding **tagged events**:

- `{"type": "audio", "data": bytes}`
- `{"type": "tool_call", "calls": [{"id": str, "name": str, "args": dict}, ...]}`
- `{"type": "turn_complete"}`

A new `send_tool_response(call_id, name, result)` method sends a tool's result back into the same live session so Gemini can narrate the outcome ("Done, sir — Notepad's open") in the same turn.

`state_manager.py`'s `recv_loop` handles all three event types: audio drives `SPEAKING` (unchanged from Voice Core), a `tool_call` event looks the name up in a flat dispatch table, runs it, and reports the result back — a `turn_complete` with no pending audio drives `THINKING` (unchanged).

**New tray state: `ACTING`** (purple) — shown while a tool is actually executing, distinct from `THINKING` (waiting on Gemini to decide something). This is the extension point the Voice Core plan deliberately left open in `tray_ui._COLORS`.

## Components

| Component | Responsibility | Notes |
|---|---|---|
| `tools.py` | `TOOL_DECLARATIONS` (schemas Gemini sees) + `TOOL_DISPATCH` (name → function). Also hosts `web_search` directly (one-liner). | Flat registry, no plugin framework — five tools don't justify one. |
| `app_index.py` | Scans Start Menu shortcuts + Pictures/Videos/Desktop/Documents for a name→path index; fuzzy-matches a spoken name via stdlib `difflib`; launches via `os.startfile()`. | No new dependency. Index built once per process (lazy, cached). |
| `media_control.py` | Play/pause/next/previous via OS media keys (`keyboard.send`, already a dependency). Seek forward/backward simulates arrow-key presses in the currently focused window. | Seek is capped at ~60s of nudging (roughly 12 keypresses); beyond that it returns an explanation instead of hammering keys, since there is no OS-level "seek by N minutes" API this can hook. |
| `email_client.py` | `draft_email(to, subject, body)` formats text for Gemini to read back (no side effect). `send_email(to, subject, body)` actually sends via stdlib `smtplib`. | Confirm-before-send is a **persona-prompt rule**, not app-side state machinery: TRON is instructed to always call `draft_email` first, read it back verbatim, and wait for explicit spoken confirmation before ever calling `send_email`. Two separate tools make this a real checkpoint. |

Stack addition: none beyond stdlib (`os`, `pathlib`, `difflib`, `smtplib`, `webbrowser`, `urllib.parse`) — `keyboard` is already a Voice Core dependency.

## Data flow

1. Gemini decides mid-conversation to call a tool; `session.receive()` yields a `tool_call` event.
2. `recv_loop` sets state to `ACTING`, looks up the function in `TOOL_DISPATCH`, calls it with the model-supplied args.
3. The function returns a plain string result (success message or a clear failure explanation — never raises for expected failure modes like "app not found").
4. `session.send_tool_response(call_id, name, result)` sends it back into the live session.
5. Gemini narrates the outcome as normal spoken audio; state returns to `SPEAKING`/`THINKING` per the existing Voice Core flow.

## Error handling

| Condition | Behavior |
|---|---|
| `open_target` can't fuzzy-match anything close enough | Returns "couldn't find anything called X, sir" — Gemini relays it, asks for clarification if needed. |
| `media_control` seek requested beyond the ~60s cap | Returns an explanation of the limitation instead of spamming keypresses. |
| No focused window when seeking, or media keys have no effect | Tool still returns a result string (can't reliably detect silent failure at the OS level) — documented as a known limitation, not solved here. |
| `send_email` SMTP failure (bad credentials, network) | Returns the SMTP error message as a plain string; Gemini relays it as speech, process doesn't crash. |
| Gemini calls `send_email` without a prior `draft_email` + confirmation in the same turn sequence | Not enforced in code — this is a persona-prompt instruction, not a hard guarantee. Documented as a known limitation (see below). |

## Testing

Each tool function is pure enough to unit test directly (given fuzzy-matchable fake data for `app_index`, a fake/mocked SMTP connection for `email_client`, and a mocked `keyboard`/`webbrowser` call for the rest) — no live Gemini connection needed. `state_manager`'s tool-call dispatch gets a test using a fake `GeminiLiveSession` that yields a `tool_call` event and asserting `send_tool_response` was called with the dispatched function's result and state passed through `ACTING`.

## Explicitly out of scope for this sub-project

- Virus/malware scanning (stays in sub-project 6, deliberately last)
- File operations beyond opening (delete/move/rename)
- Enforcing the draft-before-send rule in code (relies on the persona prompt — a real gap, noted above, acceptable for a personal single-user tool but worth hardening later if this is ever multi-user or higher-stakes)
- The 3D UI (still tray-icon only)
- Any tool not in the five above (calendar, smart home, etc. — later sub-projects per the original roadmap discussion, not yet scheduled)
