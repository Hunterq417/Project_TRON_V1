# TRON: progress report (11 Nov 2026)

## Where TRON is

A Windows desktop assistant (Python, about 13k lines, 463 automated tests passing). You say "hey tron" or
"hey jarvis", or press Ctrl+Alt+T. Usage from TRON's own logs: 57 conversations, 287 things you said,
262 actions taken, 3 failed actions.

**Built and tested**

- **Brains**
  - Gemini Live (cloud; hears, thinks and speaks).
  - A local brain (Qwen in Ollama, with Parakeet speech recognition and a Windows or Kokoro voice), with
    automatic offline fallback.
- **Three identities on one brain**
  - TRON (main), FRIDAY (mail, calendar, meetings), JARVIS (calls, messages, advice).
  - Each has its own personality, voice and control-panel colour.
  - Switch by voice, with an immediate handover.
- **Safety in code, not left to the model**
  - Every tool has a risk level.
  - Sending mail, inviting people, shutting down and deleting all need your spoken yes.
  - Forgetting needs your own words.
  - Web pages and emails are treated as content, never as instructions.
- **PC control**: apps (including tray apps), windows, volume, brightness, Wi-Fi/Bluetooth, power, timers
  (which survive restarts), dictation, files, clicking and typing on screen, video clips.
- **Media**: Spotify, YouTube Music, and its own Brave window where it can see inside pages (next episode,
  skip, subtitles, full screen), with each action checked.
- **Knows you**
  - Face recognition (ArcFace) and voice recognition (CAM++).
  - A memory with scored retrieval.
  - Routine learning: needs 3 days of evidence and is labelled as an inference.
  - Mood-aware replies.
- **New in this round**
  - Gmail and Google Calendar/Meet, as TRON tools and as one MCP server (`src/google_mcp.py`). You still have
    to connect Google once: see GOOGLE_SETUP.md.
  - Call announcements from Phone Link and WhatsApp ("Boss, Mayukh is calling you on WhatsApp").
  - Hindi and Hinglish replies.
  - Ignores talk that isn't directed at it.

## How TRON compares to similar open-source projects

Compared with PanPenek/JarvisAi, isair/jarvis, llm-guy/jarvis, AlexandreSajus/JARVIS and RehanIlyas-dev/JARVIS:

| | TRON | the others (typical) |
|---|---|---|
| Safety enforced in code (risk table, spoken confirmation, forget guard) | yes | usually prompt-only or none |
| Cloud and local brain, with offline fallback | yes | one or the other |
| Several identities on one shared memory | 3, live handover | 1 |
| Face and voice recognition | yes | rare (one has biometrics) |
| Browser control with checked results | yes (inside page frames) | screenshots or none |
| Desktop UI and control panel | yes, three animated faces and a full panel | web UI or console |
| Tests | 463 automated | few or none |
| Plugin protocol (MCP) | Google server only | isair/jarvis: many MCP connectors |

## 10 places TRON falls short

1. **Gemini response time isn't measured.** Only the local brain logs timings, so there's no way to
   prove speed-ups. Fix: log time from end of speech to first audio for every turn.
2. **The local brain is slow to start.** The first answer after a cold start takes about 22 s while the
   model loads, and around 1.5 s per turn after that. Fix: keep the model loaded while TRON runs, use a
   smaller model for simple commands, and answer clocks, timers and volume without the model at all.
3. **"Is this for me?" relies on the model's judgment** (`not_for_me`). A trained device-directed-speech
   classifier, or using voice ID plus gaze from the camera, would be far more reliable.
4. **No Hindi offline.** Parakeet hears English only and the Windows voices are English. Fix: a
   multilingual speech recogniser (Whisper large-v3-turbo or IndicConformer) and a Hindi voice.
5. **No "hey friday" wake word.** It needs one training run (about an hour), and "hey jarvis" is a
   generic model not tuned to your voice. Recording 20 samples of your own voice would raise accuracy.
6. **Calls are announce-only.** TRON can't answer, decline or reply. It depends on Phone Link and
   Bluetooth (currently off) and on Phone Link's exact wording, which hasn't been tested with a real call yet.
7. **Two separate brain loops.** Gemini and the local brain share tools, safety and memory, but not one
   orchestrator, so behaviour can differ between them (the blueprint's "provider abstraction" is still
   PARTIAL).
8. **No recurring automations or scheduler** ("every weekday at 9, read my mail"), and no offline queue
   for actions that need the internet.
9. **Only one plugin protocol.** TRON exposes a Google MCP server but can't use other MCP servers (Notion,
   Slack, GitHub, Home Assistant). Adding an MCP client would unlock hundreds of integrations.
10. **Logs are thin, and one browser test sometimes fails on timing.** The conversation log stores no
    per-turn timing, mood or misrecognitions, and one test passes and fails at random. Both make
    regressions hard to catch.

## On a "Phone Link clone" (from this round's request)

- **No iPhone app can do this.** iPhones don't run APKs. An iOS app can't see calls or other apps'
  notifications (Apple doesn't allow it), and installing your own app needs a $99/year developer account
  or re-signing every 7 days.
- **The PC side can be built without any phone app.** Phone Link itself works through Bluetooth Low
  Energy: Apple's **ANCS** (notifications, including incoming calls with the caller's name and app) and
  Bluetooth calling profiles. TRON could talk ANCS directly over Windows' Bluetooth.
  - That would remove Phone Link, making TRON one package.
  - It's a substantial piece of work (pairing, bonding, reconnects), and Windows' Bluetooth stack must
    cooperate, so it needs a prototype first.
- **Recommended next phase:** an ANCS prototype that reads notifications, then announcing calls from it.
  Answering and declining calls (Bluetooth calling profiles) would come after.
