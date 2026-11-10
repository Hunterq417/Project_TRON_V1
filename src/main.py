# main.py
import ctypes
import datetime
import sys
import threading
import traceback
from pathlib import Path
from types import SimpleNamespace

import audio_io
import json
import time
import config as config_module
import setup_wizard
from orb_ui import OrbUI
import state_manager
from state_manager import TronStateMachine
from wake_trigger import HotkeyTrigger, OpenWakeWordTrigger
import wake_trigger
from tray_ui import TrayUI
from dashboard import Dashboard
import timers
import video_clip


# Spoken once at startup. Kept here rather than in persona.txt because it is an
# instruction for one conversation, not a standing trait.
_GREETING = (
    "Open this conversation yourself, without waiting to be spoken to. Greet the "
    "user in one short line suited to the time of day, and offer to help — "
    "\"Good morning, sir. How may I assist you today?\" is the register. "
    "If you can use the camera, call look_via_camera FIRST and greet whoever is "
    "actually there: if it is the user (match against what you know of their "
    "appearance), greet them by the register above. If it is clearly someone "
    "else, greet them politely and ask who they are — do not address a stranger "
    "as if they were the user. If the camera shows nobody or you cannot see, "
    "just greet normally and say nothing about having looked."
)


def _warn_box(title: str, message: str) -> None:
    """Best-effort popup. Never lets a failed warning take down startup."""
    try:
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x00000030)  # MB_ICONWARNING
    except Exception:
        pass


def _report_microphone(cfg) -> None:
    """Names the microphone TRON will listen on.

    Deliberately does not judge whether that mic can hear anything. A previous
    version sampled it briefly and warned when the level was near zero; it
    popped a scary dialog on a headset that turned out to be working fine,
    because an idle noise-gated mic and a muted one read exactly the same. See
    the note in audio_io. `--test-mic` answers that question properly."""
    try:
        name = audio_io.microphone_name(cfg.mic_device)
    except Exception as exc:
        # No dialog: TRON follows Windows' own default mic, so there's nothing for the user to fix here.
        print(f"Microphone: Windows default ({exc})")
        return
    print(f"Microphone: {name}")
    try:
        print(f"Speaker:    {audio_io.speaker_name(cfg.speaker_device)}"
              "   (this is where TRON's voice comes out)")
    except Exception as exc:
        print(f"WARNING: the configured speaker could not be found ({exc}).")


def _test_mic(cfg) -> None:
    """Live meter: prints loudness and the wake-word score for every block.

    Exists because "it doesn't hear me" is unfalsifiable from the outside — a
    muted mic, a mic pointed the wrong way and a model that misses all look
    identical. Watching the numbers move while you speak separates them in
    seconds. The first couple of seconds are skipped: opening a stream can emit
    a full-scale transient that would otherwise read as a shout."""
    import time

    model_path = str(config_module.resolve_path(cfg.wakeword_model_path))
    name = audio_io.microphone_name(cfg.mic_device)
    start = time.time()
    best = [0.0]

    def show(level: float, score: float) -> None:
        if time.time() - start < 2.0:
            return  # stream-open transient
        best[0] = max(best[0], score)
        bar = "#" * min(30, int(level / 200))
        hit = "   <<< HEY TRON DETECTED" if score >= 0.5 else ""
        print(f"  loudness {level:8.0f} |{bar:<30}| score {score:.4f}{hit}", flush=True)

    trigger = OpenWakeWordTrigger(model_path, on_trigger=lambda: None,
                                  device=cfg.mic_device, on_score=show)
    # Keep the audio. A model can be scored against a recording as many times as
    # needed, offline; a live session can only be judged once and costs someone
    # their time. Comparing two wake-word models on the actual voice that has to
    # trigger them is otherwise impossible.
    recording = audio_io.record_alongside(trigger)

    print(f'Listening on "{name}". Say "hey tron" a few times. Ctrl+C to stop.')
    print("(this saves what it hears to mic_test.wav so the model can be checked"
          " against it later)\n")
    trigger.start()
    try:
        while True:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        trigger.stop()
        print(f"\nBest score seen: {best[0]:.4f}"
              f"{'  (would have triggered)' if best[0] >= 0.5 else '  (never reached 0.5)'}")
        saved = recording.save(config_module.app_dir() / "mic_test.wav")
        if saved:
            print(f"audio saved: {saved}")


