# tests/test_memory.py
import json

import memory


def test_log_activity_appends_json_line(tmp_path, monkeypatch):
    log_path = tmp_path / "activity.jsonl"
    monkeypatch.setattr(memory, "_LOG_PATH", log_path)

    memory.log_activity({"tool": "open_target", "args": {"name": "notepad"}, "result": 'opened "notepad"'})

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["tool"] == "open_target"
    assert "at" in record


def test_log_activity_creates_parent_directory(tmp_path, monkeypatch):
    log_path = tmp_path / "nested" / "activity.jsonl"
    monkeypatch.setattr(memory, "_LOG_PATH", log_path)

    memory.log_activity({"tool": "web_search", "args": {}, "result": "ok"})

    assert log_path.exists()


def test_recent_context_empty_when_no_log(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "_LOG_PATH", tmp_path / "does_not_exist.jsonl")
    assert memory.recent_context() == ""


def test_recent_context_formats_recent_entries(tmp_path, monkeypatch):
    log_path = tmp_path / "activity.jsonl"
    monkeypatch.setattr(memory, "_LOG_PATH", log_path)
    memory.log_activity({"tool": "open_target", "args": {"name": "notepad"}, "result": 'opened "notepad"'})
    memory.log_activity({"tool": "web_search", "args": {"query": "weather"}, "result": 'opened a search for "weather"'})

    context = memory.recent_context()

    assert "open_target" in context
    assert "web_search" in context
    assert "notepad" in context


def test_recent_context_limits_to_n_most_recent(tmp_path, monkeypatch):
    log_path = tmp_path / "activity.jsonl"
    monkeypatch.setattr(memory, "_LOG_PATH", log_path)
    for i in range(5):
        memory.log_activity({"tool": f"tool_{i}", "args": {}, "result": "ok"})

    context = memory.recent_context(n=2)

    assert "tool_3" in context
    assert "tool_4" in context
    assert "tool_0" not in context


def test_recent_context_skips_corrupted_lines(tmp_path, monkeypatch):
    log_path = tmp_path / "activity.jsonl"
    monkeypatch.setattr(memory, "_LOG_PATH", log_path)
    good = json.dumps({"tool": "web_search", "args": {}, "result": "ok", "at": "t"})
    log_path.write_text("not valid json\n" + good + "\n")

    context = memory.recent_context()

    assert "web_search" in context


def test_clear_removes_log_file(tmp_path, monkeypatch):
    log_path = tmp_path / "activity.jsonl"
    monkeypatch.setattr(memory, "_LOG_PATH", log_path)
    memory.log_activity({"tool": "x", "args": {}, "result": "ok"})
    assert log_path.exists()

    memory.clear()

    assert not log_path.exists()


def test_clear_is_a_no_op_when_no_log(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "_LOG_PATH", tmp_path / "does_not_exist.jsonl")
    memory.clear()  # must not raise


def test_join_transcript_merges_fragments_into_whole_turns():
    """The Live API streams transcription in pieces as the audio plays, so one
    event is not one utterance. Treating it as one shreds every sentence."""
    fragments = [("assistant", "It's"), ("assistant", " Friday"), ("assistant", ", sir.")]
    assert memory.join_transcript(fragments) == [
        {"role": "assistant", "text": "It's Friday, sir."}
    ]


def test_join_transcript_starts_a_new_turn_when_the_speaker_changes():
    fragments = [("user", "what is"), ("user", " the date"),
                 ("assistant", "It's Friday"), ("assistant", ", sir.")]
    assert memory.join_transcript(fragments) == [
        {"role": "user", "text": "what is the date"},
        {"role": "assistant", "text": "It's Friday, sir."},
    ]


def test_join_transcript_drops_empty_and_whitespace_turns():
    fragments = [("user", ""), ("assistant", "   "), ("user", "hello")]
    assert memory.join_transcript(fragments) == [{"role": "user", "text": "hello"}]


def test_join_transcript_of_nothing_is_empty():
    assert memory.join_transcript([]) == []


