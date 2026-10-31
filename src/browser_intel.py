# browser_intel.py
"""Browser intelligence: turns "play the next episode" into the right action on whatever site is open, and
proves it happened.

    intent (from TRON's brain, as a tool call)          browser_media(action="next_episode")
      -> inspect the page, every frame                 browser_inspect.inspect
      -> plan strategies for this intent               the site's proven strategy first (browser memory)
      -> rank candidate controls by evidence           names, roles, states, player context, episode numbers
      -> act: trusted clicks / the media API / keys    never a risky control (buy, send, delete...)
      -> verify against the state before               URL, title, episode number, video time, fullscreen
      -> recover: re-inspect, next strategy            bounded by MAX_ATTEMPTS and a deadline, cancellable
      -> learn: which strategy worked on this site     preferred only after repeated success
      -> one plain sentence back to the brain          never success without evidence

Intent understanding stays in TRON's brain (Gemini or the local model) - it already maps speech to a tool
call. This module only ever acts on the page through Playwright, on the TRON browser.
"""
import json
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional
from urllib.parse import urlparse

import browser_inspect
import browser_session
import config

ACTIONS = ("play", "pause", "seek", "next_episode", "previous_episode", "volume", "mute", "unmute",
           "subtitles_on", "subtitles_off", "fullscreen", "exit_fullscreen", "status")
MAX_ATTEMPTS = 3
DEADLINE_SECONDS = 25.0
CONFIDENCE = 0.6        # a candidate below this is not pressed
AMBIGUITY_MARGIN = 0.08  # two different targets this close in score: ask instead of guessing
VERIFY_WAIT = 6.0

_cancel = threading.Event()
_deadline = [float("inf")]   # perform() sets it; every stage checks it, so no task runs past its budget
on_status: Callable[[str, str], None] = lambda stage, detail: None   # main.py / the panel can listen

# Never pressed by a media command, whatever the page calls it.
_RISKY = re.compile(r"\b(buy|pay|purchase|order|checkout|subscribe|premium|sign ?in|log ?in|sign ?up|register|"
                    r"download|install|delete|remove|send|submit|allow|accept|donate|upgrade|vpn)\b", re.I)
_AD = re.compile(r"\b(ad|ads|advert\w*|sponsored|promo\w*)\b", re.I)

# Words for each intent, several languages. Strength 1.0 = says exactly this; lower = could be.
_WORDS = {
    "next_episode": [(r"next\s*(episode|ep\b)|play\s*next|up\s*next|continue\s*to\s*next|siguiente\s*episodio|"
                      r"[ée]pisode\s*suivant|n[äa]chste\s*folge|agla\s*episode|अगला", 1.0),
                     (r"^\s*(next|siguiente|suivant|n[äa]chste|अगला)\s*$|^skip\s*to\s*next|next\s*video", 0.75)],
    "previous_episode": [(r"prev(ious)?\s*(episode|ep\b)|[ée]pisode\s*pr[ée]c[ée]dent|episodio\s*anterior|"
                          r"vorherige\s*folge|पिछला", 1.0),
                         (r"^\s*(prev(ious)?|back|anterior|pr[ée]c[ée]dent|पिछला)\s*$", 0.7)],
    "fullscreen": [(r"(enter\s*)?full\s*-?screen|pantalla\s*completa|plein\s*[ée]cran|vollbild", 1.0)],
    "exit_fullscreen": [(r"exit\s*full\s*-?screen|salir\s*de\s*pantalla", 1.0)],
    "subtitles": [(r"subtitle|caption|\bcc\b|untertitel|sous-titres|subt[íi]tulos", 1.0)],
    "play": [(r"^\s*play(\s*\(k\))?\s*$|^play\s*video|reproducir|lecture", 1.0)],
    "pause": [(r"^\s*pause(\s*\(k\))?\s*$|pausar", 1.0)],
}
# Look-alikes that are NOT the intent: "Next chapter" isn't the next episode, "Skip intro" isn't either.
_NOT = {"next_episode": r"chapter|intro|outro|recap|skip\s*\d|forward|\+\s*\d+|seconds|season|page|slide|comment|"
                        r"result|track",
        "previous_episode": r"chapter|intro|rewind|\d+\s*s(ec)?|seconds|season|page|slide"}


