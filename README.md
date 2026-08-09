# TRON

A personal voice assistant. All 6 sub-projects complete — see
`docs/superpowers/specs/` for the full design history and roadmap.

## Running from source (development)

1. Python 3.13 (this machine only had 3.13 installed; the original spec
   targeted 3.11/3.12 but nothing here needs an older version).
2. `python -m venv .venv` then `.venv\Scripts\pip install -r requirements.txt`
3. Get a Gemini API key from https://aistudio.google.com/apikey
4. `copy config.example.json config.json` and fill in `gemini_api_key`
5. (Optional, for email) Fill in `smtp_host`/`smtp_port`/`smtp_user`/
   `smtp_app_password` in `config.json`. For Gmail: enable 2FA on the
   account, then generate an "app password" at
   https://myaccount.google.com/apppasswords — your normal password will
   not work over SMTP.
6. `.venv\Scripts\python main.py`
7. Press `Ctrl+Alt+T` (configurable in `config.json`) to talk to TRON. Quit
   from the system tray icon.

By default TRON listens for a hotkey, not a spoken wake word — training a
real "hey tron" model is a separate offline step. See
[Upgrading to the "hey tron" wake word](#upgrading-to-the-hey-tron-wake-word) below.

## Running the packaged .exe

Build `TRON.exe` per `docs/build_exe.md`, or if you already have one: just
double-click it. First launch opens a small setup window asking for your
Gemini API key (and optionally email settings, camera/screen access) and
offers to start TRON automatically on login — no manual `config.json`
editing needed. Every launch after that goes straight to the tray icon.

If TRON crashes, check `tron_error.log` next to the exe for a traceback.

## Orb HUD

A centered particle sphere pops onto the screen the moment you talk to TRON
and disappears again once the conversation ends — TRON runs quietly in the
tray the rest of the time. It uses the same color language as the tray icon
(table below), plus a real-time pulse driven by the actual loudness of
TRON's voice as it speaks. Toggle it manually anytime from the tray menu's
"Show/Hide Orb."

The orb is centered on your primary monitor and tries to pin itself to the
desktop layer — behind every application window, like a live wallpaper —
using the same undocumented Windows trick apps like Wallpaper Engine use.
This can fail on some Windows builds/configurations; when it does, the orb
just falls back to being a normal (not-always-on-top) window instead of
erroring.

**On this machine specifically, it doesn't pin** — diagnosed directly against
this real desktop (not simulated): the classic lookup (find the WorkerW
sibling of the window hosting the desktop icons) and the fallback (the
WorkerW right after Progman) both come back empty here, most likely because
this Windows build's icon host is `SHELLDLL_DefView` sitting straight under
`Progman` with no freshly-spawned `WorkerW` at all. The orb still works —
centered, color-coded, audio-reactive — it just won't be *behind* other
windows on this PC; it'll behave like a normal window instead. This may
differ on other machines/Windows builds. `pin_to_desktop()` never raises
either way, so this degrades quietly rather than breaking anything.

## Tray icon / orb status colors

| Color | State | Meaning |
|---|---|---|
| White/gray | Idle | Waiting for the hotkey |
| Blue | Listening | Mic is capturing your speech |
| Amber | Thinking | Waiting on Gemini's response |
| Green | Speaking | TRON's reply is playing |
| Purple | Acting | A tool (open app, media control, email, search, vision, scan) is running |
| Red | Error | Network/API failure this turn — press the hotkey again to retry |

## What TRON can do now

- Open apps, files, photos, videos, or games by name ("open notepad", "open that dune photo")
- Control media playback: play/pause, next/previous track, seek forward/backward (best-effort, up to about a minute)
- Search the web
- Draft and — after you confirm out loud — send email
- Remember recent activity across conversations, recite it ("what have you been up to") or clear it on request
- Look at your screen or through your camera and describe what it sees (off by default — see Privacy below)
- Run a Windows Defender malware scan and report whether it's finished

## Privacy

Camera and screen access are **off by default**. They're not just discouraged
by instructions — the `look_at_screen`/`look_via_camera` tools are not even
declared to Gemini unless you check "Enable camera access"/"Enable screen
reading" in setup (or set `camera_enabled`/`screen_enabled` to `true` in
`config.json`), so the model has no tool by that name to call until you
opt in. No frame is ever saved to disk — captured images go straight into
the live conversation and are discarded; only the fact that a capture
happened is logged. Every tool call TRON makes (including vision captures
and scans) is visible by asking "what have you been up to."

## Tests

`.venv\Scripts\pytest`

## Upgrading to the "hey tron" wake word

`OpenWakeWordTrigger` (continuous listening, no hotkey) is fully built and
tested — it just needs a trained `models/tron.onnx` file, which is a
separate offline training step (Colab notebook, not application code). See
`docs/train_wakeword.md` for the exact steps and how to switch
`config.json`'s `wake_mode` over once you have it.
