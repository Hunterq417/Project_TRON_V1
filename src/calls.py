# calls.py
"""JARVIS's call announcer: "Boss, Mayukh is calling you on WhatsApp".

An iPhone app can't see calls from other apps (iOS doesn't allow it), so there is no phone plugin for this.
Windows can: Phone Link mirrors the iPhone's calls and notifications to the PC as Windows notifications, and
WhatsApp Desktop posts its own. TRON reads Windows' notification database read-only, never changes it, and
says who is calling and on what. Messages are announced only when "announce_messages" is on (off by default:
they'd interrupt games and calls).
"""
import html
import os
import re
import sqlite3
import threading
import time
from pathlib import Path

DB = Path(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Notifications\wpndatabase.db"))
_CALL = re.compile(r"(incoming (voice |video |audio |facetime )?call|is (video )?calling|calling you|"
                   r"wants to (voice |video )?call)", re.I)
_APPS = (("whatsapp", "WhatsApp"), ("telegram", "Telegram"), ("teams", "Teams"), ("instagram", "Instagram"),
         ("facetime", "FaceTime"), ("signal", "Signal"), ("skype", "Skype"), ("discord", "Discord"),
         ("messenger", "Messenger"), ("slack", "Slack"), ("snapchat", "Snapchat"))
_SOURCES = ("yourphone", "whatsapp", "telegram", "teams", "skype", "discord", "signal", "messenger", "slack")


def _texts(payload: str) -> list:
    return [html.unescape(re.sub(r"<[^>]+>", "", t)).strip()
            for t in re.findall(r"<text[^>]*>(.*?)</text>", payload, re.S) if t.strip()]


def parse(handler: str, payload: str) -> dict:
    """{"kind": "call"|"message", "who", "app", "video"} for a phone or chat notification, else {}."""
    hay = handler.lower()
    if not any(s in hay for s in _SOURCES):
        return {}
    texts = _texts(payload)
    if not texts:
        return {}
    joined = " ".join(texts)
    app = next((name for key, name in _APPS if key in hay or key in joined.lower()), "your phone")
    app_words = {key for key, _ in _APPS} | {app.lower()}
    if _CALL.search(joined):
        names = [t for t in texts if not _CALL.fullmatch(t.strip(" .…")) and t.lower() not in app_words]
        who = _CALL.sub("", names[0] if names else "").strip(" -:.…") or "Someone"
        return {"kind": "call", "who": who, "app": app, "video": "video" in joined.lower() or "facetime" in hay}
    if "badge" in payload[:20] or len(texts) < 2:
        return {}
    who = texts[0] if texts[0].lower() not in app_words else texts[1]
    return {"kind": "message", "who": who, "app": app, "video": False}


def sentence(event: dict) -> str:
    on = "" if event["app"] == "your phone" else f" on {event['app']}"
    if event["kind"] == "call":
        return f"Boss, {event['who']} is {'video ' if event['video'] else ''}calling you{on}."
    return f"Boss, a message from {event['who']}{on}."


def _read(after: int) -> list:
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=2) as c:
        return c.execute("SELECT n.Id, h.PrimaryId, n.Payload FROM Notification n JOIN NotificationHandler h "
                         "ON n.HandlerId = h.RecordId WHERE n.Id > ? AND n.Type = 'toast' ORDER BY n.Id",
                         (after,)).fetchall()


def start(announce, cfg_messages=lambda: False) -> None:
    """Watches for new call (and optionally message) notifications and calls announce(sentence)."""
    def loop():
        try:
            last = max([row[0] for row in _read(0)], default=0)   # only what arrives from now on
        except Exception:
            return   # no notification database (Windows 10 or a locked-down PC): nothing to watch
        recent = {}
        while True:
            time.sleep(1)
            try:
                rows = _read(last)
            except Exception:
                continue
            for rid, handler, payload in rows:
                last = max(last, rid)
                text = payload.decode("utf-8", "ignore") if isinstance(payload, bytes) else str(payload or "")
                event = parse(handler, text)
                if not event or (event["kind"] == "message" and not cfg_messages()):
                    continue
                key = (event["kind"], event["who"], event["app"])
                if time.time() - recent.get(key, 0) < 30:
                    continue   # a ringing call re-posts its notification; say it once
                recent[key] = time.time()
                try:
                    announce(sentence(event))
                except Exception:
                    pass
    threading.Thread(target=loop, daemon=True).start()
