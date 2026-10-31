# TRON

A voice assistant for Windows that lives on your desktop and controls your PC. Say **"hey tron"** and talk:
"open Spotify and play Blinding Lights", "set a timer for ten minutes", "play the next episode", "tell me
when the Valorant update finishes", "who's here?".

It can run **entirely on your PC** (no internet, no API key) or use **Google Gemini Live** for its brain.

## What it does

- **Hears, thinks and speaks.** Local mode: Parakeet (speech to text), Qwen3.5 in Ollama (the brain), a
  Windows or Kokoro voice. Gemini mode: Gemini Live does all three, and falls back to local when offline.
- **Decides carefully.** A small decision engine around the model: the right tool for what you mean,
  results verified before it says something worked, a spoken "yes" before shutdown / restart / sleep /
  sending email, and nothing forgotten unless you say "forget".
- **Controls the PC.** Apps and windows (including apps in the tray), volume, brightness, Wi-Fi, Bluetooth,
  dark mode, lock, timers, dictation, files, clicking and typing on screen, clipping videos.
- **Music.** Spotify by default; YouTube Music and YouTube in the TRON browser.
- **The TRON browser.** Its own Brave window it can see inside: next/previous episode, skip, pause, volume,
  subtitles, full screen, verified on the page itself. See [docs/BROWSER_INTELLIGENCE.md](docs/BROWSER_INTELLIGENCE.md).
- **Watches for you.** "Tell me when the download finishes": it checks the window and announces it.
- **Knows who you are.** Face recognition (ArcFace) and voice recognition (CAM++), learned from the control
  panel. Remembers your preferences and learns from conversations.
- **On screen.** Three faces to choose from: Halo Ring, Aurora Orb, Dust Orb. A control panel with stats,
  conversations, memory and skills, people, settings and keys.

## Requirements

- Windows 10 or 11, a microphone. A webcam for face recognition.
- [Python 3.13](https://www.python.org/downloads/) (3.11+ should work).
- [Brave](https://brave.com/) for the TRON browser and the Dust Orb (optional otherwise).
- For Local mode: [Ollama](https://ollama.com/download) and about 4 GB of free GPU memory (or a patient CPU).
- For Gemini mode: a free API key from [Google AI Studio](https://aistudio.google.com/apikey).

## Install

```powershell
git clone https://github.com/Hunterq417/Project_TRON_V1.git
cd Project_TRON_V1
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

### Download the offline models

Models are not in this repository (about 1.3 GB). One command fetches them into `models\`:

```powershell
.venv\Scripts\python setup_models.py
```

| Model | For | Licence |
|---|---|---|
| NVIDIA Parakeet TDT 0.6B v2 (ONNX, int8) | hearing in Local mode, dictation | CC-BY-4.0 |
| Kokoro-82M (ONNX) | the Kokoro voices | Apache-2.0 |
| InsightFace buffalo_l: SCRFD + ArcFace R50 | face recognition | **non-commercial use only** |
| 3D-Speaker CAM++ | voice recognition | Apache-2.0 |
| openWakeWord front-end | "hey tron" | Apache-2.0 |

`models\tron.onnx`, TRON's own "hey tron" model, is included. Skip what you don't need, e.g.
`setup_models.py --skip faces voices`.

### Download the local brain

Install Ollama, then:

```powershell
ollama pull qwen3.5:4b
```

Any model you pull can be chosen later in Settings > Local model. `qwen3.5:4b` was the best fit tested on an
RTX 4070 laptop (right on 21 of 22 test commands, about 1.5 s per answer).

### Configure

```powershell
copy config.example.json config.json
```

Then edit `config.json`, or just start TRON: if `config.json` is missing, a setup window asks for the few
things it needs. Leave the Gemini key empty to run fully locally. Everything else can be changed later in the
control panel (tray icon > Control panel), which saves to `config.json`.

Main settings: `brain` (`local` or `gemini`), `local_model`, `local_voice` (`david`, `zira`, `hazel`, or a
Kokoro voice such as `am_michael`), `wake_mode` (`openwakeword` or `hotkey`), `hotkey`, `mic_device`,
`speaker_device` (empty follows Windows), `ui_model` (`halo-ring`, `aurora-orb`, `dust-orb`),
`camera_enabled`, `screen_enabled`.

### Run

```powershell
.venv\Scripts\python src\main.py
```

TRON starts in the tray. Say "hey tron" or press `Ctrl+Alt+T`. Useful flags: `--selftest` (checks the
models, voice and devices and writes `selftest.log`), `--panel` (only the control panel), `--list-mics`.

For the TRON browser, say "open the TRON browser" (or use the button on the control panel's Home page) and
watch videos there. It uses its own Brave profile; your normal Brave is untouched.

## Build a standalone TRON.exe

```powershell
.venv\Scripts\pip install -r requirements-build.txt
.venv\Scripts\pyinstaller TRON.spec --noconfirm
```

This makes `dist\TRON.exe`. Put `config.json`, `persona.txt` and the `models` folder next to it.

## Tests

```powershell
.venv\Scripts\pytest
```

About 440 tests. The browser tests run against local pages in a headless Brave and are skipped if Brave
isn't installed; a few model tests are skipped until `setup_models.py` has run.

## Project layout

```
src/            the code (entry point: src/main.py)
  state_manager.py   conversations: wake word -> brain -> tools -> voice
  local_brain.py     the local decision engine (Ollama), decision.py, tool_registry.py, memory_service.py
  gemini_live_client.py   Gemini Live
  tools.py           every tool TRON can use; brain.py: safety rules
  browser_*.py       the TRON browser; faces.py, voices.py: who's there
  control_panel.py, orb_ui.py, dust_orb.py   the windows on screen
  assets/dust_orb/   the Dust Orb (Ship Notes dust-orb v2, MIT)
tests/          pytest suite
docs/           BROWSER_INTELLIGENCE.md
setup_models.py downloads the offline models
TRON.spec       PyInstaller build
persona.txt     TRON's personality
```

## Privacy

Everything TRON learns stays in its folder: `memory\` (facts, face and voice fingerprints, never photos or
recordings), `logs\` (conversations) and `config.json` (keys). None of these are in git. In Local mode
nothing leaves the PC. In Gemini mode your voice during a conversation goes to Google, and a screenshot or
camera frame only when you ask TRON to look and allow it in Settings. Enrol other people's faces and voices
only with their agreement.

## Credits

Parakeet (NVIDIA), Qwen (Alibaba), Ollama, Kokoro, InsightFace, 3D-Speaker and sherpa-onnx, openWakeWord,
Playwright, CustomTkinter, the Ship Notes Dust Orb and three.js. Each keeps its own licence.
