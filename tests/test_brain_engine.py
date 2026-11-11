# tests/test_brain_engine.py
"""The local brain's decision engine (TRON_BRAIN_IMPLEMENTATION.md §27): planning, permissions, execution,
verification, replanning, memory and secrets, with a scripted model so each path is exercised exactly."""
import json
import time
from types import SimpleNamespace

import brain
import config
import decision
import local_brain
import memory
import memory_service
import tool_registry
import tools
from tests.test_local import FakeOllama


def calls(*pairs):
    return {"role": "assistant", "content": "",
            "tool_calls": [{"function": {"name": n, "arguments": a}} for n, a in pairs]}


def say(text):
    return {"role": "assistant", "content": text}


def engine(*replies, **cfg):
    ollama = FakeOllama(*replies)
    return local_brain.LocalBrain(post=ollama, cfg=SimpleNamespace(**cfg) if cfg else None), ollama


# --------------------------------------------------------------------------- registry and policy
def test_every_tool_has_registry_metadata():
    names = {d["name"] for d in tools.TOOL_DECLARATIONS} | tools.PERMISSION_GATED
    assert names == set(tool_registry.TOOLS)


def test_confirmation_policy_comes_from_the_registry():
    assert brain.DESTRUCTIVE == {"shutdown_pc", "restart_pc", "sleep_pc", "send_email",
                                 "gmail_send", "calendar_create"}
    made = decision.from_calls("email the client", [("draft_email", {}), ("send_email", {"to": "x"})], tool_registry)
    assert made.requires_confirmation and made.risk.level is decision.RiskLevel.HIGH
    assert made.risk.external_side_effect and made.response_mode == "confirmation_required"
    reads = decision.from_calls("how is my pc", [("hardware_status", {})], tool_registry)
    assert not reads.requires_confirmation and reads.reason_codes == ["read_only_actions"]


def test_no_tools_means_answer_or_one_question():
    assert decision.from_calls("hi", [], tool_registry, "Hello, sir.").mode is decision.DecisionMode.ANSWER_DIRECTLY
    assert decision.from_calls("send it", [], tool_registry, "To whom, sir?").mode is decision.DecisionMode.ASK_CLARIFICATION


# --------------------------------------------------------------------------- verification
def test_the_verifier_reads_the_tools_own_report():
    assert decision.verify("Bluetooth is off, sir", data=False).status == "verified"
    assert decision.verify("Spotify didn't open, sir", data=False).status == "replan"
    assert decision.verify('I found "X" on Spotify, sir, but couldn\'t get it to start', data=False).status == "replan"
    assert decision.verify("NOT DONE: this needs the user's spoken confirmation", data=False).status == "blocked"
    assert decision.verify("volume is at 85 percent, sir", data=True).status == "partial"
    assert decision.verify("", data=False).status == "replan"


# --------------------------------------------------------------------------- execution loop
def test_a_verified_action_is_said_without_a_second_model_call():
    b, ollama = engine(calls(("set_radio", {"kind": "bluetooth", "enabled": False})))
    assert b.reply("turn off bluetooth", brain.Guard(), lambda n, a: "Bluetooth is off, sir") == "Bluetooth is off, sir"
    assert len(ollama.sent) == 1


def test_a_failed_step_is_replanned_another_way_and_never_claimed():
    b, ollama = engine(calls(("play_music", {"query": "blinding lights"})),
                       calls(("media_play_pause", {})))
    results = {"play_music": "I found it on Spotify, sir, but couldn't get it to start",
               "media_play_pause": "playing The Weeknd - Blinding Lights on Spotify, sir"}
    assert b.reply("play blinding lights", brain.Guard(), lambda n, a: results[n]) == results["media_play_pause"]
    assert ollama.sent[1]["messages"][-1]["content"] == local_brain.REPLAN_NOTE


def test_replanning_is_bounded_and_failure_is_reported_honestly():
    b, ollama = engine(*[calls(("open_target", {"name": "x"}))] * 6, brain_max_replans=2)
    reply = b.reply("open x", brain.Guard(), lambda n, a: "couldn't find x, sir")
    assert len(ollama.sent) == 3 and "couldn't" in reply


def test_read_then_act_when_the_request_is_not_a_question():
    b, ollama = engine(calls(("volume_status", {})), calls(("change_volume", {"delta": -20})))
    ran = []
    reply = b.reply("it's way too loud", brain.Guard(),
                    lambda n, a: ran.append(n) or ("volume is at 90 percent, sir" if n == "volume_status" else "turned it down, sir"))
    assert ran == ["volume_status", "change_volume"] and reply == "turned it down, sir"


def test_a_status_question_is_answered_by_the_tool_directly():
    b, ollama = engine(calls(("battery_status", {})))
    assert b.reply("how much battery do i have", brain.Guard(), lambda n, a: "battery is at 80 percent, sir") \
        == "battery is at 80 percent, sir"
    assert len(ollama.sent) == 1


def test_sending_needs_a_yes_even_when_the_model_tries():
    b, ollama = engine(calls(("send_email", {"to": "client"})), say("Shall I send it to the client, sir?"))
    guard, ran = brain.Guard(), []
    guard.user_said("email the client the proposal")
    reply = b.reply("email the client the proposal", guard, lambda n, a: ran.append(n) or "sent")
    assert ran == [] and reply.endswith("?")


def test_tool_calls_are_bounded():
    b, ollama = engine(calls(*[("open_target", {"name": f"app{i}"}) for i in range(12)]), say("Done what I could."),
                       brain_max_tool_calls=3)
    ran = []
    b.reply("open everything", brain.Guard(), lambda n, a: ran.append(a["name"]) or f"opened {a['name']}")
    assert len(ran) == 3


