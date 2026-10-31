# tests/test_watch_video_learning.py
"""Watching an app until something happens, full-screening a browser video honestly, and learning from
every conversation (Gemini ones too)."""
import time
from types import SimpleNamespace

import desktop_control
import local_brain
import music
import state_manager as sm
import watcher
from tests.test_state_manager import FakeAudio


# --------------------------------------------------------------------------- watching
def _watch(answers, **args):
    """Runs a watch to the end with scripted looks; returns what was announced."""
    said, looks = [], list(answers)

    def check():
        if not looks:          # the script is over: end the watch as "stop watching" would
            watcher.stop_watching()
            return {"met": False, "evidence": ""}
        return looks.pop(0)
    watcher.on_found = said.append
    watch_args = {"app": "Riot Client", "condition": "a Play button is showing", "announce": "Valorant has updated",
                  **args}
    import threading
    done = threading.Event()
    orig = watcher._run

    def run(watch, check, sleep):
        orig(watch, check, sleep)
        done.set()
    watcher._run = run
    try:
        desktop_control._app_hits = lambda q: [(1, "Riot Client", "Riot Client.exe")]
        reply = watcher.watch_until(watch_args, check=check, sleep=lambda s: None)
        assert done.wait(5)
    finally:
        watcher._run = orig
    return reply, said


def test_the_watcher_announces_only_after_two_yeses_in_a_row(monkeypatch):
    monkeypatch.setattr(desktop_control, "_app_hits", desktop_control._app_hits)
    yes = {"met": True, "evidence": "Play button"}
    no = {"met": False, "evidence": "update bar at 60%"}
    reply, said = _watch([yes, no, no, yes, yes])
    assert "Nothing is confirmed yet" in reply
    assert said == ["Valorant has updated: Play button"]


def test_one_hopeful_look_is_not_enough(monkeypatch):
    monkeypatch.setattr(desktop_control, "_app_hits", desktop_control._app_hits)
    yes = {"met": True, "evidence": "Play"}
    no = {"met": False, "evidence": "bar"}
    _reply, said = _watch([yes, no, yes, no])
    assert said == []   # four looks, never two yeses in a row


def test_watching_needs_the_window(monkeypatch):
    monkeypatch.setattr(desktop_control, "_app_hits", lambda q: [])
    assert "can't see a window" in watcher.watch_until({"app": "Riot", "condition": "x"})


def test_stop_watching_ends_every_watch():
    stop = SimpleNamespace(set=lambda: None)
    watcher._watches.append({"stop": stop, "app": "a", "condition": "c", "last": ""})
    assert "watching a" in watcher.check_watches()
    assert watcher.stop_watching() == "stopped 1 watch, sir" and watcher.check_watches() == "I'm not watching anything, sir"


# --------------------------------------------------------------------------- browser video
def _fake_browser(monkeypatch, fullscreen_after_f=False, fullscreen_after_double=True):
    state = {"fs": False, "playing": True, "pressed": []}
    monkeypatch.setattr(desktop_control, "_video_window", lambda: 7)
    monkeypatch.setattr(desktop_control, "_bring_to_front", lambda h: None)
    monkeypatch.setattr(desktop_control, "_controls", lambda h: [])
    monkeypatch.setattr(desktop_control, "_is_fullscreen", lambda h: state["fs"])
    monkeypatch.setattr(desktop_control, "_is_playing", lambda h: state["playing"])
    monkeypatch.setattr(desktop_control.time, "sleep", lambda s: None)

    def key(k):
        state["pressed"].append(k)
        if k == "f" and fullscreen_after_f:
            state["fs"] = True
        if k == "play/pause media":
            state["playing"] = not state["playing"]

    def double(h):
        state["pressed"].append("double-click")
        if fullscreen_after_double:
            state["fs"], state["playing"] = True, False   # the double-click paused it on Miruro
        return True
    monkeypatch.setattr(desktop_control.keyboard, "send", key)
    monkeypatch.setattr(desktop_control, "_double_click_video", double)
    return state


def test_full_screen_falls_back_to_a_double_click_and_keeps_it_playing(monkeypatch):
    state = _fake_browser(monkeypatch)
    assert desktop_control.video_control({"action": "fullscreen"}) == "full screen, sir"
    assert state["pressed"] == ["f", "double-click", "play/pause media"] and state["playing"]


def test_full_screen_is_never_claimed_when_it_did_not_happen(monkeypatch):
    _fake_browser(monkeypatch, fullscreen_after_double=False)
    assert desktop_control.video_control({"action": "fullscreen"}).startswith("I tried, but the video didn't go full screen")


def test_no_browser_no_claim(monkeypatch):
    monkeypatch.setattr(desktop_control, "_video_window", lambda: None)
    assert "no browser window" in desktop_control.video_control({"action": "play"})


# --------------------------------------------------------------------------- spotify
def test_a_broad_request_still_has_a_song_to_play():
    assert music.choose("hindi songs", ["Arz Kiya Hai", "Tum Hi Ho"]) is None   # play_music then takes result 0


