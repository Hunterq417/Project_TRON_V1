# tests/test_brain.py
"""The decision layer, echo gate, music matching and conversation log — each from a real failure."""
import config
import brain
import convo_log
import music
import state_manager as sm
from tests.test_state_manager import FakeAudio, FakeSession


# --------------------------------------------------------------------------- stop phrases
def test_shut_up_and_friends_are_stop_phrases():
    for said in ("shut up", "Shut up!", "stop", "stop talking", "be quiet", "hey tron, shut up", "enough",
                 "never mind", "bas karo", "chup"):
        assert brain.is_stop(said), said


def test_commands_that_start_with_stop_are_not_stop_phrases():
    for said in ("stop the music", "shut down my pc", "stop the timer", "quiet the volume a bit", ""):
        assert not brain.is_stop(said), said


# --------------------------------------------------------------------------- confirmation
class Clock:
    now = 100.0

    def __call__(self):
        return self.now


def test_shutdown_needs_a_spoken_yes():
    guard = brain.Guard()
    guard.user_said("shut down my pc")
    assert "NOT DONE" in guard.check("shutdown_pc", {})
    guard.turn_over()
    guard.user_said("yes")
    assert guard.check("shutdown_pc", {}) is None


def test_shut_up_never_reaches_shutdown():
    """The 2026-10-06 bug: "shut up" -> shutdown_pc, twice."""
    guard = brain.Guard()
    guard.user_said("shut up")
    assert "stop talking" in guard.check("shutdown_pc", {})


def test_a_no_or_an_old_yes_does_not_count():
    clock = Clock()
    guard = brain.Guard(clock)
    guard.user_said("no, don't")
    assert guard.check("restart_pc", {})
    guard.turn_over()
    guard.user_said("yes")
    guard.turn_over()
    clock.now += brain.YES_FRESH_FOR + 1
    assert guard.check("restart_pc", {})


def test_the_models_duplicate_call_is_dropped():
    guard = brain.Guard()
    guard.user_said("yes")
    assert guard.check("shutdown_pc", {}) is None
    assert "already done" in guard.check("shutdown_pc", {})


def test_only_destructive_tools_are_gated():
    guard = brain.Guard()
    assert guard.check("open_target", {"name": "spotify"}) is None
    assert guard.check("set_radio", {"kind": "bluetooth", "enabled": False}) is None
    assert guard.check("set_radio", {"kind": "wifi", "enabled": False})   # cuts TRON off: needs a yes


# --------------------------------------------------------------------------- in a real conversation
def _machine(events, monkeypatch, tmp_path, audio=None):
    monkeypatch.setattr(config, "app_dir", lambda: tmp_path)
    session = FakeSession(events=events)
    machine = sm.TronStateMachine("k", "m", "v", "p", silence_timeout_s=2,
                                  audio=audio or FakeAudio(), session_factory=lambda: session)
    return machine, session


def test_shut_up_ends_the_conversation_without_running_anything(monkeypatch, tmp_path):
    ran = []
    monkeypatch.setitem(sm.tools.TOOL_DISPATCH, "shutdown_pc", lambda a, c: ran.append(1) or "shutting down")
    machine, session = _machine([
        {"type": "transcript", "role": "user", "text": "shut up"},
        {"type": "tool_call", "calls": [{"id": "1", "name": "shutdown_pc", "args": {}}]},
    ], monkeypatch, tmp_path)
    machine.trigger()
    assert ran == [] and session.sent_tool_responses == []
    log = convo_log.path().read_text(encoding="utf-8")
    assert 'YOU:  shut up' in log and "means stop talking" in log


def test_an_unconfirmed_shutdown_is_refused_and_logged(monkeypatch, tmp_path):
    ran = []
    monkeypatch.setitem(sm.tools.TOOL_DISPATCH, "shutdown_pc", lambda a, c: ran.append(1) or "shutting down")
    machine, session = _machine([
        {"type": "transcript", "role": "user", "text": "shut down my pc"},
        {"type": "tool_call", "calls": [{"id": "1", "name": "shutdown_pc", "args": {}}]},
        {"type": "transcript", "role": "assistant", "text": "Shall I shut down the PC?"},
    ], monkeypatch, tmp_path)
    machine.trigger()
    assert ran == []
    assert "Shall I shut down the PC" in session.sent_tool_responses[0][2]
    assert "REFUSED BY SAFETY CHECK" in convo_log.path().read_text(encoding="utf-8")


