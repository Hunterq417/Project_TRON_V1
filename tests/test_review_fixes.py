# tests/test_review_fixes.py
"""Regression checks for the bugs found in the 2026-10 code review."""
import asyncio
import json
from unittest.mock import MagicMock

import config
import desktop_control
import desktop_layer
import gemini_live_client as glc
import state_manager as sm
from tests.test_gemini_live_client import _audio_response, _turn_complete_response
from tests.test_state_manager import FakeAudio, FakeSession


def test_receive_keeps_listening_after_the_first_turn():
    """The SDK's receive() ends at each turn_complete; ours must span the session."""
    turns = [[_audio_response(b"one"), _turn_complete_response()],
             [_audio_response(b"two"), _turn_complete_response()],
             []]                                     # connection closed

    class Sdk:
        async def receive(self):
            for r in turns.pop(0):
                yield r

    session = glc.GeminiLiveSession.__new__(glc.GeminiLiveSession)
    session._session = Sdk()

    async def collect():
        return [e async for e in session.receive()]

    audio = [e["data"] for e in asyncio.run(collect()) if e["type"] == "audio"]
    assert audio == [b"one", b"two"]


def test_close_app_never_matches_a_pronoun():
    wins = [(1, "GitHub - Chrome", "chrome.exe"), (2, "Edit - Notepad", "notepad.exe")]
    for spoken in ("it", "this", "that one", "close it", "them"):
        assert desktop_control._matches(spoken, wins) == [], spoken
    assert [w[1] for w in desktop_control._matches("the chrome window", wins)] == ["GitHub - Chrome"]


def test_unreadable_config_is_never_overwritten(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text('{"gemini_api_key": "secret",', encoding="utf-8")   # mid-edit typo
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    try:
        config.update_config_file({"widget_pos": [1, 2]})
    except ValueError:
        pass
    assert "secret" in path.read_text(encoding="utf-8")

    path.write_text('{"gemini_api_key": "secret"}', encoding="utf-8")
    config.update_config_file({"widget_pos": [1, 2]})
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "gemini_api_key": "secret", "widget_pos": [1, 2]}


def test_a_failing_tool_answers_the_model_instead_of_killing_the_conversation(monkeypatch):
    def boom(args, cfg):
        raise RuntimeError("driver exploded")

    monkeypatch.setitem(sm.tools.TOOL_DISPATCH, "battery_status", boom)
    session = FakeSession(events=[
        {"type": "tool_call", "calls": [
            {"id": "1", "name": "battery_status", "args": {}},
            {"id": "2", "name": "made_up_tool", "args": {}},
        ]},
        {"type": "turn_complete"},
    ])
    states = []
    machine = sm.TronStateMachine("k", "m", "v", "p", silence_timeout_s=0.3,
                                  on_state_change=states.append, audio=FakeAudio(),
                                  session_factory=lambda: session)
    machine.trigger()

    results = {name: result for _id, name, result in session.sent_tool_responses}
    assert "driver exploded" in results["battery_status"]
    assert "no tool called" in results["made_up_tool"]
    assert states[-1] is sm.State.IDLE


def test_audio_device_failure_turns_the_orb_red_instead_of_raising():
    audio = FakeAudio()
    audio.start = MagicMock(side_effect=ValueError('no output device matching "Realtek"'))
    states = []
    machine = sm.TronStateMachine("k", "m", "v", "p", silence_timeout_s=1,
                                  on_state_change=states.append, audio=audio,
                                  session_factory=lambda: FakeSession())
    machine.trigger()                      # must not raise
    assert states[-1] is sm.State.ERROR


def test_widget_can_be_dragged_onto_a_second_monitor(monkeypatch):
    fake = MagicMock()

    def rect(hwnd, out):
        out._obj.left, out._obj.top, out._obj.right, out._obj.bottom = (0, 0, 150, 150)
        return 1

    fake.GetWindowRect.side_effect = rect
    # Primary 1920x1080; virtual desktop spans a second screen to the right.
    fake.GetSystemMetrics.side_effect = {0: 1920, 1: 1080, 76: 0, 77: 0,
                                         78: 3840, 79: 1080}.__getitem__
    fake.SetWindowPos.return_value = 1
    monkeypatch.setattr(desktop_layer, "user32", fake)

    desktop_layer.move_onscreen(1, 2600, 500)
    args, _ = fake.SetWindowPos.call_args
    assert (args[2], args[3]) == (2600, 500)
