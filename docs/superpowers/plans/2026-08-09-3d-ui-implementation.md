# 3D UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A centered, always-on-top 400×400px particle-sphere orb (`orb_ui.py` + `orb.html`) that mirrors TRON's state in the same 6-color palette as the tray icon, toggleable from a new tray menu item — per `docs/superpowers/specs/2026-08-09-3d-ui-design.md`.

**Architecture:** `pywebview` hosts a self-contained vanilla-JS Canvas2D animation. `main.py` composes `TrayUI.on_state_change` and `OrbUI.on_state_change` into one callback so both stay in lockstep.

**Tech Stack:** New dependency `pywebview` (Windows Edge WebView2 backend, no bundled Chromium). No JS libraries — hand-rolled Canvas2D sphere.

## Global Constraints

- `orb.html` resolves via `config.resolve_path("orb.html")`, matching `persona.txt`'s treatment (lives next to the exe, user-editable, not bundled into the PyInstaller archive).
- Orb colors are literally the same six RGB tuples as `tray_ui._COLORS` — keep them in sync if either changes later.
- `tray_ui.TrayUI`'s new `toggle_orb_callback` parameter is optional and defaults to `None` — existing callers/tests that don't pass it keep today's Quit-only menu.

---

### Task 1: Tray menu gets an orb toggle

**Files:**
- Modify: `tray_ui.py`
- Modify: `tests/test_tray_ui.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `TrayUI(quit_callback, toggle_orb_callback=None)` — `toggle_orb_callback` adds a "Show/Hide Orb" menu item above Quit when provided.

- [ ] **Step 1: Add the failing tests**

```python
# tests/test_tray_ui.py — add these two tests
def test_menu_includes_orb_toggle_when_callback_provided(monkeypatch):
    fake_menu_item = MagicMock(side_effect=lambda *a, **k: MagicMock())
    monkeypatch.setattr(tray_ui.pystray, "Icon", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(tray_ui.pystray, "Menu", MagicMock())
    monkeypatch.setattr(tray_ui.pystray, "MenuItem", fake_menu_item)

    tray_ui.TrayUI(quit_callback=MagicMock(), toggle_orb_callback=MagicMock())

    labels = [call.args[0] for call in fake_menu_item.call_args_list]
    assert "Show/Hide Orb" in labels
    assert "Quit" in labels


def test_menu_omits_orb_toggle_when_callback_not_provided(monkeypatch):
    fake_menu_item = MagicMock(side_effect=lambda *a, **k: MagicMock())
    monkeypatch.setattr(tray_ui.pystray, "Icon", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(tray_ui.pystray, "Menu", MagicMock())
    monkeypatch.setattr(tray_ui.pystray, "MenuItem", fake_menu_item)

    tray_ui.TrayUI(quit_callback=MagicMock())

    labels = [call.args[0] for call in fake_menu_item.call_args_list]
    assert "Show/Hide Orb" not in labels
    assert "Quit" in labels
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest tests/test_tray_ui.py -v`
Expected: FAIL — `TrayUI.__init__` doesn't accept `toggle_orb_callback` yet

- [ ] **Step 3: Modify `tray_ui.py`** — only `TrayUI.__init__` changes

```python
    def __init__(self, quit_callback: Callable[[], None], toggle_orb_callback: Callable[[], None] | None = None):
        menu_items = []
        if toggle_orb_callback is not None:
            menu_items.append(pystray.MenuItem("Show/Hide Orb", lambda: toggle_orb_callback()))
        menu_items.append(pystray.MenuItem("Quit", lambda: quit_callback()))

        self._icon = pystray.Icon(
            "tron",
            icon=_make_icon_image(_COLORS["idle"]),
            title="TRON: idle",
            menu=pystray.Menu(*menu_items),
        )
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
```

`start()`, `stop()`, and `on_state_change()` are unchanged from sub-project 1.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest tests/test_tray_ui.py -v`
Expected: PASS (5 tests: 3 unchanged + 2 new)

- [ ] **Step 5: Commit**

```bash
git add tray_ui.py tests/test_tray_ui.py
git commit -m "Add optional orb-toggle menu item to the tray icon"
```

---

### Task 2: Orb window + particle-sphere HTML

**Files:**
- Create: `orb_ui.py`
- Create: `orb.html`
- Test: `tests/test_orb_ui.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `config.resolve_path`
- Produces: `orb_ui.OrbUI()` with `.start() -> None`, `.on_state_change(state) -> None`, `.toggle_visibility() -> None`

- [ ] **Step 1: Add `pywebview` to `requirements.txt`**

```
google-genai>=0.3.0
sounddevice>=0.4.6
numpy>=1.26
keyboard>=0.13.5
pystray>=0.19.5
Pillow>=10.0
pywebview>=5.0
pytest>=8.0
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_orb_ui.py
from unittest.mock import MagicMock

import orb_ui


def test_creates_window_with_expected_geometry(monkeypatch):
    fake_window = MagicMock()
    fake_create_window = MagicMock(return_value=fake_window)
    monkeypatch.setattr(orb_ui.webview, "create_window", fake_create_window)
    monkeypatch.setattr(orb_ui.webview, "start", MagicMock())

    orb_ui.OrbUI()

    _, kwargs = fake_create_window.call_args
    assert kwargs["width"] == 400
    assert kwargs["height"] == 400
    assert kwargs["frameless"] is True
    assert kwargs["transparent"] is True
    assert kwargs["on_top"] is True


def test_window_created_hidden(monkeypatch):
    fake_window = MagicMock()
    fake_create_window = MagicMock(return_value=fake_window)
    monkeypatch.setattr(orb_ui.webview, "create_window", fake_create_window)
    monkeypatch.setattr(orb_ui.webview, "start", MagicMock())

    orb_ui.OrbUI()

    _, kwargs = fake_create_window.call_args
    assert kwargs["hidden"] is True


def test_on_state_change_pushes_js(monkeypatch):
    fake_window = MagicMock()
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))
    monkeypatch.setattr(orb_ui.webview, "start", MagicMock())

    ui = orb_ui.OrbUI()

    class FakeState:
        name = "LISTENING"

    ui.on_state_change(FakeState())

    fake_window.evaluate_js.assert_called_once_with("setState('listening')")


