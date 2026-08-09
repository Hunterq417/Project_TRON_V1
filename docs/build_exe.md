# Building TRON.exe

One-time build environment setup:

```
.venv\Scripts\pip install -r requirements-build.txt
```

Build the portable exe:

```
.venv\Scripts\pyinstaller --onefile --noconsole --name TRON --collect-all sounddevice --collect-all pystray --collect-all keyboard --collect-all pywebview --collect-all cv2 main.py
```

`--onefile` produces a single `dist\TRON.exe`. `--noconsole` hides the console
window (TRON is a tray app, not a CLI). The five `--collect-all` flags bundle
native/backend files these packages need at runtime that PyInstaller's default
import scanner tends to miss — sounddevice's PortAudio binary, pystray's
Windows backend, keyboard's low-level hook DLL, pywebview's Windows
(Edge WebView2) backend, and opencv's native `cv2` extension (webcam capture).
If a fresh build launches and immediately errors on import, check first
whether it's one of these five libraries failing to find a bundled resource,
and add the matching `--collect-all` (or the narrower
`--collect-binaries`/`--collect-data`) back in. PyInstaller version upgrades
occasionally change what needs collecting — treat this list as a starting
point, not a permanent fact.

pywebview's Windows backend uses the Edge WebView2 runtime, which ships with
Windows 10/11 by default. If the orb window fails to render on a machine
without it, install the "WebView2 Runtime" from Microsoft.

`persona.txt`, `orb.html`, and `vendor\` are intentionally **not** bundled
into the exe — they need to live next to `dist\TRON.exe` so `persona.txt`
and `orb.html` stay user-editable without a rebuild (`orb.html` loads
`vendor\three.min.js` via a relative path, so `vendor\` has to travel with it):

```
copy persona.txt dist\persona.txt
copy orb.html dist\orb.html
xcopy vendor dist\vendor\ /E /I
```

## Smoke-testing the build

1. From a fresh folder (not the repo — simulates a real install), copy only
   `dist\TRON.exe`, `persona.txt`, `orb.html`, and the `vendor\` folder.
2. Double-click `TRON.exe`. The first-time setup window should appear.
3. Enter a Gemini API key, leave the rest default, save.
4. Confirm `config.json` appears next to `TRON.exe` (not anywhere else) and
   the tray icon appears (white/idle).
5. Press the configured hotkey and confirm TRON responds. Confirm the orb
   appears centered on your primary monitor, changing color with TRON's
   state and pulsing with the actual loudness of its voice while it talks,
   and disappears again once the conversation ends.
6. From the tray menu, click "Show/Hide Orb" and confirm it toggles the orb
   on and off manually.
7. **Desktop-pinning (never visually verified during development — check
   this first):** while TRON is speaking, alt-tab to or click into another
   application window over where the orb is. It should end up hidden behind
   that window, not floating on top of it. If it stays on top instead, the
   WorkerW trick (`desktop_layer.py`) failed silently on your Windows
   build/configuration and the orb fell back to being a normal window —
   not a bug exactly, but worth knowing which mode you're actually in.
8. Close TRON, relaunch `TRON.exe` — it should go straight to the tray icon,
   no setup window this time.
9. Check `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run` in
   `regedit` for a `TRON` value pointing at the exe's path, if autostart was
   left checked.
10. To test crash logging: temporarily rename `persona.txt` so startup fails,
    relaunch, and confirm `tron_error.log` appears next to the exe with a
    readable traceback. Restore `persona.txt` afterward.
11. Enable "camera access"/"screen reading" in setup and confirm asking TRON
    to look at your screen or through the camera works, and that it says
    something like "let me take a look, sir" first. With both left
    unchecked, confirm TRON explains it doesn't have that capability rather
    than silently failing.
12. Ask TRON to run a malware scan, confirm it responds immediately (not a
    multi-minute wait), then later ask whether the scan finished.
