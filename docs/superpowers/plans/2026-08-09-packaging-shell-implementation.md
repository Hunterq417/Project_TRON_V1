# Packaging/Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `TRON.exe` — a portable PyInstaller build that self-configures on first launch (tkinter wizard writing `config.json`), offers to autostart on login (registry Run key), resolves `config.json`/`persona.txt` correctly relative to the real exe location (not PyInstaller's temp extraction folder), and logs crashes to a file instead of vanishing silently — per `docs/superpowers/specs/2026-08-09-packaging-shell-design.md`. Builds directly on Voice Core + Automation/Tools.

**Architecture:** `config.app_dir()` detects frozen (`sys.frozen`) vs. dev-mode execution and returns the right base directory either way; every path that needs to survive across launches (`config.json`, `persona.txt`) resolves through it. `main.py` runs `setup_wizard.run_first_time_setup()` before `load_config()` if `config.json` doesn't exist yet, and wraps its whole run in a crash logger.

**Tech Stack:** stdlib only for the new code (`tkinter`, `winreg`, `sys`, `traceback`) — `pyinstaller` is a build-time-only tool, added to a separate `requirements-build.txt`, not the runtime `requirements.txt`.

## Global Constraints

- No new *runtime* dependency — `tkinter` and `winreg` are stdlib. `pyinstaller` goes in `requirements-build.txt`, never `requirements.txt`.
- Every path read at runtime that must persist across launches (`config.json`, `persona.txt`, `tron_error.log`) resolves through `config.app_dir()` / `config.resolve_path()` — never bare `Path(__file__)` or an unresolved relative path, since both break once frozen (see spec's "core packaging problem" section).
- GUI code (`setup_wizard.py`'s window) stays thin; the logic behind it (`build_config_dict`, `write_config_file`) is separated out and unit-tested without driving real tkinter widgets — same pattern `tray_ui.py` already established for `pystray`.
- "Background service" scope is tray + registry autostart, not a real Windows Service (see spec's scope decision) — do not reach for `pywin32` service APIs here.

---

### Task 1: `config.py` — frozen-aware path resolution

**Files:**
- Modify: `config.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `config.app_dir() -> Path`, `config.resolve_path(path_str: str | Path) -> Path`. `config.CONFIG_PATH` now built from `app_dir()` instead of `Path(__file__).parent`.

- [ ] **Step 1: Add the new failing tests to `tests/test_config.py`**

```python
# tests/test_config.py — add these to the existing file, alongside the current two tests
from pathlib import Path


def test_app_dir_dev_mode(monkeypatch):
    monkeypatch.setattr(config_module.sys, "frozen", False, raising=False)
    assert config_module.app_dir() == Path(config_module.__file__).parent


def test_app_dir_frozen(monkeypatch):
    monkeypatch.setattr(config_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config_module.sys, "executable", "C:\\Apps\\TRON\\TRON.exe", raising=False)

    assert config_module.app_dir() == Path("C:\\Apps\\TRON")


def test_resolve_path_relative_resolves_against_app_dir(monkeypatch):
    monkeypatch.setattr(config_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config_module.sys, "executable", "C:\\Apps\\TRON\\TRON.exe", raising=False)

    assert config_module.resolve_path("persona.txt") == Path("C:\\Apps\\TRON\\persona.txt")


def test_resolve_path_absolute_passes_through(monkeypatch):
    monkeypatch.setattr(config_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config_module.sys, "executable", "C:\\Apps\\TRON\\TRON.exe", raising=False)

    absolute = "D:\\elsewhere\\custom_persona.txt"
    assert config_module.resolve_path(absolute) == Path(absolute)
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `.venv\Scripts\pytest tests/test_config.py -v`
Expected: FAIL on the 4 new tests with `AttributeError: module 'config' has no attribute 'app_dir'` (the existing 2 tests still pass)

- [ ] **Step 3: Modify `config.py`**

```python
# config.py
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Union


def app_dir() -> Path:
    """Directory config/persona files live in: next to the .exe when frozen
    (PyInstaller --onefile extracts to a temp dir, so __file__ is unusable
    there), next to this script in dev mode."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def resolve_path(path_str: Union[str, Path]) -> Path:
    """Resolves a config path string against app_dir(), unless it's already absolute."""
    path = Path(path_str)
    return path if path.is_absolute() else app_dir() / path


CONFIG_PATH = app_dir() / "config.json"


@dataclass
class Config:
    gemini_api_key: str
    wake_mode: str
    hotkey: str
    wakeword_model_path: str
    persona_path: str
    silence_timeout_s: float
    voice_name: str
    model_name: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_app_password: str


def load_config() -> Config:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Missing {CONFIG_PATH}. Copy config.example.json to config.json "
            "and fill in gemini_api_key."
        )
    data = json.loads(CONFIG_PATH.read_text())
    return Config(
        gemini_api_key=data["gemini_api_key"],
        wake_mode=data.get("wake_mode", "hotkey"),
        hotkey=data.get("hotkey", "ctrl+alt+t"),
        wakeword_model_path=data.get("wakeword_model_path", "models/tron.onnx"),
        persona_path=data.get("persona_path", "persona.txt"),
        silence_timeout_s=data.get("silence_timeout_s", 45.0),
        voice_name=data.get("voice_name", "Charon"),
        model_name=data.get("model_name", "gemini-2.0-flash-live-001"),
        smtp_host=data.get("smtp_host", ""),
        smtp_port=data.get("smtp_port", 465),
        smtp_user=data.get("smtp_user", ""),
        smtp_app_password=data.get("smtp_app_password", ""),
    )
```

Only `app_dir()`, `resolve_path()`, and `CONFIG_PATH`'s definition change; `Config` and `load_config()` are untouched from sub-project 2.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest tests/test_config.py -v`
Expected: PASS (6 tests: 2 existing + 4 new)

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "Add frozen-aware path resolution to config.py"
```

---

### Task 2: Registry autostart

**Files:**
- Create: `autostart.py`
- Test: `tests/test_autostart.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `autostart.enable() -> None`, `autostart.disable() -> None`, `autostart.is_enabled() -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_autostart.py
from unittest.mock import MagicMock

import autostart


def _fake_winreg():
    fake = MagicMock()
    fake.HKEY_CURRENT_USER = "HKCU"
    fake.KEY_SET_VALUE = "SET"
    fake.KEY_READ = "READ"
    fake.REG_SZ = "SZ"
    return fake


def test_enable_writes_command_line_to_registry(monkeypatch):
    fake_winreg = _fake_winreg()
    fake_key = MagicMock()
    fake_winreg.OpenKey.return_value = fake_key
    monkeypatch.setattr(autostart, "winreg", fake_winreg)
    monkeypatch.setattr(autostart.sys, "frozen", True, raising=False)
    monkeypatch.setattr(autostart.sys, "executable", "C:\\Apps\\TRON\\TRON.exe", raising=False)

    autostart.enable()

    fake_winreg.OpenKey.assert_called_once_with("HKCU", autostart._RUN_KEY_PATH, 0, "SET")
    fake_winreg.SetValueEx.assert_called_once_with(
        fake_key, "TRON", 0, "SZ", '"C:\\Apps\\TRON\\TRON.exe"'
    )
    fake_winreg.CloseKey.assert_called_once_with(fake_key)


def test_disable_removes_value_if_present(monkeypatch):
    fake_winreg = _fake_winreg()
    fake_key = MagicMock()
    fake_winreg.OpenKey.return_value = fake_key
    monkeypatch.setattr(autostart, "winreg", fake_winreg)

    autostart.disable()

    fake_winreg.DeleteValue.assert_called_once_with(fake_key, "TRON")
    fake_winreg.CloseKey.assert_called_once_with(fake_key)


def test_disable_is_a_no_op_if_not_present(monkeypatch):
    fake_winreg = _fake_winreg()
    fake_key = MagicMock()
    fake_winreg.OpenKey.return_value = fake_key
    fake_winreg.DeleteValue.side_effect = FileNotFoundError()
    monkeypatch.setattr(autostart, "winreg", fake_winreg)

    autostart.disable()  # must not raise

    fake_winreg.CloseKey.assert_called_once_with(fake_key)


def test_is_enabled_true_when_value_present(monkeypatch):
    fake_winreg = _fake_winreg()
    fake_key = MagicMock()
    fake_winreg.OpenKey.return_value = fake_key
    fake_winreg.QueryValueEx.return_value = ('"C:\\Apps\\TRON\\TRON.exe"', "SZ")
    monkeypatch.setattr(autostart, "winreg", fake_winreg)

    assert autostart.is_enabled() is True


def test_is_enabled_false_when_key_missing(monkeypatch):
    fake_winreg = _fake_winreg()
    fake_winreg.OpenKey.side_effect = FileNotFoundError()
    monkeypatch.setattr(autostart, "winreg", fake_winreg)

    assert autostart.is_enabled() is False


def test_is_enabled_false_when_value_missing(monkeypatch):
    fake_winreg = _fake_winreg()
    fake_key = MagicMock()
    fake_winreg.OpenKey.return_value = fake_key
    fake_winreg.QueryValueEx.side_effect = FileNotFoundError()
    monkeypatch.setattr(autostart, "winreg", fake_winreg)

    assert autostart.is_enabled() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\pytest tests/test_autostart.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autostart'`

- [ ] **Step 3: Write `autostart.py`**

```python
# autostart.py
import sys
import winreg
from pathlib import Path

_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "TRON"


def _command_line() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    main_py = Path(__file__).parent / "main.py"
    return f'"{sys.executable}" "{main_py}"'


def enable() -> None:
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE)
    try:
        winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, _command_line())
    finally:
        winreg.CloseKey(key)


def disable() -> None:
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE)
    try:
        try:
            winreg.DeleteValue(key, _VALUE_NAME)
        except FileNotFoundError:
            pass
    finally:
        winreg.CloseKey(key)


def is_enabled() -> bool:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_READ)
    except FileNotFoundError:
        return False
    try:
        winreg.QueryValueEx(key, _VALUE_NAME)
        return True
    except FileNotFoundError:
        return False
    finally:
        winreg.CloseKey(key)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\pytest tests/test_autostart.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add autostart.py tests/test_autostart.py
git commit -m "Add registry-based autostart-on-login"
```

---

### Task 3: First-run setup wizard

**Files:**
- Create: `setup_wizard.py`
- Test: `tests/test_setup_wizard.py`

**Interfaces:**
- Consumes: `config.CONFIG_PATH`, `autostart.enable`
- Produces: `setup_wizard.build_config_dict(form_values: dict) -> dict` (pure), `setup_wizard.write_config_file(path: Path, config_dict: dict) -> None` (pure I/O), `setup_wizard.run_first_time_setup() -> None` (blocking tkinter window, not unit-tested — see Global Constraints)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_setup_wizard.py
import json

import setup_wizard


def test_build_config_dict_fills_required_and_optional_fields():
    form = {
        "gemini_api_key": "  my-key  ",
        "hotkey": "ctrl+alt+j",
        "smtp_host": "smtp.example.com",
        "smtp_port": "587",
        "smtp_user": "me@example.com",
        "smtp_app_password": "pw",
    }

    result = setup_wizard.build_config_dict(form)

    assert result["gemini_api_key"] == "my-key"
    assert result["hotkey"] == "ctrl+alt+j"
    assert result["smtp_port"] == 587
    assert result["smtp_user"] == "me@example.com"


def test_build_config_dict_defaults_when_optional_fields_blank():
    form = {"gemini_api_key": "my-key", "hotkey": ""}

    result = setup_wizard.build_config_dict(form)

    assert result["hotkey"] == "ctrl+alt+t"
    assert result["smtp_port"] == 465
    assert result["smtp_host"] == ""


def test_write_config_file_writes_valid_json(tmp_path):
    path = tmp_path / "config.json"
    config_dict = {"gemini_api_key": "k"}

    setup_wizard.write_config_file(path, config_dict)

    assert json.loads(path.read_text(encoding="utf-8")) == {"gemini_api_key": "k"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\pytest tests/test_setup_wizard.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'setup_wizard'`

- [ ] **Step 3: Write `setup_wizard.py`**

```python
# setup_wizard.py
import json
import tkinter as tk
from tkinter import messagebox, ttk

import autostart
import config


def build_config_dict(form_values: dict) -> dict:
    """Turns raw wizard form values into the config.json dict shape. Pure — no I/O."""
    return {
        "gemini_api_key": form_values["gemini_api_key"].strip(),
        "wake_mode": "hotkey",
        "hotkey": form_values.get("hotkey", "").strip() or "ctrl+alt+t",
        "wakeword_model_path": "models/tron.onnx",
        "persona_path": "persona.txt",
        "silence_timeout_s": 45.0,
        "voice_name": "Charon",
        "model_name": "gemini-2.0-flash-live-001",
        "smtp_host": form_values.get("smtp_host", "").strip(),
        "smtp_port": int(form_values.get("smtp_port") or 465),
        "smtp_user": form_values.get("smtp_user", "").strip(),
        "smtp_app_password": form_values.get("smtp_app_password", "").strip(),
    }


def write_config_file(path, config_dict: dict) -> None:
    path.write_text(json.dumps(config_dict, indent=2), encoding="utf-8")


def run_first_time_setup() -> None:
    """Blocks on a tkinter window until the user submits, then writes config.json
    (and enables autostart if requested)."""
    root = tk.Tk()
    root.title("TRON — first-time setup")

    fields = {}

    def add_field(key, label_text, row, default="", show=None):
        ttk.Label(root, text=label_text).grid(row=row, column=0, sticky="w", padx=8, pady=4)
        var = tk.StringVar(value=default)
        ttk.Entry(root, textvariable=var, width=40, show=show or "").grid(
            row=row, column=1, padx=8, pady=4
        )
        fields[key] = var

    add_field("gemini_api_key", "Gemini API key", 0, show="*")
    add_field("hotkey", "Hotkey", 1, default="ctrl+alt+t")
    add_field("smtp_host", "SMTP host (optional)", 2)
    add_field("smtp_port", "SMTP port (optional)", 3, default="465")
    add_field("smtp_user", "SMTP user (optional)", 4)
    add_field("smtp_app_password", "SMTP app password (optional)", 5, show="*")

    autostart_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(
        root, text="Start TRON automatically when I log in", variable=autostart_var
    ).grid(row=6, column=0, columnspan=2, sticky="w", padx=8, pady=4)

    def on_save():
        if not fields["gemini_api_key"].get().strip():
            messagebox.showerror("TRON setup", "A Gemini API key is required.")
            return
        form_values = {key: var.get() for key, var in fields.items()}
        config_dict = build_config_dict(form_values)
        write_config_file(config.CONFIG_PATH, config_dict)
        if autostart_var.get():
            try:
                autostart.enable()
            except Exception as exc:
                messagebox.showwarning(
                    "TRON setup",
                    f"Couldn't enable autostart: {exc}\nYou can still run TRON manually.",
                )
        root.destroy()

    ttk.Button(root, text="Save & Start", command=on_save).grid(
        row=7, column=0, columnspan=2, pady=10
    )

    root.mainloop()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\pytest tests/test_setup_wizard.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add setup_wizard.py tests/test_setup_wizard.py
git commit -m "Add first-run tkinter setup wizard"
```

---

### Task 4: Wire the wizard and crash logging into `main.py`

**Files:**
- Modify: `main.py`

**Interfaces:**
- Consumes: `config.CONFIG_PATH`, `config.load_config`, `config.resolve_path`, `config.app_dir`, `setup_wizard.run_first_time_setup`
- Produces: `main._run_with_crash_log() -> None` (new script entry point)

- [ ] **Step 1: Rewrite `main.py`**

There is no dedicated test file for `main.py` itself, consistent with sub-projects 1–2 — it is pure wiring, verified by `py_compile` plus the manual smoke-test checklist in `docs/build_exe.md` (Task 5). The pieces it wires together (`config`, `setup_wizard`, `autostart`) each have their own tests already.

```python
# main.py
import sys
import time
import traceback

import config as config_module
import setup_wizard
from state_manager import TronStateMachine
from wake_trigger import HotkeyTrigger
from tray_ui import TrayUI


def main() -> None:
    if not config_module.CONFIG_PATH.exists():
        setup_wizard.run_first_time_setup()

    cfg = config_module.load_config()
    persona_text = config_module.resolve_path(cfg.persona_path).read_text(encoding="utf-8")

    if cfg.wake_mode != "hotkey":
        raise NotImplementedError(
            f'wake_mode="{cfg.wake_mode}" is not wired up yet — only "hotkey" is. '
            "See docs/train_wakeword.md to add a trained wake-word model, then "
            "extend wake_trigger.py with an OpenWakeWordTrigger."
        )

    tray = TrayUI(quit_callback=lambda: _quit(trigger, tray))

    machine = TronStateMachine(
        api_key=cfg.gemini_api_key,
        model_name=cfg.model_name,
        voice_name=cfg.voice_name,
        persona_text=persona_text,
        silence_timeout_s=cfg.silence_timeout_s,
        on_state_change=tray.on_state_change,
        cfg=cfg,
    )

    trigger = HotkeyTrigger(cfg.hotkey, on_trigger=machine.trigger)
    trigger.start()
    tray.start()

    print(f'TRON is running. Press {cfg.hotkey} to talk. Quit from the tray icon menu.')
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        _quit(trigger, tray)


def _quit(trigger: HotkeyTrigger, tray: TrayUI) -> None:
    trigger.stop()
    tray.stop()
    sys.exit(0)


def _run_with_crash_log() -> None:
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        log_path = config_module.app_dir() / "tron_error.log"
        log_path.write_text(traceback.format_exc(), encoding="utf-8")
        raise


if __name__ == "__main__":
    _run_with_crash_log()
```

- [ ] **Step 2: Compile-check and run the full test suite**

Run: `.venv\Scripts\python -m py_compile main.py` then `.venv\Scripts\pytest -v`
Expected: `main.py` compiles; all tests across all tasks (this plan's + sub-projects 1–2's) pass.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "Wire first-run setup wizard and crash logging into main.py"
```

---

### Task 5: Build docs and README

**Files:**
- Create: `requirements-build.txt`
- Create: `docs/build_exe.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing (documentation only)
- Produces: nothing consumed by other tasks

- [ ] **Step 1: Create `requirements-build.txt`**

```
pyinstaller>=6.0
```

- [ ] **Step 2: Create `docs/build_exe.md`**

```markdown
# Building TRON.exe

One-time build environment setup:

```
.venv\Scripts\pip install -r requirements-build.txt
```

Build the portable exe:

```
.venv\Scripts\pyinstaller --onefile --noconsole --name TRON --collect-all sounddevice --collect-all pystray --collect-all keyboard main.py
```

`--onefile` produces a single `dist\TRON.exe`. `--noconsole` hides the console
window (TRON is a tray app, not a CLI). The three `--collect-all` flags bundle
native/backend files these packages need at runtime that PyInstaller's default
import scanner tends to miss — sounddevice's PortAudio binary, pystray's
Windows backend, and keyboard's low-level hook DLL. If a fresh build launches
and immediately errors on import, check first whether it's one of these three
libraries failing to find a bundled resource, and add the matching
`--collect-all` (or the narrower `--collect-binaries`/`--collect-data`) back
in. PyInstaller version upgrades occasionally change what needs collecting —
treat this list as a starting point, not a permanent fact.

`persona.txt` is intentionally **not** bundled into the exe — it needs to live
next to `dist\TRON.exe` so it's user-editable without a rebuild:

```
copy persona.txt dist\persona.txt
```

## Smoke-testing the build

1. From a fresh folder (not the repo — simulates a real install), copy only
   `dist\TRON.exe` and `persona.txt`.
2. Double-click `TRON.exe`. The first-time setup window should appear.
3. Enter a Gemini API key, leave the rest default, save.
4. Confirm `config.json` appears next to `TRON.exe` (not anywhere else) and
   the tray icon appears (white/idle).
5. Press the configured hotkey and confirm TRON responds.
6. Close TRON, relaunch `TRON.exe` — it should go straight to the tray icon,
   no setup window this time.
7. Check `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run` in
   `regedit` for a `TRON` value pointing at the exe's path, if autostart was
   left checked.
8. To test crash logging: temporarily rename `persona.txt` so startup fails,
   relaunch, and confirm `tron_error.log` appears next to the exe with a
   readable traceback. Restore `persona.txt` afterward.
```

- [ ] **Step 3: Modify `README.md`** — add a packaged-exe section

```markdown
# TRON

A personal voice assistant. Sub-project 3/6 (Packaging/Shell) of the larger
TRON program — see `docs/superpowers/specs/` for the full design and roadmap.

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

## Running the packaged .exe

Build `TRON.exe` per `docs/build_exe.md`, or if you already have one: just
double-click it. First launch opens a small setup window asking for your
Gemini API key (and optionally email settings) and offers to start TRON
automatically on login — no manual `config.json` editing needed. Every launch
after that goes straight to the tray icon.

If TRON crashes, check `tron_error.log` next to the exe for a traceback.

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
```

- [ ] **Step 4: Commit**

```bash
git add requirements-build.txt docs/build_exe.md README.md
git commit -m "Add PyInstaller build docs and update README for packaged exe"
```