def test_on_state_change_swallows_errors_before_window_ready(monkeypatch):
    fake_window = MagicMock()
    fake_window.evaluate_js.side_effect = Exception("not ready")
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))
    monkeypatch.setattr(orb_ui.webview, "start", MagicMock())

    ui = orb_ui.OrbUI()

    class FakeState:
        name = "IDLE"

    ui.on_state_change(FakeState())  # must not raise


def test_non_idle_state_pops_the_orb_up(monkeypatch):
    fake_window = MagicMock()
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))
    monkeypatch.setattr(orb_ui.webview, "start", MagicMock())

    ui = orb_ui.OrbUI()  # starts hidden (_visible = False)

    class FakeState:
        name = "LISTENING"

    ui.on_state_change(FakeState())

    fake_window.show.assert_called_once()
    fake_window.hide.assert_not_called()


def test_idle_state_hides_the_orb_again(monkeypatch):
    fake_window = MagicMock()
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))
    monkeypatch.setattr(orb_ui.webview, "start", MagicMock())

    ui = orb_ui.OrbUI()

    class Listening:
        name = "LISTENING"

    class Idle:
        name = "IDLE"

    ui.on_state_change(Listening())  # pops up
    ui.on_state_change(Idle())       # back down

    fake_window.show.assert_called_once()
    fake_window.hide.assert_called_once()


def test_repeated_non_idle_states_only_show_once(monkeypatch):
    """Avoids redundant show() calls flickering the window across LISTENING -> THINKING -> SPEAKING."""
    fake_window = MagicMock()
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))
    monkeypatch.setattr(orb_ui.webview, "start", MagicMock())

    ui = orb_ui.OrbUI()

    for name in ("LISTENING", "THINKING", "SPEAKING", "ACTING"):
        state = type("S", (), {"name": name})
        ui.on_state_change(state())

    assert fake_window.show.call_count == 1


