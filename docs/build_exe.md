# Building TRON.exe

One-time build environment setup:

```
.venv\Scripts\pip install -r requirements-build.txt
```

Build the portable exe:

```
.venv\Scripts\pyinstaller --onefile --noconsole --name TRON --collect-all sounddevice --collect-all pystray --collect-all keyboard --collect-all pywebview main.py
```

`--onefile` produces a single `dist\TRON.exe`. `--noconsole` hides the console
window (TRON is a tray app, not a CLI). The four `--collect-all` flags bundle
native/backend files these packages need at runtime that PyInstaller's default
import scanner tends to miss — sounddevice's PortAudio binary, pystray's
Windows backend, keyboard's low-level hook DLL, and pywebview's Windows
(Edge WebView2) backend. If a fresh build launches and immediately errors on
import, check first whether it's one of these four libraries failing to find
a bundled resource, and add the matching `--collect-all` (or the narrower
`--collect-binaries`/`--collect-data`) back in. PyInstaller version upgrades
occasionally change what needs collecting — treat this list as a starting
point, not a permanent fact.

pywebview's Windows backend uses the Edge WebView2 runtime, which ships with
Windows 10/11 by default. If the orb window fails to render on a machine
without it, install the "WebView2 Runtime" from Microsoft.

`persona.txt` and `orb.html` are intentionally **not** bundled into the exe —
they need to live next to `dist\TRON.exe` so they're user-editable without a
rebuild:

```
copy persona.txt dist\persona.txt
copy orb.html dist\orb.html
```

## Smoke-testing the build

1. From a fresh folder (not the repo — simulates a real install), copy only
   `dist\TRON.exe`, `persona.txt`, and `orb.html`.
2. Double-click `TRON.exe`. The first-time setup window should appear.
3. Enter a Gemini API key, leave the rest default, save.
4. Confirm `config.json` appears next to `TRON.exe` (not anywhere else) and
   the tray icon appears (white/idle).
5. Press the configured hotkey and confirm TRON responds. Confirm the orb
   window appears centered on screen, spinning slowly and changing color
   with TRON's state, and disappears again once the conversation ends.
6. From the tray menu, click "Show/Hide Orb" and confirm it toggles the orb
   on and off manually.
7. Close TRON, relaunch `TRON.exe` — it should go straight to the tray icon,
   no setup window this time.
8. Check `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run` in
   `regedit` for a `TRON` value pointing at the exe's path, if autostart was
   left checked.
9. To test crash logging: temporarily rename `persona.txt` so startup fails,
   relaunch, and confirm `tron_error.log` appears next to the exe with a
   readable traceback. Restore `persona.txt` afterward.
