# music.py
"""Play a specific song on Spotify without a Spotify API key.

Asked to "play Dancing With Your Ghost", TRON used to open Spotify and then fall back to a Google search,
because nothing could pick a track. The Spotify developer API (spotipy) needs an app registration; this
needs nothing. Spotify's desktop app is Chromium underneath, so — exactly like reading a browser's address
bar for clipping — Windows UI Automation can see its buttons. The search URI fills Spotify's search page,
and the result's own "Play <song>" button is pressed.

Verified on this machine: the window title changed to "Sasha Alex Sloan - Dancing With Your Ghost".
Spotify only arms those buttons under the mouse, so the press is a real click at the button's position;
the pointer is put back afterwards.
"""
import ctypes
import difflib
import os
import re
import time
import urllib.parse
from ctypes import wintypes

user32 = ctypes.windll.user32


def _uia():
    import comtypes.client
    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen import UIAutomationClient as lib
    return comtypes.client.CreateObject("{ff48dba4-60ef-4201-aa87-54103eef594e}", interface=lib.IUIAutomation), lib


def _spotify_window():
    import desktop_control
    for hwnd, title, process in desktop_control._open_windows():
        if process.lower().startswith("spotify"):
            return hwnd, title
    return None, None


def now_playing():
    """'Artist - Song' while Spotify plays, else None (its title is 'Spotify ...' when paused)."""
    _hwnd, title = _spotify_window()
    return title if title and not title.startswith("Spotify") else None


def _pausable(hwnd, title: str) -> bool:
    """Spotify relabels a result's button "Pause <title>" once it plays. For a playlist or an artist that's the
    only proof: the song playing ("Artist - Song") never carries the playlist's name, and treating that as a
    failure made TRON click again and pause it."""
    uia, lib = _uia()
    cond = uia.CreatePropertyCondition(lib.UIA_NamePropertyId, "Pause " + title)
    try:
        return uia.ElementFromHandle(hwnd).FindFirst(lib.TreeScope_Descendants, cond) is not None
    except Exception:
        return False


def _play_buttons(hwnd):
    """(name, element) for every 'Play <something>' button on the page."""
    uia, lib = _uia()
    cond = uia.CreatePropertyCondition(lib.UIA_ControlTypePropertyId, lib.UIA_ButtonControlTypeId)
    root = uia.ElementFromHandle(hwnd)
    found = root.FindAll(lib.TreeScope_Descendants, cond)
    if found.Length < 3:
        # Chromium drops its accessibility tree when no one has asked for a while, and the first request
        # after that returns almost nothing. Asking for everything once wakes it up.
        # It can take a second or more to rebuild (seen: 6 elements, then 1041 a moment later).
        deadline = time.time() + 3
        while time.time() < deadline:
            if root.FindAll(lib.TreeScope_Descendants, uia.CreateTrueCondition()).Length > 50:
                break
            time.sleep(0.3)
            root = uia.ElementFromHandle(hwnd)
        found = root.FindAll(lib.TreeScope_Descendants, cond)
    walker = uia.ControlViewWalker

    def in_results(element) -> bool:
        """Inside Spotify's "Search results" section. The left sidebar lists your library and recent plays
        ("Blinding Lights" there was a Chromatics Remix you'd played), and screen position can't tell them
        apart: at some window sizes the results start left of where the sidebar ends."""
        parent = walker.GetParentElement(element)
        for _ in range(8):
            if parent is None:
                return False
            if (parent.CurrentName or "") == "Search results":
                return True
            parent = walker.GetParentElement(parent)
        return False

    out = []
    for i in range(found.Length):
        try:
            element = found.GetElement(i)
            name = element.CurrentName or ""
            if not name.lower().startswith("play ") or len(name) <= 5 or element.CurrentIsOffscreen:
                continue
            if in_results(element):
                out.append((name[5:], element))
        except Exception:
            continue   # Spotify is re-rendering and this control just went away; the rest are still good
    return out


def best_match(query: str, titles: list):
    """Index of the result that best fits what was asked for, or None.

    The query may carry the artist too ("dancing with your ghost by sasha sloan"), so a title contained in
    the query counts as a full match; otherwise plain similarity, with a floor so a wrong song isn't played."""
    want = " ".join(query.lower().replace(" by ", " ").split())
    scored = []
    for i, title in enumerate(titles):
        t = " ".join(title.lower().split())
        if t == want:
            score = 3.0
        elif t in want:                 # "dancing with your ghost" inside "...ghost sasha alex sloan"
            score = 2.0 + len(t) / 1000  # the longest such title is the most specific
        elif want in t:                 # a variant: "(Slowed + Reverb)", "- Sped Up"; the plainest wins
            score = 1.0 - (len(t) - len(want)) / 1000
        else:
            score = difflib.SequenceMatcher(None, want, t).ratio()
        scored.append((score, -i, i))   # ties go to the earlier (higher-ranked) result
    if not scored:
        return None
    score, _neg, index = max(scored)
    # Strict on purpose: at 0.45 "perfect ed sheeran" matched a playlist called "Energetic dance songs".
    # Playing nothing and saying so beats playing the wrong thing.
    return index if score >= 0.75 else None


