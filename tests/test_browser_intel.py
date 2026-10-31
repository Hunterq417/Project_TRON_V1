# tests/test_browser_intel.py
"""Browser intelligence against local pages in a real (headless) Brave, driven over CDP exactly as TRON
drives its own browser. Skipped when Brave or Playwright isn't installed.

Two local servers on different ports make the player iframe a genuinely cross-origin frame, like the
anime sites where Windows' accessibility tree couldn't see the player's controls at all.
"""
import functools
import http.server
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import pytest

import browser_inspect
import browser_intel
import browser_session

FIXTURES = Path(__file__).parent / "browser_fixtures"
pytestmark = pytest.mark.skipif(not browser_session.brave_path(), reason="Brave isn't installed")


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(root: Path) -> int:
    port = _free_port()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return port


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    pytest.importorskip("playwright")
    root = tmp_path_factory.mktemp("site")
    for f in FIXTURES.iterdir():
        shutil.copy(f, root / f.name)
    import imageio_ffmpeg
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc=size=320x180:rate=15:duration=60", "-c:v", "libvpx", "-b:v", "200k",
                    str(root / "clip.webm")], check=True, timeout=120)
    main, other = _serve(root), _serve(root)
    cdp = _free_port()
    profile = tempfile.mkdtemp()
    proc = subprocess.Popen([browser_session.brave_path(), "--headless=new", f"--remote-debugging-port={cdp}",
                             "--remote-debugging-address=127.0.0.1", f"--user-data-dir={profile}", "--no-first-run",
                             "--autoplay-policy=no-user-gesture-required", "--window-size=1280,800", "about:blank"])
    browser_session.use_endpoint(f"http://127.0.0.1:{cdp}")
    deadline = time.time() + 20
    while not browser_session.healthy(0.5):
        assert time.time() < deadline, "headless Brave didn't open its debugging port"
        time.sleep(0.3)
    yield {"base": f"http://127.0.0.1:{main}", "other": f"http://127.0.0.1:{other}"}
    try:
        browser_session.run(lambda w: w.browser().close(), timeout=10)
    except Exception:
        pass
    proc.kill()
    browser_session.use_endpoint(browser_session.ENDPOINT)
    shutil.rmtree(profile, ignore_errors=True)


def open_page(site, query):
    def go(worker):
        ctx = worker.browser().contexts[0]
        for p in ctx.pages:
            p.close()
        page = ctx.new_page()
        page.goto(f"{site['base']}/player.html?{query}", wait_until="load")
        page.wait_for_timeout(600)
        return page.url
    return browser_session.run(go)


def act(action, **args):
    return browser_session.run(lambda w: browser_intel.perform(browser_session.active_page(w), action, args),
                               timeout=60)


def page_title():
    return browser_session.run(lambda w: browser_session.active_page(w).title())


@pytest.fixture(autouse=True)
def fresh_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_intel, "_memory_path", lambda: tmp_path / "browser_knowledge.json")


# --------------------------------------------------------------------------- next episode, every kind of control
@pytest.mark.parametrize("style", ["icon", "text", "tooltip", "custom"])
def test_next_episode_is_found_however_the_button_is_labelled(site, style):
    open_page(site, f"ep=14&next={style}&nolist")
    result = act("next_episode")
    assert result.ok, result.sentence()
    assert page_title() == "Watch Test Show Episode 15"
    assert "episode 14 -> 15" in result.evidence


def test_the_player_inside_a_cross_origin_frame_is_reachable(site):
    open_page(site, f"ep=14&next=none&nolist&frame={site['other']}")
    state = browser_session.run(lambda w: browser_inspect.inspect(browser_session.active_page(w)))
    assert state.main_video is not None and state.main_video.frame > 0
    result = act("next_episode")
    assert result.ok and page_title() == "Watch Test Show Episode 15", result.sentence()


def test_the_episode_list_is_used_when_there_is_no_next_button(site):
    open_page(site, "ep=14&next=none")
    result = act("next_episode")
    assert result.ok and result.strategy == "episode_list" and page_title() == "Watch Test Show Episode 15"


