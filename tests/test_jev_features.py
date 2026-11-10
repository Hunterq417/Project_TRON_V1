# tests/test_jev_features.py
"""The features brought over from Hey Jev, plus video clipping."""
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

import config
import dictation
import state_manager as sm
import timers
import tools
import video_clip
from tests.test_state_manager import FakeAudio, FakeSession


@pytest.fixture(autouse=True)
def app_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "app_dir", lambda: tmp_path)
    timers.cancel(everything=True)
    yield tmp_path
    timers.cancel(everything=True)


@pytest.fixture(scope="module")
def tk_root():
    """One Tk for every panel test: creating a second one in the same process fails on Windows."""
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


# --------------------------------------------------------------------------- timers
def test_timer_set_check_cancel_through_the_tools():
    assert "5 minutes" in tools.TOOL_DISPATCH["set_timer"]({"seconds": 300}, None)
    assert "call mum" in tools.TOOL_DISPATCH["set_timer"]({"seconds": 1200, "label": "call mum"}, None)
    left = tools.TOOL_DISPATCH["check_timers"]({}, None)
    assert "5 minutes left" in left and "Call mum: 20 minutes left" in left
    assert tools.TOOL_DISPATCH["cancel_timer"]({}, None) == "timer cancelled, sir"   # the newest one
    assert [name for name, _ in timers.snapshot()] == ["5 min timer"]
    assert "all" in tools.TOOL_DISPATCH["cancel_timer"]({"all": True}, None) or timers.snapshot() == []


def test_a_timer_with_no_length_asks_rather_than_firing_at_once():
    assert "how long" in tools.TOOL_DISPATCH["set_timer"]({"seconds": 0}, None)
    assert timers.snapshot() == []


def test_due_timers_are_handed_over_exactly_once():
    timers.add(10, "tea")
    assert timers.due(time.time()) == []
    done = timers.due(time.time() + 11)
    assert [t["label"] for t in done] == ["tea"]
    assert timers.due(time.time() + 11) == []


def test_say_duration_reads_naturally():
    assert timers.say_duration(250) == "4 minutes and 10 seconds"
    assert timers.say_duration(3725) == "1 hour and 2 minutes"
    assert timers.say_duration(60) == "1 minute"


# --------------------------------------------------------------------------- dictation
def _fake_stream(blocks, session_ref):
    """A mic that plays `blocks` (seconds, loudness) then stops the session itself."""
    class Stream:
        def __init__(self, callback):
            self.callback = callback

        def __enter__(self):
            def feed():
                for secs, loud in blocks:
                    for _ in range(int(secs * 10)):
                        samples = np.full(dictation.BLOCK, int(loud * 32767), dtype=np.int16)
                        self.callback(samples.tobytes())
                        time.sleep(0.003)   # arrive over time, like a real mic, so pauses can be seen
                session_ref[0].stop()
            threading.Thread(target=feed, daemon=True).start()
            return self

        def __exit__(self, *exc):
            return False
    return Stream


def test_dictation_transcribes_fixes_vocab_and_keeps_history(monkeypatch):
    dictation.save_vocab({"GitHub": ["git hub"]})
    heard = []
    ref = []
    session = dictation.Session(lambda wav: heard.append(len(wav)) or "push it to git hub",
                                stream_factory=_fake_stream([(1.0, 0.2)], ref))
    ref.append(session)
    stopped = []
    text, failed, total = session.run(poll=0.01, on_stopped=lambda: stopped.append(True))
    assert (text, failed, total) == ("push it to GitHub", 0, 1)
    assert stopped == [True]
    assert dictation.history()[0]["text"] == "push it to GitHub"


def test_long_dictation_is_cut_into_chunks_at_a_pause(monkeypatch):
    monkeypatch.setattr(dictation, "CHUNK_SECS", 1)
    monkeypatch.setattr(dictation, "CHUNK_GRACE_SECS", 5)
    ref = []
    session = dictation.Session(lambda wav: "part", stream_factory=_fake_stream(
        [(1.5, 0.2), (0.5, 0.0), (1.0, 0.2)], ref))
    ref.append(session)
    _text, failed, total = session.run(poll=0.001)
    assert failed == 0 and total >= 2


def test_a_failed_chunk_keeps_its_audio_and_is_not_saved_as_history(app_dir):
    def broken(wav):
        raise RuntimeError("gemini down")
    ref = []
    session = dictation.Session(broken, stream_factory=_fake_stream([(0.5, 0.2)], ref))
    ref.append(session)
    text, failed, total = session.run(poll=0.01)
    assert (failed, total) == (1, 1) and "[missing part]" in text
    assert list((app_dir / "memory" / "dictation_failed").glob("*.wav"))
    assert dictation.history() == []


