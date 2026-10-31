# computer.py
"""TRON working the PC step by step: see what's on screen, click it, type, press keys — then look again.

The same loop an agent like Claude in Chrome uses inside a browser, here for any Windows app. Instead of
guessing pixel positions from a screenshot (which a voice model does badly), the window's controls are read
through Windows UI Automation — the technique that already reads the browser's address bar and presses
Spotify's play button — and handed to Gemini as a numbered list:

    1. Button "New folder"   2. ListItem "report.docx"   3. Edit "Search Documents" ...

Gemini then says click_element(2), and TRON clicks that exact control. Clicks go through the control's own
"Invoke" action when it has one (no mouse movement at all), and a real click at its centre otherwise.

find_file covers the most common case without any clicking: "open the file called budget" searches the
usual folders and opens the best match.
"""
import ctypes
import difflib
import os
import time
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.windll.user32

_KINDS = {  # UIA control type id -> what we call it
    50000: "Button", 50002: "CheckBox", 50003: "ComboBox", 50004: "Edit", 50005: "Hyperlink",
    50007: "ListItem", 50011: "MenuItem", 50013: "RadioButton", 50019: "TabItem", 50024: "TreeItem",
    50029: "DataItem", 50015: "Slider",
}
_MAX = 60
_elements: dict = {}   # number -> UIA element, from the last screen_elements call
_SEARCH_DIRS = ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music", "OneDrive")


def _uia():
    import comtypes.client
    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen import UIAutomationClient as lib
    return comtypes.client.CreateObject("{ff48dba4-60ef-4201-aa87-54103eef594e}", interface=lib.IUIAutomation), lib


def _target_window(app: str):
    import desktop_control
    if app:
        hits = desktop_control._app_hits(app)
        if hits:
            return hits[0][0], hits[0][1]
    hwnd = user32.GetForegroundWindow()
    n = user32.GetWindowTextLengthW(hwnd)
    title = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, title, n + 1)
    return hwnd, title.value


def screen_elements(args, cfg=None) -> str:
    """Tool: the clickable controls in the front window (or a named app's), numbered."""
    app = str(args.get("app", "")).strip()
    hwnd, title = _target_window(app)
    if not hwnd:
        return "there's no window in front, sir"
    uia, lib = _uia()
    root = uia.ElementFromHandle(hwnd)
    root.FindAll(lib.TreeScope_Descendants, uia.CreateTrueCondition())   # Chromium apps build the tree on request
    found = uia.ElementFromHandle(hwnd).FindAll(lib.TreeScope_Descendants, uia.CreateTrueCondition())
    _elements.clear()
    lines, seen = [], set()
    for i in range(found.Length):
        element = found.GetElement(i)
        kind = _KINDS.get(element.CurrentControlType)
        name = (element.CurrentName or "").strip()
        if not kind or not name or element.CurrentIsOffscreen or not element.CurrentIsEnabled:
            continue
        key = (kind, name)
        if key in seen:
            continue
        seen.add(key)
        number = len(_elements) + 1
        _elements[number] = element
        lines.append(f'{number}. {kind} "{name[:60]}"')
        if number >= _MAX:
            lines.append("(more not shown; scroll or name the app to narrow it)")
            break
    if not lines:
        return f'"{title}" shows nothing I can click, sir'
    return f'Window "{title}":\n' + "\n".join(lines)


def element_name(number) -> str:
    element = _elements.get(int(number)) if str(number).isdigit() else None
    try:
        return element.CurrentName or "" if element is not None else ""
    except Exception:
        return ""


def _real_click(element, double=False) -> None:
    r = element.CurrentBoundingRectangle
    x, y = (r.left + r.right) // 2, (r.top + r.bottom) // 2
    back = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(back))
    user32.SetCursorPos(x, y)
    time.sleep(0.25)
    for _ in range(2 if double else 1):
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.04)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        time.sleep(0.08)
    time.sleep(0.15)
    user32.SetCursorPos(back.x, back.y)


def click_element(args, cfg=None) -> str:
    """Tool: click item N from the last screen_elements list. double=True opens files and rows."""
    try:
        number = int(args.get("number"))
    except (TypeError, ValueError):
        return "which number should I click, sir? Call screen_elements first"
    element = _elements.get(number)
    if element is None:
        return "that number isn't on the list any more; call screen_elements again"
    double = bool(args.get("double", False))
    name = element_name(number)
    _uia_obj, lib = _uia()
    try:
        if not double:
            pattern = element.GetCurrentPattern(lib.UIA_InvokePatternId)
            if pattern:
                pattern.QueryInterface(lib.IUIAutomationInvokePattern).Invoke()
                return f'clicked "{name}". Call screen_elements to see what changed'
    except Exception:
        pass
    try:
        _real_click(element, double)
    except Exception as exc:
        return f"I couldn't click that, sir ({exc})"
    return f'{"double-" if double else ""}clicked "{name}". Call screen_elements to see what changed'


