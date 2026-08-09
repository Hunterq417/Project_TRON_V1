# Voice Core — Design Spec

**Sub-project 1 of 6** in the TRON personal-assistant program (see "Program roadmap" below for the other five). This spec covers only the real-time talk-back loop — no automation, no memory, no camera/screen, no installer, no 3D UI.

## Goal

A working, local-dev-mode program that you can run (`python main.py`), say **"TRON"** to, and have a real-time spoken conversation with — including being able to talk over it mid-response (barge-in). Success criteria: round-trip latency from end-of-your-sentence to start-of-response feels conversational (sub-1.5s), false wake-word triggers are rare enough not to be annoying, and the process survives a dropped network connection without crashing.

## Persona

- Wake word / assistant name: **"TRON"**
- Address form: refers to the user as **"sir"**
- Tone: formal, economical, dry-witted — a butler-AI register (JARVIS-style), not a chatty consumer assistant. Short responses by default; it elaborates only when asked.
- This persona lives entirely in the Gemini Live system prompt (`core/persona.txt` or equivalent) — not hardcoded into application logic — so it can be edited without touching code.

## Architecture — session lifecycle

State machine: `idle → listening-for-wake → active-conversation → idle`.

- **idle / listening-for-wake**: the wake-word engine runs continuously and entirely locally. No audio leaves the machine in this state.
- **On "TRON" detected** → open a Gemini Live session, begin streaming mic audio into it.
- **active-conversation**: session stays open across follow-up turns (no reconnect per sentence). A rolling silence timeout (~30–60s, tunable) returns to idle and closes the session.
- **Barge-in**: while TRON is speaking, if the user starts talking, playback is cut and the new input is forwarded immediately — handled by Gemini Live's native interruption support, not built by hand.

Rationale for a timeout-bounded session (vs. always-open or open-per-utterance): an always-open session wastes connection/cost sitting idle all day; reconnecting per utterance adds session-start latency (~200–500ms) to every single turn, which would make quick follow-ups feel sluggish. A bounded window gets snappy follow-ups without an idle-all-day connection.

## Components

| Component | Responsibility | Notes |
|---|---|---|
| Wake-word detector | Continuous local listening for "TRON" | openWakeWord. No pretrained model exists for this word — requires training a small custom model on a few dozen sample recordings of the user saying "TRON" as a one-time setup step. |
| Audio I/O | Duplex mic capture / speaker playback | `sounddevice` |
| Gemini Live client | STT + reasoning + TTS + barge-in, server-side | `google-genai` SDK |
| Session/state manager | Drives the idle/listening/active state machine above | |
| Tray icon | Shows idle / listening / thinking / speaking status | `pystray`. No waveform HUD in this phase — the 3D UI is a separate later sub-project layered on top once this loop works. |
| Config | API key, wake-word model path, persona prompt path | Local file, git-ignored. API key never hardcoded. |

Stack: **Python 3.11/3.12, Windows** — matches both reference projects researched (Mark-L, jarvis-ai-assistant) and keeps PyInstaller available for the eventual installer sub-project.

## Data flow

1. Mic audio streams continuously into the wake-word detector (local, offline).
2. On "TRON" detected, state manager opens (or reuses, if still within the active window) a Gemini Live session and starts forwarding raw mic audio to it.
3. Gemini Live streams back audio (and optionally text) as it generates a response; audio is played through the speaker as it arrives (streamed, not buffered-then-played).
4. If the user speaks while TRON is speaking, Gemini Live's barge-in cuts the current playback and starts processing the new input.
5. After the configured silence window with no new speech, the session closes and the state manager returns to `listening-for-wake`.

## Error handling

| Condition | Behavior |
|---|---|
| No network / Gemini unreachable | Tray icon shows an error state; wake-word detection keeps running locally (unaffected, since it's offline); reconnect attempts use exponential backoff. |
| API quota/billing error | A short local (non-API) error tone or canned phrase plays instead of hanging silently. |
| Mic permission denied at OS level | Detected at startup; tray shows a clear error state rather than crashing or silently listening to nothing. |
| Wake-word false positive | Auto-times out back to idle harmlessly — nothing is sent to Gemini until real speech follows the trigger, so a false trigger costs nothing but a moment of the tray icon lighting up. |

## Testing

This is a live/interactive voice loop — a conventional automated test suite doesn't fit the core interaction. One smoke check: a script that feeds a canned wake-word audio clip and a canned spoken question through the pipeline in a dry-run mode (mocked or sandboxed Gemini Live call) and asserts a non-empty response comes back. This exists to catch integration breaks (e.g. a bad SDK upgrade, a broken state transition) without requiring a human to talk to it after every code change — it is not a substitute for actually talking to it before calling a change done.

## Explicitly out of scope for this sub-project

- Automation / tool-calling (opening apps, media control, email, etc.)
- Camera or screen perception
- Cross-session memory / learning from user behavior
- The 3D futuristic UI (tray icon only, this phase)
- Auto-start-on-boot, background service, or installer packaging (`python main.py` from a terminal is the shipped form for now)
- Antivirus/malware scanning

## Program roadmap (context, not part of this spec)

Voice Core is the first of six sub-projects identified during scoping, in recommended build order:

1. **Voice Core** (this spec) — real-time talk-back loop
2. **Automation/tools layer** — app launching, media control, email, file ops, web search, routed through Gemini Live's tool-calling
3. **Packaging/shell** — installable EXE (PyInstaller), background service, tray autostart, wraps the above into something that "feels installed"
4. **Memory/learning layer** — persistent store of preferences, session history, and observed user activity; design needed before anything is allowed to write to it
5. **3D futuristic UI** — the JARVIS-style HUD, layered on top of the tray-icon shell once the underlying loop is solid
6. **Perception (camera/screen) + security scanning** — deliberately last: highest privacy/security surface, wants its own consent model (per-capability permission, visible activity log) rather than a blanket always-on grant, and benefits from every other layer already being trustworthy first.

Each sub-project gets its own spec → plan → implementation cycle when we get to it.
