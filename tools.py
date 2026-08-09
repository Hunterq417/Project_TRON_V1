# tools.py
import urllib.parse
import webbrowser

import app_index
import email_client
import media_control

_APP_INDEX_CACHE = None


def _get_app_index():
    global _APP_INDEX_CACHE
    if _APP_INDEX_CACHE is None:
        _APP_INDEX_CACHE = app_index.build_index()
    return _APP_INDEX_CACHE


def _open_target(args, cfg):
    name = args["name"]
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


TOOL_DISPATCH = {
    "open_target": _open_target,
    "web_search": _web_search,
    "media_play_pause": _media_play_pause,
    "media_next": _media_next,
    "media_previous": _media_previous,
    "media_seek": _media_seek,
    "draft_email": _draft_email,
    "send_email": _send_email,
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
]