def type_text(args, cfg=None) -> str:
    """Tool: type into whatever has focus (click a text box first if needed)."""
    import keyboard
    text = str(args.get("text", ""))
    if not text:
        return "what should I type, sir?"
    keyboard.write(text, delay=0.01)
    if args.get("enter"):
        keyboard.send("enter")
    return f'typed "{text[:60]}"' + (" and pressed Enter" if args.get("enter") else "")


def press_keys(args, cfg=None) -> str:
    """Tool: a key or shortcut, e.g. 'enter', 'ctrl+l', 'alt+f4' is refused."""
    import keyboard
    keys = str(args.get("keys", "")).strip().lower()
    if not keys:
        return "which keys, sir?"
    if keys.replace(" ", "") in ("alt+f4", "ctrl+alt+delete", "ctrl+alt+del"):
        return "I won't press that one; use close_app or window_action instead"
    keyboard.send(keys)
    return f"pressed {keys}"


def scroll(args, cfg=None) -> str:
    direction = str(args.get("direction", "down")).lower()
    amount = max(1, min(20, int(args.get("amount", 5) or 5)))
    for _ in range(amount):
        user32.mouse_event(0x0800, 0, 0, (-120 if direction == "down" else 120), 0)
        time.sleep(0.02)
    return f"scrolled {direction}"


def find_file(args, cfg=None) -> str:
    """Tool: find a file or folder by (part of) its name in the usual folders, and open the best match."""
    query = str(args.get("name", "")).strip().lower()
    if not query:
        return "which file, sir?"
    home = Path.home()
    roots = [home / d for d in _SEARCH_DIRS if (home / d).exists()]
    candidates = []
    deadline = time.time() + 8
    for root in roots:
        for folder, dirs, files in os.walk(root):
            if time.time() > deadline:
                break
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "AppData", "__pycache__")]
            for name in files + dirs:
                stem = os.path.splitext(name)[0].lower()
                if query in stem or difflib.SequenceMatcher(None, query, stem).ratio() > 0.75:
                    candidates.append(Path(folder) / name)
    if not candidates:
        return f'I couldn\'t find anything called "{query}" in your Desktop, Documents, Downloads, Pictures, Videos or Music, sir'

    def score(path):
        stem = path.stem.lower()
        return (stem == query, query in stem, -len(stem), path.stat().st_mtime if path.exists() else 0)

    candidates.sort(key=score, reverse=True)
    best = candidates[0]
    if args.get("open", True):
        os.startfile(str(best))
    others = [str(p) for p in candidates[1:4]]
    return f"opened {best}" + (f". Other matches: {'; '.join(others)}" if others else "")


DECLARATIONS = [
    {
        "name": "screen_elements",
        "description": (
            "See what can be clicked in the window in front (or in a named app): a numbered list of its "
            "buttons, files, links, menu items and text boxes. Use it for any step-by-step task on the PC, "
            "then click_element, type_text or press_keys, then call it again to check the result."
        ),
        "parameters": {"type": "object", "properties": {
            "app": {"type": "string", "description": "Optional app to look at instead of the front window."}}},
    },
    {
        "name": "click_element",
        "description": "Click item number N from the latest screen_elements list. double=true to open a file or folder.",
        "parameters": {"type": "object", "properties": {
            "number": {"type": "integer"},
            "double": {"type": "boolean", "description": "Double-click, e.g. to open a file in File Explorer."}},
            "required": ["number"]},
    },
    {
        "name": "type_text",
        "description": "Type text into the focused field (click it first with click_element if needed).",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"},
            "enter": {"type": "boolean", "description": "Press Enter afterwards."}},
            "required": ["text"]},
    },
    {
        "name": "press_keys",
        "description": "Press a key or shortcut, e.g. 'enter', 'tab', 'ctrl+l', 'ctrl+s', 'win+e'.",
        "parameters": {"type": "object", "properties": {"keys": {"type": "string"}}, "required": ["keys"]},
    },
    {
        "name": "scroll",
        "description": "Scroll the window under the mouse up or down.",
        "parameters": {"type": "object", "properties": {
            "direction": {"type": "string", "enum": ["up", "down"]},
            "amount": {"type": "integer", "description": "1 to 20, default 5."}},
            "required": ["direction"]},
    },
    {
        "name": "find_file",
        "description": (
            "Find a file or folder by name in Desktop, Documents, Downloads, Pictures, Videos and Music and "
            "open it, e.g. 'open my resume', 'open the budget spreadsheet'. Faster than clicking through "
            "File Explorer; use it first for 'open the file called X'."
        ),
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "The file's name or part of it."},
            "open": {"type": "boolean", "description": "false to only find it. Default true."}},
            "required": ["name"]},
    },
]

DISPATCH = {"screen_elements": screen_elements, "click_element": click_element, "type_text": type_text,
            "press_keys": press_keys, "scroll": scroll, "find_file": find_file}
