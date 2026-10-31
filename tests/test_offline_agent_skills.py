# tests/test_offline_agent_skills.py
"""Offline mode, step-by-step PC control, skills, and the glitches reported on 2026-10-07."""
import zipfile

import pytest

import brain
import config
import music
import offline
import skills
import state_manager as sm
from tests.test_state_manager import FakeAudio, FakeSession


@pytest.fixture(autouse=True)
def app_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "app_dir", lambda: tmp_path)
    return tmp_path


# --------------------------------------------------------------------------- offline understanding
@pytest.mark.parametrize("said, expected", [
    ("turn on the wifi", ("set_radio", {"kind": "wifi", "enabled": True})),
    ("switch off bluetooth", ("set_radio", {"kind": "bluetooth", "enabled": False})),
    ("my internet is not working, fix it", ("_fix_wifi", {})),
    ("troubleshoot the wi-fi", ("_fix_wifi", {})),
    ("set the volume to 30", ("set_volume", {"level": 30})),
    ("volume up", ("change_volume", {"delta": 20})),
    ("what time is it", ("current_time", {})),
    ("open spotify", ("open_target", {"name": "spotify"})),
    ("shut up", ("_stop", {})),
    ("shut down the computer", ("_confirm:shutdown_pc", {})),
    ("set a timer for five minutes", ("set_timer", {"seconds": 300, "label": ""})),
    ("play the music", ("media_play_pause", {})),
])
def test_offline_commands_are_understood(said, expected):
    assert offline.understand(said) == expected


def test_an_unknown_request_offline_gets_the_help_line():
    assert offline.understand("tell me a joke") is None


class FakeVoice:
    def __init__(self):
        self.said = []

    def say(self, text):
        self.said.append(text)


def test_offline_session_reconnects_and_hands_back(monkeypatch):
    monkeypatch.setattr(offline, "fix_wifi", lambda say: (True, "Connected to Home, sir."))
    voice = FakeVoice()
    assert offline.Session(voice=voice, hear=lambda: None).run() is True
    assert "Trying to reconnect" in voice.said[0] and voice.said[-1] == "Connected to Home, sir."


def test_offline_session_runs_commands_and_asks_before_shutdown(monkeypatch):
    import tools
    monkeypatch.setattr(offline, "fix_wifi", lambda say: (False, "No saved network is in range, sir."))
    ran = []
    monkeypatch.setitem(tools.TOOL_DISPATCH, "set_radio",
                        lambda a, c: ran.append(("radio", a)) or "Bluetooth is on, sir")
    monkeypatch.setitem(tools.TOOL_DISPATCH, "shutdown_pc", lambda a, c: ran.append("shutdown") or "shutting down")
    monkeypatch.setattr(offline, "online", lambda timeout=1.5: False)
    said = iter(["turn on bluetooth", "shut down the computer", "no", "shut up"])
    voice = FakeVoice()
    assert offline.Session(voice=voice, hear=lambda: next(said, None)).run() is False
    assert ran == [("radio", {"kind": "bluetooth", "enabled": True})]     # no shutdown without a yes
    assert "Shall I shut down the PC?" in voice.said


def test_waking_tron_with_no_internet_goes_offline_first(monkeypatch):
    calls = []
    monkeypatch.setattr(sm.TronStateMachine, "_online", lambda self: False)
    monkeypatch.setattr(sm.TronStateMachine, "_run_offline", lambda self: calls.append("offline") or False)
    machine = sm.TronStateMachine("k", "m", "v", "p", 1, audio=FakeAudio(),
                                  session_factory=lambda: pytest.fail("Gemini must not be tried offline"))
    machine.trigger()
    assert calls == ["offline"]


def test_reconnecting_offline_continues_with_the_real_conversation(monkeypatch):
    monkeypatch.setattr(sm.TronStateMachine, "_online", lambda self: False)
    monkeypatch.setattr(sm.TronStateMachine, "_run_offline", lambda self: True)
    opened = []
    machine = sm.TronStateMachine("k", "m", "v", "p", 0.2, audio=FakeAudio(),
                                  session_factory=lambda: opened.append(1) or FakeSession(events=[]))
    machine.trigger()
    assert opened == [1]


# --------------------------------------------------------------------------- skills
def test_a_skill_md_installs_and_shows_up_in_tron_instructions(tmp_path):
    md = tmp_path / "in.md"
    md.write_text("---\nname: Pomodoro\ndescription: When the user says focus time, run a 25 minute timer.\n"
                  "---\n1. set_timer seconds=1500 label=focus\n", encoding="utf-8")
    assert skills.install(md) == "Pomodoro"
    assert "Pomodoro: When the user says focus time" in skills.context()
    assert "set_timer seconds=1500" in skills.use_skill({"name": "pomodoro"})