def test_the_hotkey_during_a_conversation_means_stop_talking():
    machine = sm.TronStateMachine("k", "m", "v", "p", 30, audio=FakeAudio(), session_factory=lambda: FakeSession())
    machine._busy.acquire()           # a conversation is running
    try:
        machine.hotkey()
        assert machine._stop_now
    finally:
        machine._busy.release()


def test_echo_is_not_sent_while_tron_is_speaking(monkeypatch, tmp_path):
    """TRON's voice in the mic must reach Gemini as silence, or it answers itself forever."""
    class EchoyMic(FakeAudio):
        calls = 0

        def drain_mic(self):
            # TRON's voice coming back off the speakers: speech-level, but under the barge-in level.
            # Then quiet, so the conversation can time out and the test end.
            import numpy as np
            self.calls += 1
            return (np.full(1600, 300, dtype=np.int16)).tobytes() if self.calls < 20 else b""

    reply = b"\x10\x27" * 2400       # a loud stretch of TRON audio
    machine, session = _machine([{"type": "audio", "data": reply}], monkeypatch, tmp_path, audio=EchoyMic())
    machine.trigger()
    assert session.sent_audio, "the stream must stay continuous"
    assert any(chunk == bytes(len(chunk)) for chunk in session.sent_audio)


# --------------------------------------------------------------------------- music
def test_best_match_picks_the_song_not_the_remix():
    titles = ["Dancing With Your Ghost (Slowed + Reverb)", "Dancing With Your Ghost", "Dancin"]
    assert music.best_match("dancing with your ghost", titles) == 1
    assert music.best_match("dancing with your ghost by sasha alex sloan", titles) == 1


def test_best_match_refuses_a_wrong_song():
    assert music.best_match("bohemian rhapsody", ["Dancing With Your Ghost", "Dancin"]) is None


def test_music_is_never_a_web_search():
    import tools
    names = {d["name"] for d in tools.TOOL_DECLARATIONS}
    assert "play_music" in names and "play_music" in tools.TOOL_DISPATCH
    assert "Never use web_search for music" in brain.HOUSE_RULES


# --------------------------------------------------------------------------- conversation log
def test_log_reads_as_who_said_and_did_what():
    lines = convo_log.format_events([
        ("user", "open spotify"), ("user", " and play dancing with your ghost"),
        ("tool", 'play_music(query="Dancing With Your Ghost") -> playing it'),
        ("assistant", "Playing"), ("assistant", " it now, sir."),
    ])
    assert lines == ["YOU:  open spotify and play dancing with your ghost",
                     'DID:  play_music(query="Dancing With Your Ghost") -> playing it',
                     "TRON: Playing it now, sir."]


def test_a_loosely_similar_playlist_is_not_played():
    """At the old 0.45 floor, "Perfect by Ed Sheeran" played a playlist called "Energetic dance songs"."""
    assert music.best_match("Perfect by Ed Sheeran", ["Energetic dance songs", "Dancin"]) is None
    assert music.best_match("Perfect by Ed Sheeran", ["Energetic dance songs", "Perfect"]) == 1


def test_song_by_artist_plays_the_song_not_the_artist_card():
    titles = ["Ed Sheeran", "Perfect", "Perfect Symphony"]
    assert music.choose("Perfect by Ed Sheeran", titles) == 1
    assert music.choose("some Ed Sheeran", titles) == 0


def test_memories_are_only_forgotten_when_the_user_says_so():
    """'What happened to the songs that I told you' was heard as 'funds' and erased four memories."""
    guard = brain.Guard()
    guard.user_said("what happened to the funds that I told")
    assert guard.check("forget_fact", {"key": "hindi music"}).startswith("NOT DONE")
    guard.user_said("forget my hindi music preference")
    assert guard.check("forget_fact", {"key": "hindi music"}) is None