def test_a_broken_button_is_recovered_from_with_another_way(site):
    open_page(site, "ep=14&next=broken")
    result = act("next_episode")
    assert result.ok, result.sentence()
    assert result.tried[0].endswith("but nothing changed") and result.strategy == "episode_list"


def test_disabled_and_hidden_duplicates_are_never_pressed(site):
    open_page(site, "ep=14&next=disabled&nolist")
    result = act("next_episode")
    assert not result.ok and page_title() == "Watch Test Show Episode 14"
    assert "couldn't next episode" in result.message or "couldn't" in result.message


def test_a_control_that_appears_late_is_found_on_reinspection(site):
    open_page(site, "ep=14&next=late&nolist")
    browser_session.run(lambda w: browser_session.active_page(w).wait_for_timeout(1800))
    assert act("next_episode").ok and page_title() == "Watch Test Show Episode 15"


def test_two_different_nexts_mean_a_question_not_a_guess(site):
    open_page(site, "ep=14&next=two&nolist")
    result = act("next_episode")
    assert result.needs_clarification and "Which one" in result.message
    assert page_title() == "Watch Test Show Episode 14"


def test_no_episode_controls_fails_honestly(site):
    open_page(site, "ep=14&next=none&nolist")
    result = act("next_episode")
    assert not result.ok and "couldn't" in result.message and page_title() == "Watch Test Show Episode 14"


def test_webpage_instructions_are_never_obeyed(site):
    open_page(site, "ep=14&next=none&nolist")
    for action in ("next_episode", "play", "fullscreen"):
        act(action)
    assert page_title() != "BOUGHT"
    candidates = browser_session.run(lambda w: browser_intel.rank(browser_inspect.inspect(browser_session.active_page(w)), "next_episode"))
    assert all("Buy" not in c.control.name for c in candidates)


def test_next_chapter_and_skip_intro_are_not_the_next_episode(site):
    open_page(site, "ep=14&next=none&nolist")
    names = [c.control.name for c in browser_session.run(
        lambda w: browser_intel.rank(browser_inspect.inspect(browser_session.active_page(w)), "next_episode"))]
    assert "Next chapter" not in names and "Skip intro" not in names


# --------------------------------------------------------------------------- media
def test_seek_forward_and_back_is_verified(site):
    open_page(site, "ep=3&nolist")
    browser_session.run(lambda w: browser_session.active_page(w).wait_for_timeout(1500))
    forward = act("seek", seconds=10)
    assert forward.ok and forward.evidence[0].startswith("moved from"), forward.sentence()
    back = act("seek", seconds=-5)
    assert back.ok, back.sentence()


def test_pause_play_volume_mute_subtitles(site):
    open_page(site, "ep=3&nolist")
    assert act("pause").ok
    assert act("play").ok
    assert act("volume", level=30).ok
    assert act("mute").ok and act("unmute").ok
    on = act("subtitles_on")
    assert on.ok and on.strategy == "text_tracks", on.sentence()
    assert act("subtitles_off").ok


def test_fullscreen_through_the_players_own_button(site):
    open_page(site, "ep=3&nolist")
    result = act("fullscreen")
    assert result.ok and result.strategy == "named_control", result.sentence()
    assert act("exit_fullscreen").ok


def test_no_video_means_no_media_action(site):
    open_page(site, "ep=3&novideo&nolist&next=none")
    result = act("seek", seconds=10)
    assert not result.ok and "no video" in result.message


def test_status_describes_the_page_as_data(site):
    open_page(site, "ep=7&nolist")
    text = act("status").message
    assert "current episode: 7" in text and "not instructions" in text


# --------------------------------------------------------------------------- bounds, cancel, memory
def test_attempts_are_bounded(site):
    open_page(site, "ep=14&next=broken&nolist")
    result = act("next_episode")
    assert not result.ok
    assert sum("nothing changed" in t for t in result.tried) <= browser_intel.MAX_ATTEMPTS