def test_toggle_visibility_is_a_manual_override(monkeypatch):
    fake_window = MagicMock()
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))
    monkeypatch.setattr(orb_ui.webview, "start", MagicMock())

    ui = orb_ui.OrbUI()  # hidden by default

    ui.toggle_visibility()
    fake_window.show.assert_called_once()

    ui.toggle_visibility()
    fake_window.hide.assert_called_once()


def test_start_launches_background_thread(monkeypatch):
    fake_window = MagicMock()
    fake_start = MagicMock()
    monkeypatch.setattr(orb_ui.webview, "create_window", MagicMock(return_value=fake_window))
    monkeypatch.setattr(orb_ui.webview, "start", fake_start)

    ui = orb_ui.OrbUI()
    ui.start()

    assert ui._thread.daemon is True
```

- [ ] **Step 3: Install the new dependency and run test to verify it fails**

Run: `.venv\Scripts\pip install -r requirements.txt` then `.venv\Scripts\pytest tests/test_orb_ui.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'orb_ui'`

- [ ] **Step 4: Write `orb_ui.py`**

```python
# orb_ui.py
import threading

import webview

import config

_ORB_WIDTH = 400
_ORB_HEIGHT = 400


class OrbUI:
    """Centered, always-on-top particle-sphere HUD reflecting TronStateMachine state.

    Stays hidden while idle — pops onto the screen the moment a conversation
    starts (any non-idle state) and drops back out of sight once it ends."""

    def __init__(self):
        orb_html = config.resolve_path("orb.html")
        self._window = webview.create_window(
            "TRON",
            url=str(orb_html),
            width=_ORB_WIDTH,
            height=_ORB_HEIGHT,
            frameless=True,
            transparent=True,
            on_top=True,
            easy_drag=False,
            hidden=True,
        )
        self._thread = threading.Thread(target=webview.start, daemon=True)
        self._visible = False

    def start(self) -> None:
        self._thread.start()

    def on_state_change(self, state) -> None:
        name = state.name.lower()
        try:
            self._window.evaluate_js(f"setState('{name}')")
        except Exception:
            pass  # window may not be ready yet, or has been closed — non-fatal, purely visual

        if name == "idle":
            self._hide()
        else:
            self._show()

    def toggle_visibility(self) -> None:
        self._hide() if self._visible else self._show()

    def _show(self) -> None:
        if not self._visible:
            self._window.show()
            self._visible = True

    def _hide(self) -> None:
        if self._visible:
            self._window.hide()
            self._visible = False
```

- [ ] **Step 5: Write `orb.html`**

```html
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body { margin:0; padding:0; background: transparent; overflow: hidden; }
  canvas { display:block; }
</style>
</head>
<body>
<canvas id="c"></canvas>
<script>
const STATE_COLORS = {
  idle:      [235,235,235],
  listening: [66,133,244],
  thinking:  [255,193,7],
  speaking:  [52,199,89],
  acting:    [155,89,182],
  error:     [220,53,69],
};
let currentState = 'idle';
function setState(name) { if (STATE_COLORS[name]) currentState = name; }

const canvas = document.getElementById('c');
const ctx = canvas.getContext('2d');
function resize() { canvas.width = window.innerWidth; canvas.height = window.innerHeight; }
window.addEventListener('resize', resize);
resize();

const N = 220;
const points = [];
for (let i = 0; i < N; i++) {
  const phi = Math.acos(1 - 2 * (i + 0.5) / N);
  const theta = Math.PI * (1 + Math.sqrt(5)) * i;
  points.push({
    x: Math.sin(phi) * Math.cos(theta),
    y: Math.sin(phi) * Math.sin(theta),
    z: Math.cos(phi),
  });
}

