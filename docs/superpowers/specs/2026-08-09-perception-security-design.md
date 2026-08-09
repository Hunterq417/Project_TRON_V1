# Perception + Security — Design Spec

**Sub-project 6 of 6 — the final piece** in the TRON program. Adds screen/camera vision and malware scanning, deliberately last because it carries the highest privacy/security surface of anything built so far.

## Goal

You can ask TRON to look at your screen or through your camera and describe what it sees, and to run a malware scan — but only after you've explicitly turned camera/screen access on. Neither capability is available on a fresh install.

## The consent model, concretely

The Voice Core spec (sub-project 1) committed to "a per-capability permission/consent design... rather than one blanket always-on grant." This is where that commitment is implemented:

- `config.json` gains `camera_enabled` and `screen_enabled`, both defaulting to **`false`**.
- `tools.declarations_for(cfg)` — not the static `TOOL_DECLARATIONS` list used until now — builds the tool schema actually sent to Gemini Live, filtering out `look_at_screen`/`look_via_camera` unless their flag is on.
- This isn't just "TRON is told not to use it" (a prompt-level instruction an LLM could in principle ignore) — the tool is **not declared to the model at all** when disabled, so it's not a tool Gemini has any way to call. Consent is enforced structurally, not by asking nicely.
- The first-run setup wizard (sub-project 3) gains two more checkboxes, both **unchecked by default**: "Enable camera access," "Enable screen reading." Changeable anytime by editing `config.json` or re-running setup.
- Every use of a vision tool or a scan is logged via the `memory.py` activity log built in sub-project 4 — "what have you been up to" already gives visibility into every time TRON looked at your screen or camera, for free, without building a separate audit UI.

## Vision: genuine multimodal input, not local OCR

Normal tools return a text string via `send_tool_response` — fine for "opened notepad," useless for "describe what's on my screen." Piping OCR'd text back through that channel was considered and rejected: it needs a separately-installed Tesseract binary (real packaging friction) and only handles text, not general visual description ("what am I holding," "does this look right").

Instead: `gemini_live_client.GeminiLiveSession` gains `send_video_frame(jpeg_bytes: bytes) -> None`, parallel to the existing `send_audio_chunk`, using Gemini Live's realtime image input. When `look_at_screen`/`look_via_camera` is called, `state_manager.py` captures a frame, pushes it into the *same live session* via `send_video_frame`, and Gemini's next spoken turn describes what it actually saw — real vision, grounded in the actual pixels, not a text approximation.

This is why vision tools can't go through the normal `tools.TOOL_DISPATCH` — every other tool has the signature `(args, cfg) -> str` and no access to the live session object. Vision tools are handled as a special case directly in `state_manager.py`'s tool-call branch.

## Components

| Component | Responsibility | Notes |
|---|---|---|
| `perception.py` | `capture_screen_jpeg() -> bytes` (Pillow's `ImageGrab.grab()`, already a dependency, encoded to JPEG in-memory). `capture_camera_jpeg() -> bytes` (`opencv-python`, new dependency — no lighter stdlib option exists for webcam capture). | Both are one-shot captures, not continuous streams — no background recording of the screen or camera ever happens. |
| `gemini_live_client.py` (modified) | Adds `send_video_frame(jpeg_bytes) -> None`. | Same `Blob`-based pattern as `send_audio_chunk`, different mime type. |
| `state_manager.py` (modified) | Recognizes `look_at_screen`/`look_via_camera` in the tool-call branch, handles them via `perception.py` + `send_video_frame` instead of `TOOL_DISPATCH`; logs the capture to memory. Session factory now calls `tools.declarations_for(self._cfg)` instead of the static `tools.TOOL_DECLARATIONS`. | |
| `security_scan.py` | `scan_for_malware() -> str` starts Windows Defender's own `Start-MpScan` (PowerShell) on a background thread and returns immediately; the thread logs completion to memory when done. `check_scan_status() -> str` reports the most recent scan's state. | No custom malware detection logic — wrapping the OS's already-maintained, actually-effective scanner is the only responsible design here. Fits the normal `(args, cfg) -> str` tool signature; goes through `TOOL_DISPATCH` like any other tool, always declared (not gated — inspecting the user's own files isn't the same privacy category as camera/screen capture). |
| `setup_wizard.py` (modified) | Two more unchecked checkboxes: camera, screen. | |
| `config.py` / `config.example.json` (modified) | `camera_enabled`, `screen_enabled` fields, default `false`. | |
| `persona.txt` (modified) | Instructed to say "let me take a look, sir" (or similar) before using a vision tool — transparency at time of use. | |

## Data flow

**Vision:** Gemini decides to call `look_at_screen` (only possible if `declarations_for(cfg)` included it) → `state_manager` captures a JPEG → `session.send_video_frame(jpeg_bytes)` → `memory.log_activity(...)` → a short text ack goes back via `send_tool_response` ("here's my screen, sir") → Gemini's next audio turn describes what it saw, grounded in the actual frame.

**Scan:** Gemini calls `scan_for_malware` → a background thread runs `Start-MpScan -ScanType QuickScan` → the tool returns "scan started, sir" immediately (a full scan can run well past the conversation's silence timeout) → the thread logs completion (and result) to memory when it finishes → a later "did the scan finish" calls `check_scan_status`, which reads that logged state.

## Error handling

| Condition | Behavior |
|---|---|
| `look_at_screen`/`look_via_camera` called while disabled | Can't happen — not declared to Gemini, so the model has no tool by that name to call. |
| No webcam present / camera in use by another app | `capture_camera_jpeg()` raises; caught in `state_manager`, surfaced as a spoken "couldn't access the camera, sir" rather than a crash. |
| `Start-MpScan` unavailable (Defender disabled/replaced by third-party AV) | `scan_for_malware()` catches the subprocess failure and returns a clear explanation instead of hanging or crashing. |
| `check_scan_status` called with no scan ever started | Returns "no scan has been run yet, sir." |

## Testing

`perception.py`'s capture functions are tested by monkeypatching `PIL.ImageGrab.grab`/`cv2.VideoCapture` — no real screen/camera access in tests. `security_scan.py`'s subprocess calls are tested by monkeypatching `subprocess.run`/`Popen`, with the background-thread completion logic tested by running it synchronously in the test (no real scan). `state_manager.py`'s vision-tool branch is tested the same way sub-project 2's tool-call dispatch was — a fake session asserting `send_video_frame` and `send_tool_response` get called correctly, and that `look_at_screen` is included/excluded from `declarations_for(cfg)` based on `cfg.screen_enabled`.

## Explicitly out of scope

- Continuous/background screen or camera monitoring — every capture is one-shot, triggered only by an explicit tool call
- Custom malware detection (wraps Windows Defender only)
- Face recognition, identity verification, or any biometric processing
- A UI for reviewing captured frames (they're never saved to disk — sent directly into the live session and discarded; only the *fact* of the capture is logged, not the image itself)
