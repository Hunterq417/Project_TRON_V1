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