def test_a_claude_skill_zip_installs_with_its_files(tmp_path):
    archive = tmp_path / "report.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("weekly-report/SKILL.md",
                   "---\nname: weekly-report\ndescription: Write the weekly report.\n---\nSteps")
        z.writestr("weekly-report/template.txt", "Week: ...")
        z.writestr("weekly-report/../../evil.txt", "must never be written outside the skill")
    assert skills.install(archive) == "weekly-report"
    installed = skills.skills_dir() / "weekly-report"
    assert (installed / "template.txt").exists()
    assert "template.txt" in skills.use_skill({"name": "weekly-report"})
    assert not (tmp_path / "evil.txt").exists() and not (skills.skills_dir() / "evil.txt").exists()


def test_something_that_isnt_a_skill_is_refused(tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    with pytest.raises(ValueError):
        skills.install(folder)


def test_skills_are_in_the_system_prompt(monkeypatch):
    skills.install_example()
    monkeypatch.setattr(sm.memory, "long_term_context", lambda: "")
    monkeypatch.setattr(sm.memory, "recent_context", lambda: "")
    machine = sm.TronStateMachine("k", "m", "v", "persona", 1, audio=FakeAudio())
    assert "morning-routine" in machine._system_prompt()


# --------------------------------------------------------------------------- step-by-step control safety
def test_clicking_delete_needs_a_spoken_yes(monkeypatch):
    import computer
    monkeypatch.setattr(computer, "element_name", lambda n: "Delete" if str(n) == "3" else "Open")
    guard = brain.Guard()
    guard.user_said("delete the old report")
    assert 'click "Delete"' in guard.check("click_element", {"number": 3})
    assert guard.check("click_element", {"number": 4}) is None
    guard.turn_over()
    guard.user_said("yes")
    assert guard.check("click_element", {"number": 3}) is None


def test_press_keys_refuses_alt_f4():
    import computer
    assert "won't" in computer.press_keys({"keys": "alt+f4"})


# --------------------------------------------------------------------------- the reported glitches
def test_a_remix_never_passes_for_the_original():
    assert not music.same_version("Blinding Lights", "Blinding Lights - Chromatics Remix")
    assert music.same_version("Blinding Lights Remix", "Blinding Lights - Chromatics Remix")
    assert music.same_version("Blinding Lights", "Blinding Lights")


def test_spotify_volume_uses_spotifys_own_slider(monkeypatch):
    """TRON said "already at 100 percent" from the mixer while Spotify's own slider showed 50."""
    class Slider:
        CurrentValue = 0.5

        def SetValue(self, v):
            Slider.CurrentValue = v

    monkeypatch.setattr(music, "_volume_slider", lambda: Slider())
    monkeypatch.setattr(music.time, "sleep", lambda s: None)
    import tools
    reply = tools.TOOL_DISPATCH["set_app_volume"]({"app": "Spotify", "delta": 20}, None)
    assert reply == "Spotify is at 70 percent, sir"


def test_shut_up_mid_reply_stops_it():
    """"shut up" got two replies; the stop must land as soon as the words are in, not at the next reply."""
    import asyncio

    class Talky(FakeSession):
        async def receive(self):
            yield {"type": "transcript", "role": "user", "text": "shut up"}
            await asyncio.sleep(1.0)    # the user has finished; TRON is about to answer
            yield {"type": "audio", "data": b"\x00\x10" * 2400}
            yield {"type": "audio", "data": b"\x00\x10" * 2400}
            await asyncio.Event().wait()

    audio = FakeAudio()
    machine = sm.TronStateMachine("k", "m", "v", "p", 30, audio=audio, session_factory=lambda: Talky())
    machine.trigger()
    assert audio.played == []


def test_geminis_session_limit_ends_the_conversation_cleanly(app_dir):
    """A long conversation hit Gemini's session limit; ignoring its GoAway got it cut off as an error."""
    import convo_log
    states = []
    machine = sm.TronStateMachine("k", "m", "v", "p", 30, audio=FakeAudio(), on_state_change=states.append,
                                  session_factory=lambda: FakeSession(events=[{"type": "go_away"}]))
    machine.trigger()
    assert states[-1] is sm.State.IDLE
    assert "session time limit" in convo_log.path().read_text(encoding="utf-8")


def test_parakeet_hears_the_users_own_command(monkeypatch):
    """On the user's recording, Parakeet heard every "shut down the computer"; the old Whisper base.en
    once heard "shut down a little bit"."""
    import wave
    from pathlib import Path
    import numpy as np
    here = Path(__file__).resolve().parent.parent
    if not (here / "models" / "parakeet-tdt-0.6b-v2").exists() or not (here / "mic_test.wav").exists():
        pytest.skip("speech model or recording not present")
    monkeypatch.setattr(config, "app_dir", lambda: here)   # the model lives in the repo; restored after, or later tests log into it
    w = wave.open(str(here / "mic_test.wav"))
    audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    heard = offline.transcribe(audio[int(16000 * 30):]).lower()
    assert "shut down the computer" in heard
    assert offline.understand(heard)[0] == "_confirm:shutdown_pc"
