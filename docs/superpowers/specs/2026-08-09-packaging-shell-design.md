# Packaging/Shell — Design Spec

**Sub-project 3 of 6** in the TRON personal-assistant program (see Voice Core's spec for the full roadmap). This spec turns TRON from "a repo you run with `python main.py`" into a portable `.exe` you can put anywhere, that sets itself up on first launch and starts automatically on login.

## Goal

Build `TRON.exe`, hand it to a fresh machine (or a fresh folder) with nothing else, and:
1. First launch opens a small window asking for the Gemini API key (and optionally email settings), writes `config.json` next to the `.exe`, and offers to start automatically on login.
2. Every launch after that goes straight to the tray icon, exactly like the dev-mode `python main.py` experience from sub-projects 1–2.
3. A crash produces a `tron_error.log` next to the `.exe`, not silent disappearance.

## Scope decision: "background service" means tray + autostart, not a Windows Service

The original roadmap line said "background service." A true Windows Service (SYSTEM-level, survives without a logged-in user, installed via `sc.exe`/`pywin32`) is real extra complexity — elevated install, service account permissions, a different failure-debugging story — that a personal, single-user, run-when-I'm-logged-in assistant doesn't need. Registry-Run-key autostart + a tray icon achieves the actual goal ("it runs all the time for me") without any of that. If TRON is ever meant to run for multiple users or without anyone logged in, revisit this.

## The core packaging problem: path resolution when frozen

PyInstaller's `--onefile` mode extracts the bundle to a temp directory at every launch and runs the code from there. Inside that frozen process, `Path(__file__).parent` resolves to the **temp extraction folder**, not wherever the actual `.exe` sits. Every other component built so far (`config.py`'s `CONFIG_PATH`, `main.py`'s `Path(cfg.persona_path)`) assumes `__file__`-relative or cwd-relative paths — both silently wrong once frozen, meaning `config.json` would get written into a folder that's deleted the moment the process exits, and the wizard would ask for the API key on every single launch.

**Fix:** `config.py` gains `app_dir()`:
```python
def app_dir() -> Path:
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
```
`CONFIG_PATH` and any relative path from config (`persona_path`, `wakeword_model_path`) resolve through `app_dir()`, not `__file__` or cwd. In dev mode (`python main.py`), `sys.frozen` is unset, so behavior is unchanged from sub-projects 1–2.

## Components

| Component | Responsibility | Notes |
|---|---|---|
| `config.py` (modified) | Adds `app_dir()` and `resolve_path(path_str)`; `CONFIG_PATH` now built from `app_dir()`. | No new dependency. |
| `setup_wizard.py` | tkinter window (stdlib) shown when `config.json` is missing: API key, hotkey, optional SMTP fields, "start on login" checkbox (checked by default). Writes `config.json` on submit. | GUI wiring is thin; the form-values → config-dict conversion is a separate, unit-tested pure function. |
| `autostart.py` | `enable()`, `disable()`, `is_enabled()` against `HKEY_CURRENT_USER\...\Run` via stdlib `winreg`. | No admin rights required; user can also remove the entry by hand via `regedit` or `msconfig` if something goes wrong. |
| `main.py` (modified) | Runs the setup wizard first if `config.json` is absent; wraps the whole run in try/except logging to `tron_error.log` next to the exe. | Necessary because `--noconsole` builds have no console to show a traceback in. |
| `docs/build_exe.md` | The actual `pyinstaller` command and known `--collect-all` needs for `sounddevice`/`pystray`/`keyboard`, plus a manual smoke-test checklist for the built exe. | PyInstaller's data-collection requirements shift between versions — documented as "verify against your installed PyInstaller version," same caveat style as the Gemini SDK notes in earlier specs. |
| `requirements-build.txt` | Just `pyinstaller` — kept separate from `requirements.txt` since it's a build-time-only tool, not a runtime dependency. | |

## Data flow

1. `main.py` starts, checks `config.CONFIG_PATH.exists()`.
2. If missing: `setup_wizard.run_first_time_setup()` blocks (tkinter mainloop) until the user submits, writes `config.json` via `app_dir()`, calls `autostart.enable()` if the checkbox was checked.
3. `load_config()` proceeds exactly as in sub-projects 1–2, except `persona_path`/`wakeword_model_path` now resolve through `config.resolve_path()` instead of a bare relative path.
4. The rest of the run (voice loop, tools, tray) is unchanged from sub-project 2.
5. Any unhandled exception anywhere in the run is caught at the top of `main()`, written with a full traceback to `app_dir() / "tron_error.log"`, and the process exits instead of hanging invisibly.

## Error handling

| Condition | Behavior |
|---|---|
| `config.json` missing | Setup wizard runs instead of crashing on `FileNotFoundError`. |
| API key left blank in the wizard | Save button stays disabled / shows an inline error; cannot submit without it. |
| Autostart registry write fails (e.g. permissions oddity) | Caught and surfaced as a wizard warning, not a crash — TRON still runs manually. |
| Any unhandled exception during a run | Logged with traceback to `tron_error.log`; process exits cleanly rather than hanging with an invisible window. |
| Unsigned `.exe` triggers Windows SmartScreen on first run | Documented in `docs/build_exe.md`, not solved — code signing is out of scope (needs a paid certificate). |

## Testing

`config.app_dir()`/`resolve_path()` are pure functions, tested directly by monkeypatching `sys.frozen`/`sys.executable`. `autostart.py`'s registry calls are tested via a monkeypatched `winreg` (no real registry writes in tests). `setup_wizard.py`'s pure `build_config_dict(form_values)` is tested directly; the tkinter window itself is not — same pattern as `tray_ui.py` in sub-project 1, where the GUI shell is thin and untested but the logic behind it is. No test builds the actual `.exe` (that's an integration step done manually per `docs/build_exe.md`, not part of the automated suite).

## Explicitly out of scope

- A real Windows Service (see scope decision above)
- An MSI/Inno-Setup installer, Start Menu entries, uninstaller
- Code signing / SmartScreen suppression
- Auto-update
