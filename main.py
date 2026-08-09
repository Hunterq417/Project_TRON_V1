# main.py
import traceback

import config as config_module
import setup_wizard
from orb_ui import OrbUI
from state_manager import TronStateMachine
from wake_trigger import HotkeyTrigger, OpenWakeWordTrigger
from tray_ui import TrayUI


def main() -> None:
    if not config_module.CONFIG_PATH.exists():
        setup_wizard.run_first_time_setup()

    cfg = config_module.load_config()
    persona_text = config_module.resolve_path(cfg.persona_path).read_text(encoding="utf-8")

    if cfg.wake_mode not in ("hotkey", "openwakeword"):
        raise ValueError(
            f'unknown wake_mode "{cfg.wake_mode}" in config.json — use "hotkey" or "openwakeword"'
        )

    # OrbUI() must be constructed on the main thread — its run() call below blocks
    # the main thread running pywebview's GUI loop, which pywebview requires.
    orb = OrbUI()
    tray = TrayUI(
        quit_callback=lambda: _quit(trigger, tray, orb),
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
        on_audio_level=orb.on_audio_level,
        cfg=cfg,
    )

    if cfg.wake_mode == "hotkey":
        trigger = HotkeyTrigger(cfg.hotkey, on_trigger=machine.trigger)
        ready_message = f'TRON is running. Press {cfg.hotkey} to talk. Quit from the tray icon menu.'
    else:
        model_path = str(config_module.resolve_path(cfg.wakeword_model_path))
        trigger = OpenWakeWordTrigger(model_path, on_trigger=machine.trigger)
        ready_message = 'TRON is running. Say "hey tron" to talk. Quit from the tray icon menu.'

    def on_gui_ready() -> None:
        # Runs on its own thread once pywebview's GUI loop has started — trigger
        # and tray don't touch the native orb window, so they're safe to start here.
        trigger.start()
        tray.start()
        print(ready_message)

    try:
        orb.run(on_gui_ready)  # blocks the main thread until orb.quit() is called
    except KeyboardInterrupt:
        _quit(trigger, tray, orb)


def _quit(trigger, tray: TrayUI, orb: OrbUI) -> None:
    trigger.stop()
    tray.stop()
    orb.quit()  # unblocks the main thread's orb.run() call in main(), letting the process exit


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