def test_silence_marker_never_reaches_the_user(monkeypatch):
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = SimpleNamespace(text=dictation.SILENCE)
    monkeypatch.setattr("google.genai.Client", lambda api_key: fake_client)
    assert dictation.gemini_transcriber("k")(b"wav") == ""


def test_start_dictation_ends_the_conversation_then_dictates(monkeypatch):
    pasted = []
    monkeypatch.setattr(dictation, "paste", pasted.append)
    monkeypatch.setattr("winsound.PlaySound", lambda *a: None)

    class FakeDictation:
        levels = ()
        active = True

        def __init__(self, transcribe, device=None):
            pass

        def run(self, on_stopped=None):
            on_stopped()
            return "hello world", 0, 1

        def stop(self):
            self.active = False

    monkeypatch.setattr(dictation, "Session", FakeDictation)
    session = FakeSession(events=[{"type": "tool_call", "calls": [
        {"id": "1", "name": "start_dictation", "args": {}}]}])
    states = []
    machine = sm.TronStateMachine("k", "m", "v", "p", silence_timeout_s=30, on_state_change=states.append,
                                  audio=FakeAudio(), session_factory=lambda: session)
    machine._transcriber = object()
    resumed = []
    machine.on_dictation_start = lambda: resumed.append(True)

    started = time.monotonic()
    machine.trigger()
    assert time.monotonic() - started < 10          # hung up well before the 30s silence timeout
    assert "chime" in session.sent_tool_responses[0][2]
    assert pasted == ["hello world"] and resumed == [True]
    assert sm.State.DICTATING in states and states[-1] is sm.State.IDLE
    assert machine.dictation is None


def test_trigger_during_dictation_stops_it_instead_of_starting_a_conversation():
    machine = sm.TronStateMachine("k", "m", "v", "p", 1, audio=FakeAudio(), session_factory=lambda: FakeSession())
    machine.dictation = MagicMock(active=True)
    machine.trigger()
    machine.dictation.stop.assert_called_once()
    assert machine.state is sm.State.IDLE


# --------------------------------------------------------------------------- video clipping
def test_clip_checks_its_times_before_looking_for_a_video(monkeypatch):
    monkeypatch.setattr(video_clip, "current_video", lambda: pytest.fail("should not look"))
    assert "start and end" in video_clip.clip_video({"start_seconds": "soon"})
    assert "after its start" in video_clip.clip_video({"start_seconds": 90, "end_seconds": 30})


def test_clip_without_a_browser_video_says_so(monkeypatch):
    monkeypatch.setattr(video_clip, "current_video", lambda: None)
    assert "can't see a video" in video_clip.clip_video({"start_seconds": 1, "end_seconds": 5})


def test_clip_runs_in_the_background_and_reports_back(monkeypatch):
    monkeypatch.setattr(video_clip, "current_video", lambda: ("https://youtube.com/watch?v=x", "Cats"))
    calls = []
    monkeypatch.setattr(video_clip, "_run_ytdlp", lambda url, s, e: calls.append((url, s, e)) or "C:/clip.mp4")
    told = threading.Event()
    messages = []
    monkeypatch.setattr(video_clip, "on_finished", lambda m: (messages.append(m), told.set()))
    reply = video_clip.clip_video({"start_seconds": 80, "end_seconds": 125})
    assert '"Cats" from 1:20 to 2:05' in reply
    assert told.wait(5)
    assert calls == [("https://youtube.com/watch?v=x", 80.0, 125.0)]
    assert "saved in Videos, TRON Clips" in messages[0]


def test_ytdlp_is_asked_for_just_the_section(monkeypatch, tmp_path):
    exe = tmp_path / "yt-dlp.exe"
    exe.write_text("")
    monkeypatch.setattr(video_clip, "_ytdlp", lambda: exe)
    monkeypatch.setattr(video_clip, "_ffmpeg_dir", lambda: tmp_path)
    monkeypatch.setattr(video_clip, "clips_dir", lambda: tmp_path / "clips")
    out = tmp_path / "clips" / "Cats [1-20 to 2-05].mp4"
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["env"] = cmd, kw["env"]
        out.parent.mkdir(exist_ok=True)
        out.write_text("x")
        return SimpleNamespace(returncode=0, stdout=f"{out}\n", stderr="")

    monkeypatch.setattr(video_clip.subprocess, "run", fake_run)
    assert video_clip._run_ytdlp("https://youtube.com/watch?v=x", 80, 125) == str(out)
    cmd = seen["cmd"]
    assert cmd[cmd.index("--download-sections") + 1] == "*80.00-125.00"
    assert "--force-keyframes-at-cuts" in cmd
    # yt-dlp's section check ignores --ffmpeg-location and only searches PATH
    assert seen["env"]["PATH"].startswith(str(tmp_path))


def test_stamp_formats_like_a_player():
    assert video_clip.stamp(80) == "1:20"
    assert video_clip.stamp(3725) == "1:02:05"