def _selftest() -> None:
    """Run every read-only tool and print what it returns.

    Exists for the frozen build specifically. pycaw reaches Core Audio through
    comtypes, which generates its COM wrappers at runtime — so it imports fine
    and then fails on the first real call, a failure that only appears in the
    packaged exe and never in development. Nothing here changes machine state.
    """
    import time

    import tools

    checks = ["battery_status", "hardware_status", "volume_status",
              "brightness_status", "radio_status"]
    lines, failures = [], 0
    for name in checks:
        started = time.time()
        try:
            result = tools.TOOL_DISPATCH[name]({}, None)
        except Exception as exc:
            failures += 1
            result = f"FAILED: {type(exc).__name__}: {exc}"
        else:
            # These tools report trouble by returning a sentence, not by raising.
            # Counting that as a pass is how a radio check that had stopped
            # working in the packaged build still reported 5/5.
            if any(bad in result.lower() for bad in ("couldn't", "could not", "failed")):
                failures += 1
        # Timings matter as much as results here: several of these shell out,
        # and a subprocess that works but takes 30s in the packaged build would
        # freeze a conversation while looking perfectly healthy in a log.
        lines.append(f"  {name:<18} [{time.time() - started:5.1f}s] {result}")
    # The features from Hey Jev and the video clipper lean on things that can work from source and still
    # be missing from the frozen exe: UI Automation's generated COM wrappers, the bundled ffmpeg binary.
    def browser_video():
        import video_clip
        found = video_clip.current_video()
        return f"reading the browser works ({'a video is open' if found else 'no browser video open'})"

    def bundled_ffmpeg():
        import os
        import imageio_ffmpeg
        path = imageio_ffmpeg.get_ffmpeg_exe()
        return f"ffmpeg present ({os.path.getsize(path) // 1_000_000} MB)"

    def new_modules():
        import importlib
        for module in ("control_panel", "dictation", "timers", "brain", "music", "convo_log", "computer", "skills", "offline", "local_brain",
                       "decision", "tool_registry", "memory_service", "browser_session", "browser_inspect",
                       "browser_intel", "watcher", "faces", "voices", "sherpa_onnx", "onnxruntime"):
            importlib.import_module(module)
        # The TRON browser needs Playwright's driver, which only a working bundle can start.
        from playwright.sync_api import sync_playwright
        sync_playwright().start().stop()
        return "control panel, dictation, timers and the browser driver load"

    def offline_speech():
        import offline
        started = time.time()
        offline.speech_model()
        offline.Voice()
        import audio_io
        if audio_io.make_echo_canceller() is None:
            raise RuntimeError("echo cancellation (livekit) is missing from the build")
        import tts
        tts.synth("Ready.")
        return f"local speech recognition, TRON's voice ({tts.VOICE}) and echo cancellation work ({time.time() - started:.1f}s)"

    for name, check in (("browser_video", browser_video), ("bundled_ffmpeg", bundled_ffmpeg),
                        ("new_modules", new_modules), ("offline_speech", offline_speech)):
        checks.append(name)
        started = time.time()
        try:
            result = check()
        except Exception as exc:
            failures += 1
            result = f"FAILED: {type(exc).__name__}: {exc}"
        lines.append(f"  {name:<18} [{time.time() - started:5.1f}s] {result}")
    lines.append(f"\n{len(checks) - failures}/{len(checks)} passed")
    report = "\n".join(lines)

    print(report)
    # A windowed build's stdout does not reliably reach a pipe, so printing
    # alone leaves this diagnostic unable to report from the one build it was
    # written to check. The file always works.
    try:
        (config_module.app_dir() / "selftest.log").write_text(report, encoding="utf-8")
    except Exception:
        pass