def test_the_activity_log_is_capped():
    """recent_context() reads the whole file at every conversation start, and
    the log is append-only, so without a cap that read gets slower forever."""
    big = {"tool": "x", "args": {}, "result": "y" * 500}
    for _ in range(700):
        memory.log_activity(big)

    assert memory._LOG_PATH.stat().st_size <= memory._MAX_LOG_BYTES


def test_trimming_keeps_the_newest_entry():
    """Trimming must happen after the append. Doing it first drops the line
    that was just written — the one most likely to be asked about."""
    for _ in range(700):
        memory.log_activity({"tool": "old", "args": {}, "result": "y" * 500})
    memory.log_activity({"tool": "newest", "args": {}, "result": "the last thing"})

    assert "newest" in memory._LOG_PATH.read_text(encoding="utf-8").splitlines()[-1]
    assert "the last thing" in memory.recent_context()


def test_an_unwritable_log_never_breaks_a_conversation(monkeypatch):
    def boom(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(memory._LOG_PATH.__class__, "stat", boom, raising=False)
    memory._trim_log()   # must not raise


def test_remembering_the_same_key_twice_corrects_rather_than_duplicates():
    """(kind, key) identifies a fact. "actually I prefer tea" must replace the
    old preference, not sit next to it contradicting it."""
    memory.remember("preference", "drink", "coffee")
    memory.remember("preference", "drink", "tea")

    drinks = [f for f in memory.all_facts() if f["key"] == "drink"]
    assert len(drinks) == 1
    assert drinks[0]["value"] == "tea"


def test_the_same_key_under_a_different_kind_is_a_different_fact():
    memory.remember("preference", "tron", "likes it dark")
    memory.remember("project", "tron", "voice assistant")
    assert len(memory.all_facts()) == 2


def test_forget_reports_when_there_was_nothing_to_forget():
    """So TRON can say so instead of claiming to have forgotten something it
    never knew."""
    assert memory.forget("nonexistent") is False
    memory.remember("fact", "sister birthday", "3 March")
    assert memory.forget("sister birthday") is True
    assert memory.all_facts() == []


def test_facts_render_into_the_prompt_grouped_by_kind():
    memory.remember("identity", "name", "Shivansh")
    memory.remember("preference", "browser", "Firefox")
    memory.remember("project", "tron", "voice assistant", status="active")

    block = memory.long_term_context()
    assert "Who the user is:" in block and "- name: Shivansh" in block
    assert "Their preferences:" in block and "- browser: Firefox" in block
    assert "[status: active]" in block


def test_an_empty_store_contributes_nothing_to_the_prompt():
    """Must be "" and never None: the prompt is built with a join, and a None
    block would raise inside the session factory and kill every conversation."""
    assert memory.long_term_context() == ""


def test_a_corrupt_store_is_set_aside_rather_than_crashing():
    """A broken file must never stop TRON starting, but it is also the only
    copy of what TRON knew, so it is moved aside rather than deleted."""
    memory._FACTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    memory._FACTS_PATH.write_text("{not json at all", encoding="utf-8")

    assert memory.all_facts() == []
    assert memory._FACTS_PATH.with_suffix(".corrupt").exists()

    memory.remember("fact", "still", "works")
    assert memory.all_facts()[0]["value"] == "works"


def test_the_store_is_capped_but_never_evicts_who_the_user_is():
    """A name is worth more than any number of passing remarks."""
    memory.remember("identity", "name", "Shivansh")
    for i in range(memory._MAX_FACTS + 20):
        memory.remember("fact", f"trivia {i}", f"value {i}")

    facts = memory.all_facts()
    assert len(facts) <= memory._MAX_FACTS
    assert any(f["kind"] == "identity" and f["value"] == "Shivansh" for f in facts)


def test_an_unknown_kind_is_filed_as_a_plain_fact():
    memory.remember("nonsense", "k", "v")
    assert memory.all_facts()[0]["kind"] == "fact"


def test_remembering_nothing_is_a_no_op():
    memory.remember("fact", "k", "")
    assert memory.all_facts() == []