@dataclass
class Candidate:
    control: browser_inspect.Control
    score: float
    evidence: List[str] = field(default_factory=list)


@dataclass
class Result:
    ok: bool
    action: str
    message: str
    strategy: str = ""
    tried: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    needs_clarification: bool = False

    def sentence(self) -> str:
        if self.ok or self.needs_clarification:
            return self.message
        tried = "; ".join(self.tried) or "nothing could be tried"
        return f"{self.message} (I tried: {tried})"


class Cancelled(Exception):
    pass


def cancel() -> str:
    _cancel.set()
    return "stopped what I was doing in the browser, sir"


def _status(stage: str, detail: str = "") -> None:
    try:
        import local_brain
        local_brain.log_event("browser", stage, detail=detail[:200])
    except Exception:
        pass
    try:
        on_status(stage, detail)
    except Exception:
        pass
    if _cancel.is_set():
        raise Cancelled("stopped, sir")
    if time.time() > _deadline[0]:
        raise Cancelled("that took too long, so I stopped, sir")


# --------------------------------------------------------------------------- ranking
def rank(state: browser_inspect.PageState, intent: str) -> List[Candidate]:
    """Every control that could carry out `intent`, best first, with the evidence for each score."""
    key = "subtitles" if intent.startswith("subtitles") else intent
    patterns = _WORDS.get(key, [])
    target = None
    if intent in ("next_episode", "previous_episode") and state.episode:
        target = state.episode + (1 if intent == "next_episode" else -1)
    out = []
    for c in state.controls:
        label = c.label.strip()
        in_player = bool(re.search(r"player|plyr|video|controls|media", c.context, re.I))
        if not label or c.disabled or not (c.visible or (c.faded and in_player)):
            continue   # disabled or hidden: never "the" control. Faded player controls come back on hover.
        if _RISKY.search(label) or (_AD.search(label) and "player" not in c.context.lower()):
            continue
        score, evidence = 0.0, []
        for pattern, strength in patterns:
            if re.search(pattern, label, re.I):
                score, evidence = max(score, strength), [f'named "{label[:50]}"']
        if target is not None:
            number = browser_inspect.episode_number(c.name, c.href, " ".join(c.data.values()))
            if number is None and re.fullmatch(r"\s*(ep(isode)?\s*)?\d{1,4}\s*", c.name, re.I):
                number = int(re.search(r"\d+", c.name).group())
            if number == target:
                score, evidence = max(score, 0.9), evidence + [f"episode {target} (current is {state.episode})"]
        if score == 0:
            continue
        if intent in _NOT and re.search(_NOT[intent], label, re.I) and score < 1.0:
            continue
        if re.search(r"player|plyr|video|controls|episode|playlist", c.context, re.I):
            score += 0.1
            evidence.append(f"inside {c.context[:40]}")
        if not c.visible:
            score -= 0.05
            evidence.append("shown when the player's controls appear")
        if c.covered:
            score -= 0.25
            evidence.append("covered by something")
        if not c.in_view:
            score -= 0.05
        if c.current in ("true", "page", "step"):
            continue                                   # that's the episode already playing
        out.append(Candidate(c, round(min(score, 1.2), 3), evidence))
    out.sort(key=lambda x: -x.score)
    return out


def ambiguous(candidates: List[Candidate]) -> bool:
    """Two different destinations scoring about the same: pressing either would be a guess."""
    if len(candidates) < 2:
        return False
    a, b = candidates[0], candidates[1]
    if a.score - b.score > AMBIGUITY_MARGIN:
        return False
    if a.control.href and b.control.href:
        same = a.control.href == b.control.href      # two "Next" links to different pages aren't the same thing
    else:
        same = a.control.name == b.control.name
    return not same


# --------------------------------------------------------------------------- memory (what worked where)
def _memory_path():
    return config.app_dir() / "memory" / "browser_knowledge.json"