_instance_lock = []


def _only_instance(wait_ms: int = 15000) -> bool:
    """True when this is the only TRON running. A second launch (a double-click while TRON is already up)
    waits briefly - Restart starts the new TRON a moment before the old one exits - then gives way."""
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, True, "Local\\TRON_single_instance")
    if not handle:
        return True      # can't tell: better to run than to refuse
    if kernel32.GetLastError() == 183:      # ERROR_ALREADY_EXISTS: someone else owns it
        if kernel32.WaitForSingleObject(ctypes.c_void_p(handle), wait_ms) not in (0, 0x80):
            kernel32.CloseHandle(ctypes.c_void_p(handle))
            return False
    _instance_lock.append(handle)            # held for the life of this process
    return True


def main() -> None:
    if "--list-mics" in sys.argv:
        audio_io.print_audio_devices()
        return

    if "--panel" in sys.argv:
        _panel_only()
        return

    if "--selftest" in sys.argv:
        _selftest()
        return

    if "--test-mic" in sys.argv:
        try:
            cfg = config_module.load_config()
        except FileNotFoundError:
            # A diagnostic has to work before setup does, and in a source
            # checkout where config.json is gitignored — that is exactly when
            # someone is trying to find out why nothing works.
            cfg = SimpleNamespace(mic_device=None, wakeword_model_path="models/tron.onnx")
        # Optional device after the flag, so mics can be compared without
        # editing config.json between attempts: --test-mic 2
        position = sys.argv.index("--test-mic")
        if len(sys.argv) > position + 1:
            choice = sys.argv[position + 1]
            cfg.mic_device = int(choice) if choice.lstrip("-").isdigit() else choice
        _test_mic(cfg)
        return

    if not _only_instance():
        return      # TRON is already running: two would both answer every "hey tron"

    if not config_module.CONFIG_PATH.exists():
        setup_wizard.run_first_time_setup()
        if not config_module.CONFIG_PATH.exists():
            return      # wizard closed without saving: a choice, not a crash

    cfg = config_module.load_config()
    persona_text = config_module.resolve_path(cfg.persona_path).read_text(encoding="utf-8")

    if cfg.wake_mode not in ("hotkey", "openwakeword"):
        raise ValueError(
            f'unknown wake_mode "{cfg.wake_mode}" in config.json — use "hotkey" or "openwakeword"'
        )

    # OrbUI() must be constructed on the main thread — its run() call below blocks
    # the main thread running the GUI loop.
    orb = OrbUI()
    dash = Dashboard()
    panel = []   # the control panel, built on the GUI thread once the loop is running
    restart = []  # set by the panel's Restart button; acted on once this instance has shut down

    def request_restart() -> None:
        restart.append(True)
        _quit(triggers, tray, orb, dash)

    tray = TrayUI(
        quit_callback=lambda: _quit(triggers, tray, orb, dash),
        toggle_orb_callback=orb.toggle_visibility,
        dashboard_callback=dash.open,
        panel_callback=lambda: panel and panel[0].show(),
    )

    def on_state_change(state) -> None:
        tray.on_state_change(state)
        orb.on_state_change(state)
        if panel:
            panel[0].on_state_change(state)

    machine = TronStateMachine(
        api_key=cfg.gemini_api_key,
        model_name=cfg.model_name,
        voice_name=cfg.voice_name,
        persona_text=persona_text,
        silence_timeout_s=cfg.silence_timeout_s,
        on_state_change=on_state_change,
        on_audio_level=orb.on_audio_level,
        cfg=cfg,
    )

    _report_microphone(cfg)

    def announce(message: str) -> None:
        """Timers running out and clips finishing: a chime and a notification always, and TRON
        says it out loud as well when it isn't already busy talking or taking dictation."""
        tray.notify(message)
        try:
            import winsound
            winsound.PlaySound(r"C:\Windows\Media\Alarm01.wav",
                               winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except Exception:
            pass
        if machine.state.name in ("IDLE", "ERROR") and machine.dictation is None:
            note = ("Open this conversation yourself, without waiting to be spoken to, and tell the user "
                    f"this in one short sentence: {message} Then wait for them.")
            threading.Thread(target=lambda: machine.greet(note), daemon=True).start()

    def timer_done(timer) -> None:
        label = timer["label"]
        announce(f"Reminder: {label}." if label else
                 f"Your {timers.say_duration(timer['secs'])} timer is up.")

    timers.start_loop(timer_done, config_module.app_dir() / "memory" / "timers.json")
    video_clip.on_finished = announce
    import watcher
    watcher.on_found = announce

    def announce_call(message: str) -> None:
        # A ringing phone needs one spoken line, not a conversation; while TRON is mid-conversation the
        # notification alone is enough (it never talks over itself).
        tray.notify(message)
        if machine.state.name in ("IDLE", "ERROR") and machine.dictation is None:
            import tts
            tts.say(message)

    def _config_flag(name: str, default: bool) -> bool:
        try:
            return bool(json.loads(config_module.CONFIG_PATH.read_text(encoding="utf-8")).get(name, default))
        except Exception:
            return default

    def run_scheduled(task: str) -> None:
        note = (f"A recurring task the user set up earlier is due: {task}. Speak first, do it now with your "
                "tools, then tell them in one or two sentences what you did.")
        for _ in range(30):   # TRON busy (a conversation, dictation): try again for up to 5 minutes
            if machine.state.name in ("IDLE", "ERROR") and machine.dictation is None:
                machine.greet(note)
                return
            time.sleep(10)

    import scheduler
    scheduler.start(run_scheduled)

    try:
        mcp_servers = json.loads(config_module.CONFIG_PATH.read_text(encoding="utf-8")).get("mcp_servers")
    except Exception:
        mcp_servers = None
    try:
        hotspot_ssid = json.loads(config_module.CONFIG_PATH.read_text(encoding="utf-8")).get("hotspot_ssid")
    except Exception:
        hotspot_ssid = None
    if hotspot_ssid:
        import hotspot
        hotspot.start(hotspot_ssid, tray.notify)
    if mcp_servers:   # other apps' MCP servers become TRON's tools; slow ones never delay startup
        import mcp_hub
        threading.Thread(target=lambda: print("MCP:", mcp_hub.start(mcp_servers)), daemon=True).start()

    if _config_flag("announce_calls", True):
        import calls
        calls.start(announce_call, lambda: _config_flag("announce_messages", False))
    try:
        ancs_address = json.loads(config_module.CONFIG_PATH.read_text(encoding="utf-8")).get("ancs_address")
    except Exception:
        ancs_address = None
    if ancs_address:   # prototype: the iPhone's own notifications over Bluetooth, no Phone Link needed
        import ancs
        ancs.start(ancs_address, lambda text, event: announce_call(text) if event["kind"] == "call"
                   or _config_flag("announce_messages", False) else None)

    if cfg.wake_mode == "hotkey":
        triggers = [HotkeyTrigger(cfg.hotkey, on_trigger=machine.hotkey)]
        ready_message = f'{config_module.APP_LABEL} is running. Press {cfg.hotkey} to talk. Quit from the tray icon menu.'
    else:
        model_path = str(config_module.resolve_path(cfg.wakeword_model_path))
        triggers = [
            OpenWakeWordTrigger(model_path, on_trigger=machine.trigger, device=cfg.mic_device,
                                extra_models=wake_trigger.persona_wake_models(),
                                on_assistant=lambda a: config_module.update_config_file({"active_assistant": a})),
            # The hotkey stays live alongside the wake word. Wake-word recall
            # depends on the speaker's voice and the microphone, and a bad run
            # of detections would otherwise leave TRON with no way in at all.
            HotkeyTrigger(cfg.hotkey, on_trigger=machine.hotkey),
        ]
        ready_message = (f'{config_module.APP_LABEL} is running. Say "hey tron" (or "hey jarvis") — or press '
                         f"{cfg.hotkey} if it mishears you. Quit from the tray icon menu.")

    # The wake word that opened a conversation stays paused until it ends; dictation follows a
    # conversation, so the wake word has to listen again for "hey tron" to be able to stop it.
    machine.on_dictation_start = lambda: [t.resume() for t in triggers if hasattr(t, "resume")]

    def on_gui_ready() -> None:
        # Runs once the orb's GUI loop has started. The trigger and the tray both
        # spin up their own threads and neither touches the orb window, so
        # starting them from here is safe.
        for trigger in triggers:
            trigger.start()
        try:
            from control_panel import ControlPanel
            panel.append(ControlPanel(orb.root, machine, on_restart=request_restart))
            import browser_intel
            browser_intel.on_status = panel[0].browser_status   # "Inspecting the page...", "Verifying..."
        except Exception:
            # The assistant matters more than its settings window: log it and carry on.
            import traceback
            with open(config_module.app_dir() / "tron_error.log", "a", encoding="utf-8") as log:
                log.write("\n===== control panel failed to build =====\n" + traceback.format_exc())
        tray.start()
        if getattr(cfg, "brain", "gemini") == "local":
            import local_brain
            import tts
            tts.VOICE = cfg.local_voice
            threading.Thread(target=local_brain.warm_up, args=(cfg.local_model,), daemon=True).start()
        print(ready_message)
        # Own thread: greet() runs a whole conversation, and on_gui_ready is on
        # the orb's GUI thread — blocking it would freeze the orb for the length
        # of the greeting.
        threading.Thread(target=lambda: machine.greet(_GREETING), daemon=True).start()

    try:
        orb.run(on_gui_ready)  # blocks the main thread until orb.quit() is called
    except KeyboardInterrupt:
        _quit(triggers, tray, orb)
    if restart:
        # Only now, with this instance's hotkey, tray icon and microphone released, start the new one.
        _launch_tron()


def _launch_tron() -> None:
    """Starts a fresh, independent TRON.

    PYINSTALLER_RESET_ENVIRONMENT makes a packaged exe unpack itself afresh. Without it the new process
    reuses this one's temporary folder, which is deleted the moment this process exits."""
    import os
    import subprocess
    env = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}
    if getattr(sys, "frozen", False):
        cmd = [sys.executable]
    else:
        cmd = [sys.executable, str(Path(__file__).resolve())]
    subprocess.Popen(cmd, cwd=str(config_module.app_dir()), env=env, close_fds=True,
                     creationflags=0x00000008 | 0x00000200)  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def _panel_only() -> None:
    """`TRON.exe --panel`: just the control panel, without starting the assistant. For changing settings
    while TRON is quit, or when a broken setting keeps it from starting."""
    import tkinter as tk
    from control_panel import ControlPanel

    ctypes.windll.user32.SetProcessDPIAware()
    root = tk.Tk()
    root.withdraw()
    def start_tron():
        _launch_tron()
        root.destroy()

    panel = ControlPanel(root, on_restart=start_tron, restart_label="Start TRON")
    panel.win.protocol("WM_DELETE_WINDOW", root.destroy)
    panel.show()
    root.mainloop()


def _quit(triggers, tray: TrayUI, orb: OrbUI, dash=None) -> None:
    for trigger in triggers:
        trigger.stop()
    tray.stop()
    if dash is not None:
        dash.stop()
    orb.quit()  # unblocks the main thread's orb.run() call in main(), letting the process exit


def _run_with_crash_log() -> None:
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # Appended, like conversation failures: overwriting erased every
        # earlier entry the moment startup crashed once.
        try:
            stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(state_manager.error_log_path(), "a", encoding="utf-8") as log:
                log.write(f"\n===== startup crashed at {stamp} =====\n")
                log.write(traceback.format_exc())
        except Exception:
            pass
        raise


if __name__ == "__main__":
    _run_with_crash_log()