def choose(query: str, titles: list):
    """Which result to play. "X by Y" means the song X by the artist Y: look for X first, so the artist's
    own card (also inside the request) doesn't win over the song; fall back to the whole request, which
    is right for "play some Ed Sheeran"."""
    lowered = query.lower()
    # The version asked for (normally the original) before remixes/instrumentals, unless that's all there is (or what was asked for).
    kind = {v for v in _VARIANTS if v in lowered}
    originals = [i for i, t in enumerate(titles) if {v for v in _VARIANTS if v in t.lower()} == kind]
    if originals and len(originals) < len(titles):
        picked = choose(query, [titles[i] for i in originals])
        if picked is not None:
            return originals[picked]
    if " by " in lowered:
        song = query[:lowered.index(" by ")].strip()
        index = best_match(song, titles) if song else None
        if index is not None:
            return index
    return best_match(query, titles)


_VARIANTS = ("remix", "slowed", "sped up", "reverb", "live", "acoustic", "instrumental", "karaoke", "cover", "8d")


def same_version(wanted: str, playing_song: str) -> bool:
    """A remix, slowed or live version only counts when one was asked for. "Blinding Lights" played the
    Chromatics Remix and was accepted as a match, because its name contains the original's."""
    w, p = wanted.lower(), playing_song.lower()
    return not any(v in p and v not in w for v in _VARIANTS)


def _volume_slider():
    """Spotify's in-app volume slider (0..1). This is the volume Spotify shows, and it is separate from
    Spotify's level in the Windows volume mixer: TRON once said "already at 100 percent" reading the
    mixer while Spotify's own slider sat at 50."""
    hwnd, _title = _spotify_window()
    if not hwnd:
        return None
    uia, lib = _uia()
    cond = uia.CreateAndCondition(
        uia.CreatePropertyCondition(lib.UIA_ControlTypePropertyId, lib.UIA_SliderControlTypeId),
        uia.CreatePropertyCondition(lib.UIA_NamePropertyId, "Change volume"))
    element = uia.ElementFromHandle(hwnd).FindFirst(lib.TreeScope_Descendants, cond)
    if element is None:
        return None
    return element.GetCurrentPattern(lib.UIA_RangeValuePatternId).QueryInterface(lib.IUIAutomationRangeValuePattern)


def spotify_volume(args, cfg=None) -> str:
    """Set (level) or nudge (delta) Spotify's own volume, in percent."""
    try:
        slider = _volume_slider()
    except Exception:
        slider = None
    if slider is None:
        return None   # caller falls back to the mixer
    current = round(slider.CurrentValue * 100)
    try:
        level = int(args["level"]) if args.get("level") is not None else current + int(args.get("delta", 0))
    except (TypeError, ValueError):
        return "I need a level between 0 and 100, sir"
    level = max(0, min(100, level))
    slider.SetValue(level / 100.0)
    time.sleep(0.3)
    try:   # report what Spotify actually shows now, not what was asked for
        level = round(_volume_slider().CurrentValue * 100)
    except Exception:
        pass
    if level == current and args.get("level") is None:
        return f"Spotify is already at {level} percent, sir"
    return f"Spotify is at {level} percent, sir"


def _click(element) -> None:
    r = element.CurrentBoundingRectangle
    x, y = (r.left + r.right) // 2, (r.top + r.bottom) // 2
    back = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(back))
    user32.SetCursorPos(x, y)
    time.sleep(0.4)                    # Spotify arms the button on hover
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.2)
    user32.SetCursorPos(back.x, back.y)


