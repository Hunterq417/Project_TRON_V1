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
import re
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
_listed_names: dict = {}   # number -> the name it had when listed: a page that redrew reuses elements
_SEARCH_DIRS = ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music", "OneDrive")


def _uia():
    import comtypes.client
    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen import UIAutomationClient as lib
    return comtypes.client.CreateObject("{ff48dba4-60ef-4201-aa87-54103eef594e}", interface=lib.IUIAutomation), lib


_TRAY_WORDS = ("tray", "hidden icon", "notification area", "system tray")


def _overflow_window():
    """Windows' hidden-icons pop-up, repaired if something minimised it (it then never opens again)."""
    hwnd = user32.FindWindowW("TopLevelWindowForOverflowXamlIsland", None)
    if hwnd and user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)    # SW_RESTORE
        user32.ShowWindow(hwnd, 0)    # SW_HIDE: closed, the way Windows keeps it
    return hwnd


def show_hidden_icons(args=None, cfg=None) -> str:
    """Tool: open the taskbar's hidden-icons tray (the ^ arrow, "mini tray")."""
    _overflow_window()
    uia, lib = _uia()
    tray = user32.FindWindowW("Shell_TrayWnd", None)
    # Windows 11 draws the taskbar's buttons inside this child; older builds put them on the taskbar itself.
    bridge = user32.FindWindowExW(tray, None, "Windows.UI.Composition.DesktopWindowContentBridge", None)
    taskbar = uia.ElementFromHandle(bridge or tray)
    found = taskbar.FindAll(lib.TreeScope_Descendants, uia.CreateTrueCondition())
    for i in range(found.Length):
        button = found.GetElement(i)
        if "hidden icons" in (button.CurrentName or "").lower():
            button.GetCurrentPattern(lib.UIA_InvokePatternId).QueryInterface(lib.IUIAutomationInvokePattern).Invoke()
            time.sleep(0.6)
            return ("opened the hidden icons tray. To click an icon in it, call screen_elements(app=\"tray\") "
                    "and click the one the user named")
    return "I couldn't find the hidden icons arrow on the taskbar, sir"


def _target_window(app: str):
    import desktop_control
    if app and any(word in app.lower() for word in _TRAY_WORDS):
        hwnd = _overflow_window()
        if hwnd and user32.IsWindowVisible(hwnd):
            return hwnd, "Hidden icons tray"
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
    _listed_names.clear()
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
        _listed_names[number] = name
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
    if name.strip() != _listed_names.get(number, name).strip():
        # The page redrew since the list was made: #20 was "Clear Selection", by then it was something blank,
        # and the click landed elsewhere. Never click a number whose control has changed.
        _elements.clear()
        return (f'the screen changed since I listed it (#{number} was "{_listed_names.get(number, "")}"). '
                "Call screen_elements again and pick from the new list")
    _elements.clear()   # a click usually changes the page: the next click needs a fresh list
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
    if not _typing_target_ok():
        return ("nothing to type into has the keyboard focus, so I didn't type (Enter could have done anything). "
                "Call screen_elements, click the text box, then type")
    keyboard.write(text, delay=0.01)
    if args.get("enter"):
        _elements.clear()
        keyboard.send("enter")
    return f'typed "{text[:60]}"' + (" and pressed Enter" if args.get("enter") else "")


_TYPEABLE = {50004, 50030, 50003}   # UIA Edit, Document, ComboBox


def _typing_target_ok() -> bool:
    """Is a text box focused? Typing (and its Enter) into a tab strip or a page once switched the user's tab.
    True when UI Automation can't tell: better to type than to refuse in an app it can't read."""
    try:
        uia, _lib = _uia()
        focused = uia.GetFocusedElement()
        return focused is None or focused.CurrentControlType in _TYPEABLE
    except Exception:
        return True


def switch_to_tab(query: str) -> str:
    """Bring a browser tab to the front by words from its title ("the LinkedIn tab"). "" when none matches."""
    import desktop_control
    words = [w for w in query.lower().split() if w not in ("tab", "the", "my", "last")]
    if not words:
        return ""
    uia, lib = _uia()
    tab_type = uia.CreatePropertyCondition(lib.UIA_ControlTypePropertyId, 50019)   # TabItem
    for browser in ("brave", "chrome", "edge", "firefox", "opera"):
        for hwnd, _title, _process in desktop_control._app_hits(browser):
            tabs = uia.ElementFromHandle(hwnd).FindAll(lib.TreeScope_Descendants, tab_type)
            for i in range(tabs.Length):
                tab = tabs.GetElement(i)
                name = (tab.CurrentName or "")
                if all(w in name.lower() for w in words):
                    desktop_control._bring_to_front(hwnd)
                    try:
                        tab.GetCurrentPattern(lib.UIA_SelectionItemPatternId).QueryInterface(
                            lib.IUIAutomationSelectionItemPattern).Select()
                    except Exception:
                        _real_click(tab)
                    title = re.sub(r" - (Memory usage|Audio playing|Pinned).*$", "", name)
                    return f'switched to the "{title[:70]}" tab'
    return ""


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
    {"name": "show_hidden_icons",
     "description": "Open the taskbar's hidden-icons tray (the ^ arrow by the clock). The user may call it the "
                    "mini tray, system tray or hidden icons. Never minimise or close it.",
     "parameters": {"type": "object", "properties": {}}},
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
