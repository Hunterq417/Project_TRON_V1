# tools.py
import urllib.parse
import webbrowser

import app_index
import email_client
import media_control
import memory
import security_scan
import system_control

_APP_INDEX_CACHE = None


def _get_app_index():
    global _APP_INDEX_CACHE
    if _APP_INDEX_CACHE is None:
        _APP_INDEX_CACHE = app_index.build_index()
    return _APP_INDEX_CACHE


def _open_target(args, cfg):
    name = args["name"]
    if app_index.try_direct_launch(name):
        return f'opened "{name}"'
    path = app_index.resolve(name, _get_app_index())
    if path is None:
        return f'could not find anything called "{name}", sir'
    app_index.launch(path)
    return f'opened "{path.stem}"'


def _web_search(args, cfg):
    query = args["query"]
    url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
    webbrowser.open(url)
    return f'opened a search for "{query}"'


def _media_play_pause(args, cfg):
    return media_control.play_pause()


def _media_next(args, cfg):
    return media_control.next_track()


def _media_previous(args, cfg):
    return media_control.previous_track()


def _media_seek(args, cfg):
    return media_control.seek(args["direction"], args.get("seconds", 10))


def _draft_email(args, cfg):
    return email_client.draft_email(args["to"], args["subject"], args["body"])


def _send_email(args, cfg):
    return email_client.send_email(
        args["to"], args["subject"], args["body"],
        smtp_host=cfg.smtp_host, smtp_port=cfg.smtp_port,
        smtp_user=cfg.smtp_user, smtp_app_password=cfg.smtp_app_password,
    )


def _recall_activity(args, cfg):
    context = memory.recent_context()
    if not context:
        return "nothing logged yet, sir"
    return context


def _forget_recent_activity(args, cfg):
    memory.clear()
    return "recent activity log cleared, sir"


def _scan_for_malware(args, cfg):
    return security_scan.scan_for_malware(args, cfg)


def _check_scan_status(args, cfg):
    return security_scan.check_scan_status(args, cfg)


def _shutdown_pc(args, cfg):
    return system_control.shutdown_pc(args, cfg)


def _restart_pc(args, cfg):
    return system_control.restart_pc(args, cfg)


def _cancel_shutdown(args, cfg):
    return system_control.cancel_shutdown(args, cfg)


TOOL_DISPATCH = {
    "open_target": _open_target,
    "web_search": _web_search,
    "media_play_pause": _media_play_pause,
    "media_next": _media_next,
    "media_previous": _media_previous,
    "media_seek": _media_seek,
    "draft_email": _draft_email,
    "send_email": _send_email,
    "recall_activity": _recall_activity,
    "forget_recent_activity": _forget_recent_activity,
    "scan_for_malware": _scan_for_malware,
    "check_scan_status": _check_scan_status,
    "shutdown_pc": _shutdown_pc,
    "restart_pc": _restart_pc,
    "cancel_shutdown": _cancel_shutdown,
}

TOOL_DECLARATIONS = [
    {
        "name": "open_target",
        "description": "Open an application, file, photo, video, or game by name.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "What to open, as spoken by the user."}
            },
            "required": ["name"],
        },
    },
    {
        "name": "web_search",
        "description": "Search the web for a query and open the results in the browser.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "media_play_pause",
        "description": "Toggle play/pause on whatever media is currently playing.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "media_next",
        "description": "Skip to the next track.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "media_previous",
        "description": "Go to the previous track.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "media_seek",
        "description": (
            "Seek forward or backward in the currently focused video/media player, by "
            "roughly the given number of seconds (best-effort, capped at about 60 seconds)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["forward", "backward"]},
                "seconds": {
                    "type": "integer",
                    "description": "Roughly how many seconds to skip. Defaults to 10.",
                },
            },
            "required": ["direction"],
        },
    },
    {
        "name": "draft_email",
        "description": (
            "Compose an email draft and return its text for you to read back to the user. "
            "Always call this before send_email, read the draft back verbatim, and wait "
            "for explicit confirmation before calling send_email."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "send_email",
        "description": (
            "Actually send an email. Only call this after draft_email was called, the "
            "draft was read back to the user, and the user explicitly confirmed sending it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "recall_activity",
        "description": (
            "Get a summary of recent actions TRON has taken (apps opened, searches, "
            "emails, etc.) to answer questions like 'what have you been up to'."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "forget_recent_activity",
        "description": "Clear TRON's recent activity log. Use when the user explicitly asks to forget or clear recent activity.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "scan_for_malware",
        "description": (
            "Start a Windows Defender quick scan for malware/viruses. Runs in the "
            "background; use check_scan_status later to see if it finished."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "check_scan_status",
        "description": "Check whether the most recent malware scan has finished and what it found.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "shutdown_pc",
        "description": (
            "Shut down the computer after a short delay. ALWAYS ask the user to confirm "
            "out loud first — never call this on an ambiguous, overheard, or unconfirmed request."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "restart_pc",
        "description": (
            "Restart the computer after a short delay. ALWAYS ask the user to confirm "
            "out loud first — never call this on an ambiguous, overheard, or unconfirmed request."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "cancel_shutdown",
        "description": "Cancel a pending shutdown or restart previously scheduled by shutdown_pc or restart_pc.",
        "parameters": {"type": "object", "properties": {}},
    },
]

_LOOK_AT_SCREEN_DECLARATION = {
    "name": "look_at_screen",
    "description": (
        "Capture and look at what's currently on the user's screen, then describe it. "
        'Say something like "let me take a look, sir" before calling this.'
    ),
    "parameters": {"type": "object", "properties": {}},
}

_LOOK_VIA_CAMERA_DECLARATION = {
    "name": "look_via_camera",
    "description": (
        "Capture a frame from the webcam and describe what's seen. "
        'Say something like "let me take a look, sir" before calling this.'
    ),
    "parameters": {"type": "object", "properties": {}},
}

VISION_TOOL_NAMES = {"look_at_screen", "look_via_camera"}


def declarations_for(cfg) -> list:
    """The tool schema actually sent to Gemini Live — vision tools are only
    included if the corresponding config flag is on. This is the structural
    enforcement of the camera/screen consent model: a tool Gemini was never
    told about is a tool it cannot call."""
    declarations = list(TOOL_DECLARATIONS)
    if cfg is not None and getattr(cfg, "screen_enabled", False):
        declarations.append(_LOOK_AT_SCREEN_DECLARATION)
    if cfg is not None and getattr(cfg, "camera_enabled", False):
        declarations.append(_LOOK_VIA_CAMERA_DECLARATION)
    return declarations