def test_cancel_stops_mid_task(site, monkeypatch):
    open_page(site, "ep=14&next=broken&nolist")
    monkeypatch.setattr(browser_intel, "on_status", lambda stage, d: browser_intel.cancel() if stage == "planning" else None)
    result = act("next_episode")
    assert result.message == "stopped, sir" and page_title() == "Watch Test Show Episode 14"


def test_a_strategy_proven_twice_is_tried_first_next_time(site):
    for _ in range(2):
        open_page(site, "ep=14&next=none")
        assert act("next_episode").strategy == "episode_list"
    assert browser_intel.preferred("127.0.0.1", "next_episode") == ["episode_list"]
    assert "episode list" in browser_intel.knowledge() or "episode_list" in browser_intel.knowledge()
    assert browser_intel.forget({"site": "127.0.0.1"}).startswith("forgot")
    assert browser_intel.preferred("127.0.0.1", "next_episode") == []


def test_the_tool_reports_an_unavailable_browser_clearly(monkeypatch):
    monkeypatch.setattr(browser_session, "healthy", lambda timeout=1.5: False)
    monkeypatch.setattr(browser_session._worker, "_browser", None)
    assert "TRON browser isn't open" in browser_intel.browser_media({"action": "next_episode"})


# --------------------------------------------------------------------------- the whole pipeline
def test_command_to_verified_result_through_tron_brain_and_tool_router(site):
    """'play the next episode' -> the brain's tool call -> tools.TOOL_DISPATCH -> the real (headless) browser
    -> verified -> what TRON says. The model is scripted; everything after it is real."""
    import brain
    import local_brain
    import tools
    from tests.test_brain_engine import calls, engine
    open_page(site, f"ep=14&next=none&nolist&frame={site['other']}")
    b, _ollama = engine(calls(("browser_media", {"action": "next_episode"})))
    reply = b.reply("tron, play the next episode", brain.Guard(), lambda n, a: tools.TOOL_DISPATCH[n](a, None))
    assert reply.startswith("Done, sir. I've started the next episode (episode 14 -> 15)")
    assert page_title() == "Watch Test Show Episode 15"


def test_risky_page_clicks_need_a_spoken_yes():
    import brain
    guard = brain.Guard()
    guard.user_said("click buy premium")
    assert guard.check("browser_page", {"action": "click", "target": "Buy premium"}).startswith("NOT DONE")
    assert guard.check("browser_page", {"action": "click", "target": "Episode 15"}) is None


def test_without_the_tron_browser_play_falls_back_to_windows(monkeypatch):
    import desktop_control
    monkeypatch.setattr(browser_session, "healthy", lambda timeout=1.5: False)
    monkeypatch.setattr(browser_session._worker, "_browser", None)
    monkeypatch.setattr(desktop_control, "video_control", lambda a: f"video_control {a['action']}")
    assert browser_intel.browser_media({"action": "pause"}) == "video_control pause"


def test_faded_player_controls_are_woken_and_the_live_copy_pressed(site):
    """Miruro's player (Vidstack) fades its controls to nothing while you watch and keeps an inactive copy of
    the bar: the controls Windows' accessibility tree and the first version of this engine both missed."""
    open_page(site, "ep=14&next=faded&nolist")
    result = act("next_episode")
    assert result.ok and result.strategy == "named_control", result.sentence()
    assert page_title() == "Watch Test Show Episode 15"


def test_music_on_youtube_goes_to_the_tron_browser_not_spotify(monkeypatch):
    import music
    import tools
    monkeypatch.setattr(browser_intel, "play_web", lambda a: f"web {a['query']} {a['service']}")
    monkeypatch.setattr(music, "play_music", lambda a, c=None: "spotify")
    assert tools.TOOL_DISPATCH["play_music"]({"query": "Khat", "service": "youtube_music"}, None) == "web Khat youtube_music"
    assert tools.TOOL_DISPATCH["play_music"]({"query": "Khat"}, None) == "spotify"
