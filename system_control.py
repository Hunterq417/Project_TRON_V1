# system_control.py
import subprocess

_DELAY_SECONDS = 30


def shutdown_pc(args, cfg) -> str:
    return _schedule("/s", "shutting down")


def restart_pc(args, cfg) -> str:
    return _schedule("/r", "restarting")


def _schedule(flag: str, verb: str) -> str:
    try:
        subprocess.run(
            ["shutdown", flag, "/t", str(_DELAY_SECONDS), "/c", f"TRON is {verb} this PC, as requested."],
            check=True, capture_output=True, text=True,
        )
    except Exception as exc:
        return f"couldn't start the {verb}, sir: {exc}"
    return f"{verb} in {_DELAY_SECONDS} seconds, sir — say \"cancel shutdown\" to stop it"


def cancel_shutdown(args, cfg) -> str:
    try:
        subprocess.run(["shutdown", "/a"], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError:
        return "there's no pending shutdown to cancel, sir"
    except Exception as exc:
        return f"couldn't cancel it, sir: {exc}"
    return "cancelled, sir"