def _load() -> dict:
    try:
        return json.loads(_memory_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def site_of(url: str) -> str:
    return (urlparse(url).hostname or "").removeprefix("www.")


def remember(site: str, intent: str, strategy: str, ok: bool) -> None:
    """Counts outcomes per site/intent/strategy. Only these counts are stored: no page content, no URLs."""
    if not site:
        return
    data = _load()
    entry = data.setdefault(site, {}).setdefault(intent, {}).setdefault(strategy, {"ok": 0, "fail": 0})
    entry["ok" if ok else "fail"] += 1
    entry["last"] = time.strftime("%Y-%m-%d %H:%M")
    path = _memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")


def preferred(site: str, intent: str) -> List[str]:
    """Strategies proven on this site: at least two successes and more successes than failures."""
    stats = _load().get(site, {}).get(intent, {})
    good = [(s, v) for s, v in stats.items() if v.get("ok", 0) >= 2 and v["ok"] > v.get("fail", 0)]
    return [s for s, _v in sorted(good, key=lambda sv: -sv[1]["ok"])]


def knowledge(args=None, cfg=None) -> str:
    data = _load()
    if not data:
        return "I haven't learned anything about websites yet, sir"
    parts = []
    for site, intents in data.items():
        for intent, strategies in intents.items():
            best = max(strategies.items(), key=lambda sv: sv[1].get("ok", 0))
            parts.append(f"{site}: {intent.replace('_', ' ')} works best by {best[0]} ({best[1].get('ok', 0)} ok, "
                         f"{best[1].get('fail', 0)} failed)")
    return "; ".join(parts)


def forget(args=None, cfg=None) -> str:
    site = str((args or {}).get("site", "")).strip().lower()
    data = _load()
    if site:
        removed = {k: v for k, v in data.items() if site not in k}
        if len(removed) == len(data):
            return f"I hadn't learned anything about {site}, sir"
        data = removed
    else:
        data = {}
    path = _memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return f"forgot what I'd learned about {site or 'every website'}, sir"


# --------------------------------------------------------------------------- acting
def _media_call(state, script: str, arg=None):
    """Runs `script` against the page's main video (in whichever frame it lives); returns its result."""
    video = state.main_video
    if video is None:
        return None
    frame = state.frames[video.frame]
    return frame.evaluate(
        "([script, arg]) => { const vs = Array.from(document.querySelectorAll('video'));"
        " const v = vs.sort((a, b) => b.clientWidth * b.clientHeight - a.clientWidth * a.clientHeight)[0];"
        " return v ? (new Function('v', 'arg', script))(v, arg) : null; }", [script, arg])


def _reveal(state, control: browser_inspect.Control) -> bool:
    """Brings a faded player control back; True when it's really there to press. Players often keep a second,
    inactive copy of their control bar that never appears: that copy answers False."""
    frame = state.frames[control.frame]
    locator = frame.locator(f'[data-tron-id="{control.id}"]').first
    if not control.visible:
        # The player faded its controls out: moving the mouse over it brings them back, as for a person.
        # Players wake their controls on mouse movement (one static hover isn't enough on Vidstack), then fade
        # them in over ~0.5 s: wiggle across the player for a moment, the way a person would.
        player = frame.locator("media-player, [aria-label='Video Player'], .plyr, video").filter(visible=True).first
        try:
            player.scroll_into_view_if_needed(timeout=1000)   # the page may have scrolled the player away
            box = player.bounding_box(timeout=1000)
        except Exception:
            box = None   # no player in this frame: the control can't be woken here
        if box:
            for i in range(6):
                frame.page.mouse.move(box["x"] + box["width"] / 2 + (i % 2) * 12, box["y"] + box["height"] / 2)
                frame.page.wait_for_timeout(120)
    return locator.is_visible()


def _click(state, control: browser_inspect.Control, double=False) -> None:
    _reveal(state, control)
    locator = state.frames[control.frame].locator(f'[data-tron-id="{control.id}"]').first
    (locator.dblclick if double else locator.click)(timeout=2500)


def _snapshot(page) -> dict:
    state = browser_inspect.inspect(page)
    video = state.main_video
    return {"state": state, "url": page.url, "title": state.title, "episode": state.episode,
            "src": video.src if video else "", "time": video.time if video else None,
            "paused": video.paused if video else None, "fullscreen": state.fullscreen}


def _wait_for(page, check, timeout=VERIFY_WAIT):
    """Polls check(snapshot) until it returns evidence (a non-empty list) or the time runs out."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        _status("verifying")
        try:
            last = _snapshot(page)
            evidence = check(last)
            if evidence:
                return True, evidence, last
        except Exception as exc:            # the page navigating mid-read: read it again
            last = last or {"error": str(exc)}
        page.wait_for_timeout(400)
    return False, [], last


def _new_episode(before):
    def check(now):
        ev = []
        if now["episode"] is not None and before["episode"] is not None and now["episode"] != before["episode"]:
            ev.append(f"episode {before['episode']} -> {now['episode']}")
        if now["url"] != before["url"]:
            ev.append("the address changed")
        if now["title"] != before["title"]:
            ev.append(f'title is now "{now["title"][:60]}"')
        if now["src"] and now["src"] != before["src"]:
            ev.append("a new video loaded")
        return ev
    return check


def _ensure_playing(page, before: dict) -> str:
    """After moving to a new episode: is the NEW video playing? Sites that change episode without reloading
    keep the old <video> running for a moment, so "playing" needs the new one: a different source or a time
    back near the start, and the time moving forward between two looks."""
    deadline, nudged, last = time.time() + 10, False, None
    while time.time() < deadline:
        _status("verifying", "waiting for the new episode to play")
        video = browser_inspect.inspect(page).main_video
        fresh = video is not None and (video.src != before["src"] or (before["time"] or 0) - video.time > 5
                                       or video.time < 3)
        if fresh and last is not None and not video.paused and video.time > last + 0.2:
            return "it's playing"
        if fresh and video.paused and not nudged and time.time() > deadline - 7:
            nudged = True   # the site didn't autoplay it: press its Play (a real click counts as the user's)
            try:
                state = browser_inspect.inspect(page)
                plays = [c for c in rank(state, "play") if c.score >= CONFIDENCE]
                if plays:
                    _click(state, plays[0].control)
                else:
                    _media_call(state, "return v.play().then(() => true).catch(() => false)")
            except Exception:
                pass
        last = video.time if fresh else None
        page.wait_for_timeout(700)
    return "it's loaded but paused" if last is not None else "it's still loading"


def _strategies(intent: str, state, site: str) -> List[str]:
    """Which ways to try, most reliable first, a strategy proven on this site before anything else."""
    base = {
        "next_episode": ["named_control", "episode_list", "player_shortcut"],
        "previous_episode": ["named_control", "episode_list"],
        "play": ["media_api", "named_control", "click_video"], "pause": ["media_api", "named_control"],
        "seek": ["media_api", "arrow_keys"], "volume": ["media_api"], "mute": ["media_api"], "unmute": ["media_api"],
        "subtitles_on": ["text_tracks", "named_control"], "subtitles_off": ["text_tracks", "named_control"],
        "fullscreen": ["named_control", "f_key", "double_click_video"],
        "exit_fullscreen": ["exit_api", "escape", "named_control"],
    }.get(intent, [])
    known = [s for s in preferred(site, intent) if s in base]
    return known + [s for s in base if s not in known]


def _attempt(page, intent: str, strategy: str, before: dict, args: dict):
    """Tries one strategy. Returns (verified, evidence, detail) - detail says what happened either way."""
    state = before["state"]
    video = state.main_video

    if strategy in ("named_control", "episode_list"):
        candidates = rank(state, intent)
        if strategy == "episode_list":
            candidates = [c for c in candidates if any(e.startswith("episode ") for e in c.evidence)]
        else:   # a control whose own name says it ("Next episode"); episode numbers are episode_list's job
            candidates = [c for c in candidates if any(e.startswith("named ") for e in c.evidence)]
        candidates = [c for c in candidates if c.score >= CONFIDENCE]
        if not candidates:
            return False, [], "no control with enough evidence"
        if strategy == "named_control" and ambiguous(candidates):
            raise _Ambiguous(candidates[:3])
        # the first candidate that is really there once the player's controls are woken
        best = next((c for c in candidates[:4] if c.control.visible or _reveal(state, c.control)), None)
        if best is None:
            return False, [], "no control with enough evidence"
        _status("executing", f'pressing "{best.control.name[:40]}"')
        _click(state, best.control)
        check = {"next_episode": _new_episode(before), "previous_episode": _new_episode(before)}.get(intent)
        if intent in ("play", "pause"):
            check = lambda now: ["the video is " + ("paused" if now["paused"] else "playing")] \
                if now["paused"] == (intent == "pause") else []
        if intent.startswith("subtitles"):
            check = lambda now: [f'pressed "{best.control.name[:30]}"'] if now["state"].controls else []
        if intent in ("fullscreen", "exit_fullscreen"):
            check = lambda now: ["full screen is " + ("on" if now["fullscreen"] else "off")] \
                if now["fullscreen"] == (intent == "fullscreen") else []
        ok, evidence, after = _wait_for(page, check)
        return ok, evidence + best.evidence, f'pressed "{best.control.name[:40]}"'

    if strategy == "player_shortcut":
        if video is None:
            return False, [], "no video to send the shortcut to"
        page.keyboard.press("Shift+N")          # YouTube and many players: next video
        ok, evidence, after = _wait_for(page, _new_episode(before), timeout=5)
        return ok, evidence, "pressed Shift+N"

    if video is None and strategy in ("media_api", "arrow_keys", "text_tracks", "click_video", "double_click_video",
                                      "f_key"):
        return False, [], "there's no video on this page"

    if strategy == "media_api":
        if intent in ("play", "pause"):
            _status("executing", intent)
            played = _media_call(state, "return arg ? v.play().then(() => true).catch(e => e.name) : (v.pause(), true)",
                                 intent == "play")
            ok, evidence, _ = _wait_for(page, lambda now: [f"the video is {'playing' if not now['paused'] else 'paused'}"]
                                        if now["paused"] == (intent == "pause") else [], timeout=3)
            return ok, evidence, f"used the player ({played})"
        if intent == "seek":
            seconds = float(args.get("seconds") or 10)
            start = video.time
            _media_call(state, "v.currentTime = Math.max(0, v.currentTime + arg); return v.currentTime;", seconds)
            ok, evidence, _ = _wait_for(page, lambda now: [f"moved from {start:.0f}s to {now['time']:.0f}s"]
                                        if now["time"] is not None and (now["time"] - start) * seconds > 0
                                        and abs(now["time"] - start - seconds) < max(4, abs(seconds) * 0.5) else [],
                                        timeout=4)
            return ok, evidence, f"moved the video by {seconds:+.0f}s"
        if intent == "volume":
            level = min(max(float(args.get("level", 50)), 0), 100) / 100
            got = _media_call(state, "v.volume = arg; v.muted = false; return v.volume;", level)
            ok = got is not None and abs(got - level) < 0.02
            return ok, [f"volume is {round((got or 0) * 100)}%"] if ok else [], "set the video's volume"
        if intent in ("mute", "unmute"):
            got = _media_call(state, "v.muted = arg; return v.muted;", intent == "mute")
            return got == (intent == "mute"), [f"the video is {'muted' if got else 'unmuted'}"], "set mute"

    if strategy == "arrow_keys":
        seconds = float(args.get("seconds") or 10)
        start = video.time
        state.frames[video.frame].locator("video").first.focus()
        for _ in range(max(1, round(abs(seconds) / 5))):
            page.keyboard.press("ArrowRight" if seconds > 0 else "ArrowLeft")
        ok, evidence, _ = _wait_for(page, lambda now: [f"moved from {start:.0f}s to {now['time']:.0f}s"]
                                    if now["time"] is not None and (now["time"] - start) * seconds > 0 else [], timeout=3)
        return ok, evidence, "used the arrow keys"

    if strategy == "text_tracks":
        if not video.tracks:
            return False, [], "the video has no subtitle tracks the page exposes"
        on = intent == "subtitles_on"
        modes = _media_call(state, "const ts = Array.from(v.textTracks); ts.forEach((t, i) => t.mode = arg && i === 0 ? "
                                   "'showing' : (arg ? t.mode : 'disabled')); return ts.map(t => t.mode);", on)
        ok = bool(modes) and (("showing" in modes) == on)
        return ok, [f"subtitles {'on' if on else 'off'}"] if ok else [], "switched the subtitle track"

    if strategy == "exit_api":
        for frame in state.frames:
            try:
                frame.evaluate("document.fullscreenElement ? document.exitFullscreen() : null")
            except Exception:
                continue
        ok, evidence, _ = _wait_for(page, lambda now: ["full screen is off"] if not now["fullscreen"] else [], timeout=3)
        return ok, evidence, "asked the page to leave full screen"

    if strategy in ("f_key", "double_click_video", "click_video", "escape"):
        frame = state.frames[video.frame] if video else page.main_frame
        if strategy == "escape":
            page.keyboard.press("Escape")
        elif strategy == "f_key":
            frame.locator("media-player, [aria-label='Video Player'], .plyr, video").filter(visible=True).first.focus()
            page.keyboard.press("f")
        else:
            frame.locator("video, media-player, [aria-label='Video Player'], .plyr").filter(visible=True).first.click(
                timeout=4000, click_count=2 if strategy == "double_click_video" else 1)
        if intent in ("fullscreen", "exit_fullscreen"):
            want = intent == "fullscreen"
            ok, evidence, after = _wait_for(page, lambda now: ["full screen is " + ("on" if now["fullscreen"] else "off")]
                                            if now["fullscreen"] == want else [], timeout=3)
            if ok and want and before["paused"] is False and after["paused"]:
                _media_call(after["state"], "return v.play().then(() => true).catch(() => false)")
                evidence.append("kept it playing")
            return ok, evidence, strategy.replace("_", " ")
        ok, evidence, _ = _wait_for(page, lambda now: ["the video is playing"] if now["paused"] is False else [], timeout=3)
        return ok, evidence, "clicked the video"
    return False, [], f"{strategy} doesn't apply"


class _Ambiguous(Exception):
    def __init__(self, candidates):
        super().__init__("ambiguous")
        self.candidates = candidates


def perform(page, action: str, args: dict = None, max_attempts: int = MAX_ATTEMPTS,
            deadline: float = DEADLINE_SECONDS) -> Result:
    """The whole loop on one page: inspect, plan, act, verify, recover, learn."""
    args = args or {}
    _cancel.clear()
    started = time.time()
    _deadline[0] = started + deadline
    try:
        _status("inspecting", page.url[:80])
        before = _snapshot(page)
        state = before["state"]
        site = site_of(state.url)
        if action == "status":
            return Result(True, action, browser_inspect.summary(state))
        if action not in ACTIONS:
            return Result(False, action, f"I don't know how to {action.replace('_', ' ')} in the browser, sir")
        if state.main_video is None and action not in ("next_episode", "previous_episode"):
            return Result(False, action, "there's no video on this page, sir", tried=["looked in every frame"])
        tried, attempts = [], 0
        for strategy in _strategies(action, state, site):
            if attempts >= max_attempts or time.time() - started > deadline:
                break
            _status("planning", strategy)
            try:
                ok, evidence, detail = _attempt(page, action, strategy, before, args)
            except _Ambiguous as amb:
                names = " or ".join(f'"{c.control.name[:40]}"' for c in amb.candidates[:2])
                _status("needs_clarification", names)
                return Result(False, action, f"I can see {names}, sir. Which one do you mean?", tried=tried,
                              needs_clarification=True)
            except Cancelled:
                raise
            except Exception as exc:
                ok, evidence, detail = False, [], f"{strategy} failed: {type(exc).__name__}: {str(exc)[:80]}"
            if detail.startswith(("no control", "there's no", "the video has no", "no video")) or \
                    detail.endswith("doesn't apply"):
                tried.append(detail)
                continue                                   # nothing was done: not an attempt, nothing learned
            attempts += 1
            remember(site, action, strategy, ok)
            if ok and action in ("next_episode", "previous_episode"):
                evidence.append(_ensure_playing(page, before))   # last on purpose: _done reads it
            if ok:
                _status("completed", "; ".join(evidence))
                return Result(True, action, _done(action, evidence), strategy, tried + [detail], evidence)
            tried.append(f"{detail}, but nothing changed")
            _status("recovering", detail)
            before = _snapshot(page)                       # the page may have moved on: plan from what's there now
        _status("failed", "; ".join(tried))
        last = _last_episode(before["state"]) if action == "next_episode" else ""
        if last:
            return Result(False, action, last, tried=tried)
        return Result(False, action, f"I couldn't {action.replace('_', ' ')} on this page, sir", tried=tried)
    except Cancelled as stop:
        return Result(False, action, str(stop) or "stopped, sir", tried=["cancelled"])
    finally:
        _deadline[0] = float("inf")


def _last_episode(state) -> str:
    """"Next episode" with nothing to press: if the episode list ends at the current one, say that."""
    if not state.episode:
        return ""
    numbers = {browser_inspect.episode_number(c.name, c.href) for c in state.controls}
    numbers.discard(None)
    if numbers and max(numbers) <= state.episode:
        seasons = [c.name for c in state.controls if re.search(r"season\s*\d", c.name, re.I) and c.visible
                   and "current" not in c.name.lower()]
        offer = f" {seasons[0].split(chr(10))[0][:30]} is listed; shall I open it?" if seasons else ""
        return f"Episode {state.episode} looks like the last one here, sir.{offer}"
    return ""


def _done(action: str, evidence: List[str]) -> str:
    said = {"next_episode": "I've started the next episode", "previous_episode": "I've gone back an episode",
            "play": "it's playing", "pause": "paused", "seek": "done", "volume": "done", "mute": "muted",
            "unmute": "unmuted", "subtitles_on": "subtitles are on", "subtitles_off": "subtitles are off",
            "fullscreen": "it's full screen", "exit_fullscreen": "back to normal size"}[action]
    if action in ("next_episode", "previous_episode") and evidence and evidence[-1] != "it's playing":
        said = said.replace("started", "opened") + (", but it's paused" if "paused" in evidence[-1]
                                                    else ", and it's still loading")
    if action == "seek":
        moved = next((e for e in evidence if e.startswith("moved")), "")
        return f"Done, sir. {moved[0].upper() + moved[1:]}." if moved else "Done, sir."
    detail = next((e for e in evidence if e.startswith(("episode", "moved", "volume"))), "")
    return f"Done, sir. {said[0].upper() + said[1:]}" + (f" ({detail})." if detail else ".")


# --------------------------------------------------------------------------- the tools
def browser_media(args, cfg=None) -> str:
    """Tool: control the video in the TRON browser and report only what was verified."""
    action = str((args or {}).get("action", "")).strip().lower().replace(" ", "_")
    if action == "next":
        action = "next_episode"
    try:
        result = browser_session.run(lambda w: perform(browser_session.active_page(w), action, args or {}),
                                     timeout=DEADLINE_SECONDS + 20)
    except browser_session.BrowserUnavailable as exc:
        fallback = {"play": "play", "pause": "pause", "fullscreen": "fullscreen", "exit_fullscreen": "exit_fullscreen"}
        if action in fallback:
            # Not the TRON browser: Windows' view of any browser can still do these (desktop_control.video_control).
            import desktop_control
            return desktop_control.video_control({"action": fallback[action]})
        return str(exc)
    except TimeoutError:
        cancel()   # or the job keeps the browser thread busy and every command after it times out too
        return "the browser didn't respond in time, sir"
    return result.sentence()


def browser_page(args, cfg=None) -> str:
    """Tool: describe the current page, or press a control on it by what it says."""
    action = str((args or {}).get("action", "describe")).lower()

    def go(worker):
        page = browser_session.active_page(worker)
        state = browser_inspect.inspect(page)
        if action != "click":
            return browser_inspect.summary(state)
        want = str(args.get("target", "")).strip().lower()
        if not want:
            return "what should I press, sir?"
        matches = [c for c in state.controls if c.visible and not c.disabled and want in c.label.lower()]
        if not matches:
            return f'there\'s nothing on the page called "{want}", sir'
        exact = [c for c in matches if c.name.lower().strip() == want] or matches
        if len({c.name for c in exact}) > 1:
            return "which one, sir: " + " or ".join(f'"{c.name[:40]}"' for c in exact[:3]) + "?"
        target = exact[0]
        if _RISKY.search(target.label) and not _RISKY.search(want):
            # A harmless-sounding request that lands on "Continue to checkout": only a request that names the
            # risky thing can press it, and brain.Guard asks the user for a spoken yes before those run.
            return (f'NOT DONE: the matching control is "{target.name[:40]}", which may buy, send, delete or sign '
                    "in. Tell the user and ask them to say exactly that if they want it.")
        title, url = page.title(), page.url
        _click(state, target)
        page.wait_for_timeout(1200)
        changed = page.url != url or page.title() != title
        return f'pressed "{target.name[:40]}"' + (f', now on "{page.title()[:60]}"' if changed else
                                                   " (the page didn't visibly change)")
    try:
        return browser_session.run(go)
    except browser_session.BrowserUnavailable as exc:
        return str(exc)


def open_browser(args=None, cfg=None) -> str:
    try:
        return browser_session.launch(str((args or {}).get("url", "")))
    except browser_session.BrowserUnavailable as exc:
        return str(exc)


def play_web(args, cfg=None) -> str:
    """Tool: play a song or video on YouTube Music / YouTube in the TRON browser, and check it plays."""
    from urllib.parse import quote_plus
    query = str((args or {}).get("query", "")).strip()
    service = str((args or {}).get("service", "youtube_music")).lower()
    if not query:
        return "what should I play, sir?"
    url = (f"https://music.youtube.com/search?q={quote_plus(query)}" if service == "youtube_music"
           else f"https://www.youtube.com/results?search_query={quote_plus(query)}")
    if not browser_session.healthy():
        try:
            browser_session.launch()
        except browser_session.BrowserUnavailable as exc:
            return str(exc)
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1]

    def go(worker):
        _cancel.clear()
        ctx = worker.browser().contexts[0]
        page = next((p for p in ctx.pages if site_of(p.url) in ("music.youtube.com", "youtube.com")), None)             or (ctx.pages[0] if ctx.pages else ctx.new_page())
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        page.bring_to_front()
        found = None
        for _ in range(16):          # results render a moment after the page loads
            page.wait_for_timeout(500)
            state = browser_inspect.inspect(page)
            plays = [c for c in state.controls if c.visible or c.faded]
            # a result whose name carries the query: its "Play <title>" button first, else its link
            scored = sorted(((sum(w in c.name.lower() for w in words) + (1 if c.name.lower().startswith("play") else 0), c)
                             for c in plays if not _RISKY.search(c.label)), key=lambda x: -x[0])
            if scored and scored[0][0] >= max(2, len(words)):
                found = (state, scored[0][1])
                break
        if found is None:
            return f"I couldn't find \"{query}\" on {'YouTube Music' if service == 'youtube_music' else 'YouTube'}, sir"
        state, control = found
        _click(state, control)
        deadline = time.time() + 12
        last = None
        while time.time() < deadline:
            page.wait_for_timeout(800)
            video = browser_inspect.inspect(page).main_video
            if video and not video.paused and last is not None and video.time > last + 0.3:
                return f'playing "{control.name.removeprefix("Play ")[:60]}" on ' +                        ("YouTube Music" if service == "youtube_music" else "YouTube") + ", sir"
            last = video.time if video else None
        return f"I opened \"{control.name[:60]}\" but it isn't playing yet, sir"
    try:
        return browser_session.run(go, timeout=60)
    except browser_session.BrowserUnavailable as exc:
        return str(exc)
    except TimeoutError:
        cancel()
        return "the browser didn't respond in time, sir"