def play_music(args, cfg=None) -> str:
    """Tool handler: find the song on Spotify and start it."""
    import desktop_control
    query = str(args.get("query", "")).strip()
    # "Hey tron, play sunflower" reached Spotify as "Drone Sunflower": the wake word, misheard, rode along.
    query = re.sub(r"^\s*(?:(?:hey|hi|ok|okay)\s+)?(?:tron|drone|throne|tran)\b[\s,]*", "", query, flags=re.I).strip()
    query = re.sub(r"^play\s+", "", query, flags=re.I).strip()
    if not query:
        return "what should I play, sir?"
    if re.fullmatch(r"(?:some |a |any )?(?:spotify|music|songs?|something)(?: on spotify)?", query, re.I):
        # "Open Spotify and play" names no song: resume whatever Spotify had, instead of searching "Spotify".
        os.startfile("spotify:")
        for _ in range(20):
            time.sleep(0.5)
            if _spotify_window()[0]:
                break
        import keyboard
        if not now_playing():
            keyboard.send("play/pause media")
        time.sleep(1.0)
        playing = now_playing()
        return f"playing {playing} on Spotify, sir" if playing else "Spotify is open, sir. What should I play?"
    hwnd, _title = _spotify_window()
    try:
        before = [t for t, _e in _play_buttons(hwnd)] if hwnd else []
    except Exception:
        before = []
    os.startfile("spotify:search:" + urllib.parse.quote(query))   # also launches Spotify if it's closed
    titles, buttons = [], []
    brought_forward = resent = False
    started = time.time()
    # Spotify may be starting up (from closed it took longer than 15 s once: "Spotify didn't open"), and it
    # fills its page a moment later.
    limit = 15 if hwnd else 30
    while time.time() - started < limit:
        time.sleep(0.4)
        hwnd, _title = _spotify_window()
        if not hwnd:
            continue
        if not brought_forward:
            # Behind other windows or minimised, Windows reports every control as off screen and none could
            # be picked ("Sunflower" found nothing that way). It is about to be clicked anyway.
            desktop_control._bring_to_front(hwnd)
            brought_forward = True
            time.sleep(0.6)
        try:
            found = _play_buttons(hwnd)
        except Exception:
            continue
        current = [t for t, _e in found]
        # The page still showing the previous search's results is the trap here: wait for it to change
        # (or a few seconds, for a repeat of the same search, whose results don't change).
        if current == before and current and not resent and time.time() - started > 2.5:
            # Spotify sometimes ignores the search link (seen twice in a row while it sat behind Brave):
            # send it again now that the window is in front.
            os.startfile("spotify:search:" + urllib.parse.quote(query))
            resent = True
            continue
        if not found or (current == before and time.time() - started < 4):
            continue
        titles, buttons = current, [e for _t, e in found]
        index = choose(query, titles)
        # A half-loaded page may show only a remix so far: give the original a few seconds to appear.
        if index is not None and (same_version(query, titles[index]) or time.time() - started > 6):
            break
        if index is None and time.time() - started > 5:
            break   # results are in and none is named like the request: a broad one ("hindi songs")
    if not hwnd:
        return "Spotify didn't open, sir"
    index = choose(query, titles)
    broad = index is None and bool(titles)
    if broad:
        index = 0   # "hindi songs" names a kind of music, not a title: Spotify's top result is the best guess
    if index is None:
        return f'Spotify has no result that looks like "{query}", sir'
    wanted = titles[index]

    def is_wanted(playing):
        """Spotify's title is "Artist - Song": what was pressed may be either (a song, or an artist card)."""
        if not playing:
            return False
        if broad:
            return True
        artist, _sep, song = playing.partition(" - ")
        if not same_version(wanted, song or playing):
            return False
        return any(best_match(wanted, [part]) is not None for part in (song, artist, playing))

    def click(element):
        desktop_control._bring_to_front(hwnd)
        time.sleep(0.8)
        # A fresh search opens a suggestions dropdown over the top results; a click aimed at the first result
        # landed on a suggestion instead. Escape closes the dropdown and leaves the results.
        import keyboard
        keyboard.send("esc")
        time.sleep(0.5)
        # Bringing the window forward can re-lay the page out: find the button again for a fresh position.
        fresh = [e for t, e in _play_buttons(hwnd) if t == wanted]
        _click(fresh[0] if fresh else element)

    def invoke(element):
        _uia_obj, lib = _uia()
        # Found while the page was still re-rendering, the element can be a dead copy: look it up again.
        fresh = [e for t, e in _play_buttons(hwnd) if t == wanted]
        element = fresh[0] if fresh else element
        element.GetCurrentPattern(lib.UIA_InvokePatternId).QueryInterface(lib.IUIAutomationInvokePattern).Invoke()

    def media_key(_element):
        # When Spotify is already paused on this very song its Play button does nothing; the play key
        # resumes it. Checked below against what actually plays, so a different paused song isn't kept.
        import keyboard
        keyboard.send("play/pause media")

    # Invoke presses that exact button; a click by screen position landed on another row ("Blinding Lights"
    # played the Chromatics Remix above it) and needs the window in front.
    for attempt in (invoke, click, media_key):
        try:
            attempt(buttons[index])
        except Exception:
            continue
        for _ in range(24 if broad else 12):   # a playlist takes longer to start than a song
            time.sleep(0.25)
            playing = now_playing()
            if playing and is_wanted(playing):
                return f"playing {playing} on Spotify, sir"
            if _pausable(hwnd, wanted):   # started; the window title can lag a moment behind
                return f"playing {wanted} on Spotify, sir"
        if attempt is media_key and now_playing():
            import keyboard
            keyboard.send("play/pause media")   # resumed the wrong song: put it back the way it was
    return f'I found "{wanted}" on Spotify, sir, but couldn\'t get it to start'
