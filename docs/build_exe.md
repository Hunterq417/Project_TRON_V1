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
