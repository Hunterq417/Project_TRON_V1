import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import local_brain
import state_manager as sm


def local_session(monkeypatch, heard):
    said, spoken = iter(heard), []
    session = local_brain.LocalSession(SimpleNamespace(mic_device=None), hear=lambda: next(said, None),
                                       speak=spoken.append, local_brain=MagicMock())

    def reply(text, guard, run_tool, log):
        if text.startswith("(to a friend)"):
            run_tool("not_for_me", {})
            return "Sure."            # what the model may say anyway: must stay unspoken
        return f"Answer to {text}"
    session.brain.reply = reply
    monkeypatch.setattr("winsound.PlaySound", lambda *a: None)
    return session, spoken


def test_talk_to_someone_else_then_ask_tron_without_the_wake_word(monkeypatch):
    session, spoken = local_session(monkeypatch, ["(to a friend) pass the salt", "what time is it"])
    session.run()
    assert spoken == ["Answer to what time is it"]


def test_three_in_a_row_means_they_are_talking_to_someone_else(monkeypatch):
    session, spoken = local_session(monkeypatch, ["(to a friend) a", "(to a friend) b", "(to a friend) c",
                                                  "what time is it"])
    session.run()
    assert spoken == []                       # back to the wake word before the fourth line


def test_gemini_goes_quiet_for_the_turn_and_ends_only_after_a_streak():
    machine = sm.TronStateMachine(api_key="k", model_name="m", voice_name="v", persona_text="p",
                                  silence_timeout_s=1, audio=MagicMock(), session_factory=MagicMock())
    call = {"name": "not_for_me", "args": {}}
    for expected_stop in (False, False, True):
        reply = asyncio.run(machine._run_tool(call, None))
        assert machine._quiet_turn and "keep listening" in reply
        assert machine._stop_now is expected_stop
