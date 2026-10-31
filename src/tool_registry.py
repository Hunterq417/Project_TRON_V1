# tool_registry.py
"""Every TRON tool with what code needs to know about it: its capability, category, risk, whether it
changes anything, whether that reaches outside the PC, and whether it needs the user's spoken yes.

The confirmation policy lives here, in one place (brain.Guard enforces it). The model never decides
whether something is risky: it proposes a tool, and this table says what that tool is.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolMeta:
    name: str
    capability: str
    category: str                 # READ SEARCH COMPUTE TRANSFORM CREATE UPDATE DELETE SEND PUBLISH SYSTEM_CONTROL
    risk: str = "low"             # none low medium high critical
    side_effect: bool = True      # changes something on the PC
    external: bool = False        # the effect leaves the PC (an email sent)
    reversible: bool = True
    requires_confirmation: bool = False
    timeout_seconds: int = 30


def _t(name, capability, category, risk="low", side_effect=True, external=False, reversible=True,
       confirm=False, timeout=30):
    return ToolMeta(name, capability, category, risk, side_effect, external, reversible, confirm, timeout)


def _read(name, capability, category="READ"):
    return _t(name, capability, category, "none", side_effect=False)


TOOLS = {m.name: m for m in (
    # apps and windows
    _t("open_target", "app_control", "UPDATE"), _t("close_app", "app_control", "UPDATE", "medium"),
    _t("focus_app", "app_control", "UPDATE"), _t("minimize_app", "app_control", "UPDATE"),
    _read("list_windows", "app_control"), _t("window_action", "app_control", "UPDATE"),
    # music and media
    _t("play_music", "music", "UPDATE", timeout=30), _t("media_play_pause", "music", "UPDATE"),
    _t("media_next", "music", "UPDATE"), _t("media_previous", "music", "UPDATE"),
    _t("media_seek", "music", "UPDATE"),
    # sound
    _t("set_volume", "audio", "UPDATE"), _t("change_volume", "audio", "UPDATE"), _t("set_mute", "audio", "UPDATE"),
    _read("volume_status", "audio"), _t("set_app_volume", "audio", "UPDATE"),
    # display
    _t("set_brightness", "display", "UPDATE"), _read("brightness_status", "display"),
    _t("set_dark_mode", "display", "UPDATE"),
    # connectivity: turning Wi-Fi off can cut TRON off mid-task (Guard asks for that case)
    _t("set_radio", "connectivity", "SYSTEM_CONTROL", "medium"), _read("radio_status", "connectivity"),
    # status and time
    _read("battery_status", "system_status"), _read("hardware_status", "system_status"),
    _read("current_time", "system_status", "COMPUTE"),
    # power
    _t("lock_pc", "power", "SYSTEM_CONTROL"),
    _t("sleep_pc", "power", "SYSTEM_CONTROL", "high", confirm=True),
    _t("shutdown_pc", "power", "SYSTEM_CONTROL", "high", reversible=False, confirm=True),
    _t("restart_pc", "power", "SYSTEM_CONTROL", "high", reversible=False, confirm=True),
    _t("cancel_shutdown", "power", "SYSTEM_CONTROL"),
    # web
    _t("web_search", "web", "SEARCH"), _t("open_website", "web", "UPDATE"), _t("new_tab", "web", "UPDATE"),
    # files
    _t("find_file", "files", "SEARCH", side_effect=False),
    # email: a draft stays on the PC; sending is the external effect
    _t("draft_email", "email", "CREATE", side_effect=False),
    _t("send_email", "email", "SEND", "high", external=True, reversible=False, confirm=True),
    # memory
    _t("remember_fact", "memory", "UPDATE"), _t("forget_fact", "memory", "DELETE", "medium"),
    _read("recall_activity", "memory"), _t("forget_recent_activity", "memory", "DELETE", "medium"),
    # timers
    _t("set_timer", "timers", "CREATE"), _read("check_timers", "timers"), _t("cancel_timer", "timers", "DELETE"),
    # dictation
    _t("start_dictation", "dictation", "UPDATE"),
    # seeing and driving the screen (Guard asks before risky clicks such as Delete or Send)
    _read("screen_elements", "screen_control"), _t("click_element", "screen_control", "UPDATE", "medium"),
    _t("type_text", "screen_control", "UPDATE", "medium"), _t("press_keys", "screen_control", "UPDATE", "medium"),
    _t("scroll", "screen_control", "UPDATE"), _read("look_at_screen", "vision"), _read("look_via_camera", "vision"),
    # video
    _t("clip_video", "video", "CREATE", timeout=600),
    # security
    _t("scan_for_malware", "security", "READ", side_effect=False, timeout=60), _read("check_scan_status", "security"),
    # skills
    _read("use_skill", "skills"),
    # browser video and background watching
    _t("video_control", "video", "UPDATE"), _t("watch_until", "watching", "READ", side_effect=False),
    _read("check_watches", "watching"), _t("stop_watching", "watching", "UPDATE"),
    # faces: the camera, only when Settings allows it (faces.py checks camera_enabled)
    _t("enroll_face", "faces", "CREATE"), _read("who_is_here", "faces"), _t("forget_face", "faces", "DELETE", "medium"),
    _read("known_faces", "faces"),
    _t("enroll_voice", "voices", "CREATE"), _read("who_is_speaking", "voices"),
    _t("forget_voice", "voices", "DELETE", "medium"), _read("known_voices", "voices"),
    # the TRON browser (risky page clicks also need a spoken yes: brain.risky_click)
    _t("browser_media", "browser", "UPDATE"), _t("browser_page", "browser", "UPDATE", "medium"),
    _t("open_tron_browser", "browser", "UPDATE"), _t("stop_browser_task", "browser", "UPDATE"),
    _read("browser_knowledge", "browser"), _t("forget_browser_knowledge", "browser", "DELETE"),
)}


def get(name: str):
    return TOOLS.get(name)


def confirmation_tools() -> set:
    return {name for name, meta in TOOLS.items() if meta.requires_confirmation}


def capabilities() -> dict:
    """capability -> tool names, for the panel and the decision log."""
    out = {}
    for meta in TOOLS.values():
        out.setdefault(meta.capability, []).append(meta.name)
    return out