# --------------------------------------------------------------------------- learning from every conversation
def test_a_gemini_conversation_is_learned_from_when_it_ends(monkeypatch):
    learned = []
    monkeypatch.setattr(local_brain, "server_up", lambda timeout=2.0: True)
    monkeypatch.setattr(local_brain.LocalBrain, "learn", lambda self, lines: learned.append(lines))
    machine = sm.TronStateMachine("k", "m", "v", "p", 1, audio=FakeAudio(), cfg=SimpleNamespace(memory_enabled=True))
    machine._learn(["YOU:  play hindi songs", "TRON: Which ones, sir?", "YOU:  my preference is Karan Aujla"])
    deadline = time.time() + 3
    while not learned and time.time() < deadline:
        time.sleep(0.02)
    assert learned and learned[0][-1].endswith("Karan Aujla")


def test_learning_never_starts_ollama_itself(monkeypatch):
    learned = []
    monkeypatch.setattr(local_brain, "server_up", lambda timeout=2.0: False)
    monkeypatch.setattr(local_brain.LocalBrain, "learn", lambda self, lines: learned.append(lines))
    sm.TronStateMachine("k", "m", "v", "p", 1, audio=FakeAudio(), cfg=SimpleNamespace())._learn(["YOU:  hi"])
    time.sleep(0.2)
    assert learned == []


def test_a_known_preference_is_used_not_saved_again():
    """Asked for Hindi music, the local model re-saved "Karan Aujla" instead of playing it: the save is refused
    as already known, and the model is sent back to do the request with it."""
    import brain
    import memory
    import tools
    from tests.test_brain_engine import calls, engine
    memory.remember("preference", "hindi_music_artist", "User likes Karan Aujla for Hindi music.")
    b, ollama = engine(calls(("remember_fact", {"kind": "preference", "key": "hindi_music_artist", "value": "Karan Aujla"})),
                       calls(("play_music", {"query": "Karan Aujla"})))
    ran = []

    def run(name, args):
        ran.append(name)
        return tools.TOOL_DISPATCH[name](args, None) if name == "remember_fact" else "playing Karan Aujla - Softly on Spotify, sir"
    assert b.reply("play some hindi music", brain.Guard(), run) == "playing Karan Aujla - Softly on Spotify, sir"
    assert ran == ["remember_fact", "play_music"]
    assert [f["value"] for f in memory.all_facts()] == ["User likes Karan Aujla for Hindi music."]


def test_a_new_preference_is_still_saved():
    import memory
    import tools
    assert tools.TOOL_DISPATCH["remember_fact"]({"kind": "preference", "key": "hindi music", "value": "Arijit Singh"}, None) == "noted, sir"
    assert memory.all_facts()[0]["value"] == "Arijit Singh"


# --------------------------------------------------------------------------- names and closing
def test_misheard_names_are_matched_by_sound():
    import app_index
    names = ["claude", "calendar", "cloudflare one client", "spotify", "chatgpt", "notepad"]
    assert app_index.sounds_like("cloud code", names)[0][0] == "claude"
    assert app_index.sounds_like("spot if i", names)[0][0] == "spotify"
    assert app_index.sounds_like("chat gpt", names)[0][0] == "chatgpt"
    assert app_index.sounds_like("xylophone", names) == []


def test_open_uses_a_clear_sound_alike_and_otherwise_lists_suggestions(monkeypatch):
    import app_index
    import tools
    launched = []
    monkeypatch.setattr(app_index, "start_apps", lambda refresh=False: {"claude": "Claude!App", "calendar": "Cal!App"})
    monkeypatch.setattr(app_index, "resolve_start_app", lambda q, apps=None: None)
    monkeypatch.setattr(app_index, "resolve", lambda q, i: None)
    monkeypatch.setattr(app_index, "try_direct_launch", lambda n: False)
    monkeypatch.setattr(app_index, "launch_start_app", launched.append)
    monkeypatch.setattr(tools, "_get_app_index", lambda: {})
    assert "Claude" in tools.TOOL_DISPATCH["open_target"]({"name": "cloud code"}, None) and launched == ["Claude!App"]


def test_a_tray_app_with_no_window_is_closed_by_its_processes(monkeypatch):
    import psutil

    class P:
        def __init__(self, pid, name):
            self.info = {"pid": pid, "name": name}
            self.pid = pid

        def terminate(self):
            ended.append(self.pid)
    ended = []
    monkeypatch.setattr(desktop_control, "_open_windows", lambda: [])
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: [P(11, "ChatGPT.exe"), P(12, "svchost.exe"), P(13, "ChatGPT.exe")])
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: True)
    monkeypatch.setattr(psutil, "Process", lambda pid: P(pid, "x"))
    monkeypatch.setattr(psutil, "wait_procs", lambda procs, timeout: (procs, []))   # both exit on the close request
    monkeypatch.setattr(desktop_control.user32, "EnumWindows", lambda cb, l: None)
    assert desktop_control.close_app({"name": "ChatGPT"}) == "closed chatgpt, which was running in the background, sir"


def test_windows_own_processes_are_never_closed(monkeypatch):
    import psutil
    monkeypatch.setattr(desktop_control, "_open_windows", lambda: [])
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: [type("P", (), {"info": {"pid": 5, "name": "explorer.exe"}})()])
    assert "can't find" in desktop_control.close_app({"name": "explorer"})