# --------------------------------------------------------------------------- new desktop tools
def test_open_website_refuses_a_sentence_as_a_url():
    assert "which website" in tools.TOOL_DISPATCH["open_website"]({"url": "the bbc news site"}, None)


def test_every_new_tool_is_declared_and_handled():
    declared = {d["name"] for d in tools.TOOL_DECLARATIONS}
    for name in ("set_timer", "check_timers", "cancel_timer", "start_dictation", "focus_app", "minimize_app",
                 "set_app_volume", "open_website", "new_tab", "set_dark_mode", "lock_pc", "sleep_pc",
                 "clip_video"):
        assert name in declared
        assert name in tools.TOOL_DISPATCH or name in tools.CONTROL_TOOL_NAMES


# --------------------------------------------------------------------------- control panel

def test_the_stop_phrase_is_not_typed_into_the_dictation():
    assert dictation.strip_stop_phrase("Send the report by Friday. Hey Drone.") == "Send the report by Friday."
    assert dictation.strip_stop_phrase("Send it, hey tron") == "Send it"
    keep = "Hey Tron is my assistant and I like it."
    assert dictation.strip_stop_phrase(keep) == keep


def test_clipping_past_the_end_explains_the_length(monkeypatch):
    def too_far(url, s, e):
        raise RuntimeError("ffmpeg exited with code 4294967262")
    monkeypatch.setattr(video_clip, "_run_ytdlp", too_far)
    monkeypatch.setattr(video_clip, "_duration", lambda url: 45.0)
    monkeypatch.setattr(video_clip, "current_video", lambda: ("https://youtube.com/shorts/x", "Short"))
    done = threading.Event()
    messages = []
    monkeypatch.setattr(video_clip, "on_finished", lambda m: (messages.append(m), done.set()))
    video_clip.clip_video({"start_seconds": 60, "end_seconds": 63})
    assert done.wait(5)
    assert "only 0:45 long" in messages[0]


# --------------------------------------------------------------------------- OpenRouter for dictation
def test_openrouter_transcription_sends_what_jev_sent(monkeypatch):
    import requests
    seen = {}

    def fake_post(url, headers, json, timeout):
        seen.update(url=url, headers=headers, body=json)
        return SimpleNamespace(ok=True, status_code=200, json=lambda: {"text": "hello there"})

    monkeypatch.setattr(requests, "post", fake_post)
    assert dictation.openrouter_transcriber("or-key")(b"RIFFwav") == "hello there"
    assert seen["url"] == "https://openrouter.ai/api/v1/audio/transcriptions"
    assert seen["headers"]["Authorization"] == "Bearer or-key"
    assert seen["body"]["model"] == "openai/gpt-4o-mini-transcribe"
    assert seen["body"]["input_audio"]["format"] == "wav"


def test_openrouter_goes_first_and_gemini_takes_over_when_it_fails(monkeypatch):
    order = []

    def failing(key):
        def t(wav):
            order.append("openrouter")
            raise RuntimeError("OpenRouter said 502")
        return t

    def gemini(key):
        def t(wav):
            order.append("gemini")
            return "from gemini"
        return t

    monkeypatch.setattr(dictation, "openrouter_transcriber", failing)
    monkeypatch.setattr(dictation, "gemini_transcriber", gemini)
    assert dictation.best_transcriber("g", "o")(b"w") == "from gemini"
    assert order == ["openrouter", "gemini"]
    order.clear()
    dictation.best_transcriber("g", "")(b"w")   # no OpenRouter key: straight to Gemini
    assert order == ["gemini"]


def test_an_echoed_prompt_is_stripped():
    echoed = dictation.OPENROUTER_PROMPT + " Buy milk and eggs."
    assert dictation._strip_prompt(echoed) == "Buy milk and eggs"


def test_an_openrouter_account_without_credit_is_skipped_after_the_first_try(monkeypatch):
    calls = []

    def broke(key):
        def t(wav):
            calls.append("openrouter")
            raise RuntimeError("OpenRouter said 402: requires at least $0.50 in balance for audio")
        return t

    monkeypatch.setattr(dictation, "openrouter_transcriber", broke)
    monkeypatch.setattr(dictation, "gemini_transcriber", lambda key: lambda wav: "ok")
    transcribe = dictation.best_transcriber("g", "o")
    assert [transcribe(b"w") for _ in range(3)] == ["ok", "ok", "ok"]
    assert calls == ["openrouter"]


def test_relaunch_asks_the_new_exe_to_unpack_afresh(monkeypatch):
    import main
    seen = {}
    monkeypatch.setattr("subprocess.Popen", lambda cmd, **kw: seen.update(cmd=cmd, **kw))
    main._launch_tron()
    assert seen["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert seen["cmd"][-1].endswith("main.py")   # from source; the frozen exe relaunches itself
