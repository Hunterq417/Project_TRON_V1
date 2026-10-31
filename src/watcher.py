# watcher.py
"""Watch an app until something happens, then say so: "tell me when the Valorant update finishes".

A background thread looks at the app's window every few seconds (a capture of that window, even when it's
behind others, plus any text the app shows to Windows) and asks the local vision model whether the
condition is true yet. It only announces when the model says yes twice in a row with the same visible
evidence: once, a single look claimed an update had finished while its bar was still filling.
"""
import ctypes
import io
import json
import threading
import time
from ctypes import wintypes

on_found = print       # main.py points this at TRON's announce(): a chime, a notification and speech
_watches: list = []
_lock = threading.Lock()
PROMPT = ("You are checking an app's window for the user. Condition: \"{condition}\".\n"
          "Look at the screenshot{text}. Is the condition true right now? Judge only from what you can see. "
          "evidence: the exact words or the specific thing on screen that shows it (or why not).")
SCHEMA = {"type": "object", "properties": {"met": {"type": "boolean"}, "evidence": {"type": "string"}},
          "required": ["met", "evidence"]}


def capture(hwnd) -> bytes:
    """A JPEG of the window, drawn by the window itself, so other windows on top don't matter."""
    from PIL import Image
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    rect = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0 or user32.IsIconic(wintypes.HWND(hwnd)):
        raise RuntimeError("the window is minimised")
    window_dc = user32.GetWindowDC(wintypes.HWND(hwnd))
    mem_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, w, h)
    gdi32.SelectObject(mem_dc, bitmap)
    try:
        user32.PrintWindow(wintypes.HWND(hwnd), mem_dc, 2)   # PW_RENDERFULLCONTENT: Chromium/CEF apps too
        header = (ctypes.c_uint32 * 10)(40, w, -h, 1 | (32 << 16), 0, 0, 0, 0, 0, 0)   # BITMAPINFOHEADER
        buffer = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(mem_dc, bitmap, 0, h, buffer, header, 0)
    finally:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(wintypes.HWND(hwnd), window_dc)
    image = Image.frombuffer("RGB", (w, h), buffer, "raw", "BGRX", 0, 1)
    image.thumbnail((1280, 1280))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=85)
    return out.getvalue()


def _window_text(hwnd) -> str:
    import music
    uia, lib = music._uia()
    found = uia.ElementFromHandle(hwnd).FindAll(lib.TreeScope_Descendants, uia.CreateTrueCondition())
    names = []
    for i in range(min(found.Length, 400)):
        try:
            name = (found.GetElement(i).CurrentName or "").strip()
        except Exception:
            continue
        if name and name not in names:
            names.append(name)
    return " | ".join(names)[:2000]


def look(hwnd, condition: str, chat=None) -> dict:
    """One check: {"met": bool, "evidence": str}. chat(messages, schema) -> reply text (the local model)."""
    import base64
    if chat is None:
        import local_brain
        if not local_brain.ensure_server():
            raise RuntimeError("the local brain is switched off in Settings, and watching needs it")
        provider = local_brain.OllamaProvider()
        chat = lambda messages, schema: provider.chat(messages, format=schema, temperature=0).get("content", "")
    text = _window_text(hwnd)
    prompt = PROMPT.format(condition=condition, text=f" and the window's text ({text})" if len(text) > 40 else "")
    reply = chat([{"role": "user", "content": prompt, "images": [base64.b64encode(capture(hwnd)).decode()]}],
                 SCHEMA)
    answer = json.loads(reply)
    return {"met": bool(answer.get("met")), "evidence": str(answer.get("evidence", ""))[:200]}


def _run(watch, check, sleep):
    yes = 0
    while not watch["stop"].is_set() and time.time() < watch["until"]:
        try:
            answer = check()
            watch["last"] = answer["evidence"]
            yes = yes + 1 if answer["met"] else 0
            if yes >= 2:   # twice in a row: one hopeful look isn't proof
                on_found(f"{watch['label']}: {answer['evidence']}".rstrip(": "))
                break
        except Exception as exc:
            watch["last"] = f"couldn't look: {exc}"
            if "minimised" in str(exc) or "no longer" in str(exc):
                on_found(f"I stopped watching {watch['app']}: {exc}.")
                break
        sleep(watch["every"])
    else:
        if not watch["stop"].is_set():
            on_found(f"I've been watching {watch['app']} for {watch['minutes']} minutes and it hasn't happened yet: "
                     f"{watch['condition']}.")
    with _lock:
        if watch in _watches:
            _watches.remove(watch)


def watch_until(args, cfg=None, check=None, sleep=time.sleep) -> str:
    """Tool: watch an app's window in the background and tell the user when the condition is true."""
    import desktop_control
    app = str(args.get("app", "")).strip()
    condition = str(args.get("condition", "")).strip()
    if not app or not condition:
        return "which app should I watch, and for what, sir?"
    hits = desktop_control._app_hits(app)
    if not hits:
        return f"I can't see a window for {app}, sir. Open it first."
    hwnd, title, _proc = hits[0]
    every = max(10, int(args.get("every_seconds") or 20))
    minutes = max(1, int(args.get("give_up_minutes") or 120))
    watch = {"app": title, "condition": condition, "every": every, "minutes": minutes, "last": "",
             "until": time.time() + minutes * 60, "stop": threading.Event(),
             "label": str(args.get("announce") or f"Done: {condition}").strip()}
    with _lock:
        _watches.append(watch)
    threading.Thread(target=_run, args=(watch, check or (lambda: look(hwnd, condition)), sleep), daemon=True).start()
    return (f"watching {title} every {every} seconds; I'll tell you when {condition}, sir. "
            "Nothing is confirmed yet, so don't say it has happened.")


def check_watches(args=None, cfg=None) -> str:
    with _lock:
        if not _watches:
            return "I'm not watching anything, sir"
        return "; ".join(f"watching {w['app']} for: {w['condition']} (last look: {w['last'] or 'not yet'})"
                         for w in _watches)


def stop_watching(args=None, cfg=None) -> str:
    with _lock:
        n = len(_watches)
        for w in _watches:
            w["stop"].set()
        _watches.clear()
    return f"stopped {n} watch{'es' if n != 1 else ''}, sir" if n else "I wasn't watching anything, sir"