def test_a_tool_that_raises_does_not_end_the_conversation():
    session = local_brain.LocalSession(SimpleNamespace(mic_device=None),
                                       local_brain=local_brain.LocalBrain(post=FakeOllama()))
    tools.TOOL_DISPATCH["__boom__"] = lambda a, c: 1 / 0
    try:
        assert session.run_tool("__boom__", {}).startswith("that failed, sir: ZeroDivisionError")
    finally:
        del tools.TOOL_DISPATCH["__boom__"]


def test_each_stage_is_logged_without_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "app_dir", lambda: tmp_path)
    b, _ = engine(calls(("type_text", {"text": "hello", "password": "hunter2"})))
    b.reply("type my password", brain.Guard(), lambda n, a: "typed it, sir")
    events = [json.loads(line) for line in (tmp_path / "logs" / "brain_events.jsonl").read_text().splitlines()]
    assert [e["stage"] for e in events] == ["request", "decision", "verification", "response"]
    assert "hunter2" not in json.dumps(events) and events[2]["args"]["password"] == "***"


def test_debug_mode_writes_the_decision_into_the_conversation_log():
    b, _ = engine(calls(("lock_pc", {})), brain_debug=True)
    log = []
    b.reply("lock my pc", brain.Guard(), lambda n, a: "locked, sir", log)
    assert any(kind == "note" and "execute_and_verify: power" in text for kind, text in log)


# --------------------------------------------------------------------------- memory
def _fact(kind, key, value, days_old=0, **extra):
    at = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - days_old * 86400))
    return {"kind": kind, "key": key, "value": value, "at": at, **extra}


def test_relevant_memory_beats_irrelevant_and_identity_always_comes(monkeypatch):
    facts = [_fact("identity", "name", "Shivansh"), _fact("preference", "music", "likes The Weeknd on Spotify"),
             _fact("project", "tron", "building TRON, a voice assistant"), _fact("fact", "car", "drives a Swift")]
    monkeypatch.setattr(memory, "all_facts", lambda kind="": facts)
    got = memory_service.retrieve("play some music on spotify", k=2)
    assert [f["key"] for f in got] == ["name", "music"]


def test_stale_low_value_memory_is_deprioritised():
    q = memory_service._words("what music do i like")
    fresh = _fact("preference", "music", "likes lofi music", days_old=1)
    stale = _fact("fact", "music", "liked music in school", days_old=400, confidence=0.5)
    assert memory_service.score(fresh, q, set()) > memory_service.score(stale, q, set())


def test_memory_weights_are_configuration():
    q = memory_service._words("music")
    f = _fact("fact", "music", "likes music")
    assert memory_service.score(f, q, set(), weights={"relevance": 0, "importance": 0, "freshness": 0,
                                                       "task": 0, "confidence": 0}) == 0


def test_only_confident_non_secret_new_memories_pass_the_gate():
    ok = {"type": "USER_PREFERENCE", "key": "music", "content": "prefers lofi while working", "confidence": 0.9}
    assert memory_service.gate(ok, [])
    assert not memory_service.gate({**ok, "confidence": 0.5}, [])
    assert not memory_service.gate({**ok, "content": "my wifi password is tiger123"}, [])
    assert not memory_service.gate({**ok, "content": "key sk-abcdefghijklmnop"}, [])
    assert not memory_service.gate({**ok, "type": "SUCCESSFUL_ACTION"}, [])
    assert not memory_service.gate(ok, [{"value": "Prefers lofi while working"}])


def test_learning_stores_what_passes_and_skips_small_talk(monkeypatch):
    stored = []
    monkeypatch.setattr(memory, "remember", lambda kind, key, value, **kw: stored.append((kind, key, value, kw)))
    monkeypatch.setattr(memory, "all_facts", lambda kind="": [])
    reply = json.dumps({"memories": [
        {"type": "USER_PREFERENCE", "key": "music", "content": "prefers lofi while working", "confidence": 0.9, "importance": 0.7},
        {"type": "USER_FACT", "key": "pin", "content": "bank pin is 4421", "confidence": 0.99, "importance": 1},
        {"type": "USER_FACT", "key": "guess", "content": "might like jazz", "confidence": 0.4, "importance": 0.2}]})
    lines = ["YOU:  I always want lofi playing while I'm working on code", "TRON: Noted, sir."]
    assert len(memory_service.extract(lines, lambda m, s: reply)) == 1
    assert stored[0][0] == "preference" and stored[0][3]["confidence"] == 0.9
    assert memory_service.extract(["YOU:  what time is it"], lambda m, s: 1 / 0) == []


def test_relevant_memory_reaches_the_model(monkeypatch):
    monkeypatch.setattr(memory, "all_facts", lambda kind="": [_fact("preference", "music", "likes The Weeknd")])
    b, ollama = engine(say("Playing it, sir."))
    b.reply("play my usual music", brain.Guard(), lambda n, a: "")
    assert "likes The Weeknd" in ollama.sent[0]["messages"][0]["content"]


def test_a_promise_without_a_tool_call_is_sent_back_to_be_done():
    b, ollama = engine(calls(("volume_status", {})), say("It's at 90 percent. I'll turn it down for you."),
                       calls(("change_volume", {"delta": -30})))
    ran = []
    reply = b.reply("it's way too loud", brain.Guard(),
                    lambda n, a: ran.append(n) or ("volume is at 90 percent, sir" if n == "volume_status" else "turned it down, sir"))
    assert ran == ["volume_status", "change_volume"] and reply == "turned it down, sir"
    assert ollama.sent[2]["messages"][-1]["content"] == local_brain.ACT_NOTE
