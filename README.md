# TRON

A personal voice assistant. Sub-project 2/6 (Automation/Tools) of the larger
TRON program — see `docs/superpowers/specs/` for the full design and roadmap.

## Setup

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

## Tray icon status colors

| Color | State | Meaning |
|---|---|---|
| White/gray | Idle | Waiting for the hotkey |
| Blue | Listening | Mic is capturing your speech |
| Amber | Thinking | Waiting on Gemini's response |
| Green | Speaking | TRON's reply is playing |
| Purple | Acting | A tool (open app, media control, email, search) is running |
| Red | Error | Network/API failure this turn — press the hotkey again to retry |

## What TRON can do now

- Open apps, files, photos, videos, or games by name ("open notepad", "open that dune photo")
- Control media playback: play/pause, next/previous track, seek forward/backward (best-effort, up to about a minute)
- Search the web
- Draft and — after you confirm out loud — send email

## Tests

`.venv\Scripts\pytest`

## Upgrading to a real "TRON" wake word (no hotkey)

See `docs/train_wakeword.md`.