let angle = 0;
function animate() {
  requestAnimationFrame(animate);
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  const [r, g, b] = STATE_COLORS[currentState];
  const cx = w / 2, cy = h / 2;
  const radius = Math.min(w, h) * 0.38;

  const speed = currentState === 'idle' ? 0.002 : currentState === 'error' ? 0.02 : 0.008;
  angle += speed;

  const pulse = (currentState === 'speaking' || currentState === 'acting')
    ? 1 + 0.08 * Math.sin(Date.now() / 150)
    : 1;

  const projected = points.map(p => {
    const x = p.x * Math.cos(angle) - p.z * Math.sin(angle);
    const z = p.x * Math.sin(angle) + p.z * Math.cos(angle);
    const y = p.y;
    const scale = 1.6 / (1.6 + z);
    return {
      sx: cx + x * radius * scale * pulse,
      sy: cy + y * radius * scale * pulse,
      z, scale,
    };
  }).sort((a, b) => a.z - b.z);

  for (const p of projected) {
    const alpha = 0.25 + 0.6 * ((p.z + 1) / 2);
    const size = 1.2 * p.scale + 0.6;
    ctx.beginPath();
    ctx.fillStyle = `rgba(${r},${g},${b},${alpha})`;
    ctx.shadowColor = `rgba(${r},${g},${b},0.9)`;
    ctx.shadowBlur = 8 * p.scale;
    ctx.arc(p.sx, p.sy, size, 0, Math.PI * 2);
    ctx.fill();
  }
}
animate();
</script>
</body>
</html>
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv\Scripts\pytest tests/test_orb_ui.py -v`
Expected: PASS (8 tests)

- [ ] **Step 7: Commit**

```bash
git add orb_ui.py orb.html requirements.txt tests/test_orb_ui.py
git commit -m "Add particle-sphere orb HUD (pywebview + vanilla-JS Canvas2D)"
```

---

### Task 3: Wire the orb into main.py, update docs

**Files:**
- Modify: `main.py`
- Modify: `docs/build_exe.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: `orb_ui.OrbUI`, `tray_ui.TrayUI(..., toggle_orb_callback=...)`
- Produces: nothing new

- [ ] **Step 1: Modify `main.py`**

```python
# main.py
import sys
import time
import traceback

import config as config_module
import setup_wizard
from orb_ui import OrbUI
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

    orb = OrbUI()
    tray = TrayUI(
        quit_callback=lambda: _quit(trigger, tray),
        toggle_orb_callback=orb.toggle_visibility,
    )

    def on_state_change(state) -> None:
        tray.on_state_change(state)
        orb.on_state_change(state)

    machine = TronStateMachine(
        api_key=cfg.gemini_api_key,
        model_name=cfg.model_name,
        voice_name=cfg.voice_name,
        persona_text=persona_text,
        silence_timeout_s=cfg.silence_timeout_s,
        on_state_change=on_state_change,
        cfg=cfg,
    )

    trigger = HotkeyTrigger(cfg.hotkey, on_trigger=machine.trigger)
    trigger.start()
    tray.start()
    orb.start()

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
Expected: `main.py` compiles; all tests across every sub-project so far pass.

- [ ] **Step 3: Update `docs/build_exe.md`** — add `--collect-all pywebview`, copy `orb.html`, and extend the smoke-test checklist

Add `--collect-all pywebview` to the documented `pyinstaller` command (alongside the existing three). Add to the "not bundled" copy step:

```
copy orb.html dist\orb.html
```

Add a note: pywebview's Windows backend uses the Edge WebView2 runtime, which ships with Windows 10/11 by default — if the build fails to render the orb on a machine without it, install the "WebView2 Runtime" from Microsoft.

Extend the smoke-test checklist with one more step: confirm the orb window appears centered on screen, spins slowly and white while idle, and changes color when you talk to TRON; confirm "Show/Hide Orb" in the tray menu toggles it.

- [ ] **Step 4: Update `README.md`** — bump to sub-project 5/6, document the orb

Update the header line to "Sub-project 5/6 (3D UI)" and add a short "Orb HUD" section under "What TRON can do now" noting the centered particle-sphere window, its color meanings (same table as the tray), and the tray's Show/Hide Orb toggle.

- [ ] **Step 5: Commit**

```bash
git add main.py docs/build_exe.md README.md
git commit -m "Wire orb HUD into main.py; update build docs and README"
```
