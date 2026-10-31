# tests/conftest.py
import pytest

import memory


@pytest.fixture(autouse=True)
def never_launch_real_apps(monkeypatch):
    """Stop the suite opening real windows on the developer's desktop.

    test_smoke replays a scripted conversation containing a real open_target
    tool call, and it does not stub the dispatch table — so every run genuinely
    launched Notepad. Windows appearing unbidden while someone is working is
    its own kind of broken, and no test needs the app to actually start to
    prove the wiring.

    Blocked at the launch primitives rather than at the tool, so a test that
    exercises the tool still exercises the real routing logic."""
    import app_index

    monkeypatch.setattr(app_index, "launch", lambda path: None)
    monkeypatch.setattr(app_index, "launch_start_app", lambda app_id: None)
    monkeypatch.setattr(app_index, "try_direct_launch", lambda name: False)


@pytest.fixture(autouse=True)
def isolate_error_log(tmp_path, monkeypatch):
    """Failure tests must not write the developer's real tron_error.log."""
    import state_manager

    monkeypatch.setattr(state_manager, "error_log_path", lambda: tmp_path / "tron_error.log")


@pytest.fixture(autouse=True)
def isolate_memory(tmp_path, monkeypatch):
    """Point every memory file at a temp dir for the whole suite.

    Without this the tests write the developer's real memory: test_smoke runs a
    full tool-dispatch conversation with log_activity unpatched, and a suite run
    was measured appending four junk entries to memory/activity.jsonl. Harmless
    while memory was only an action log; once facts and the last-session line
    live here too, a test run would overwrite what TRON actually knows about
    its user.

    Autouse and unconditional. A test that wants to exercise real paths can
    still monkeypatch these itself — monkeypatch inside a test wins over a
    fixture.

    Every path must be read as a module global at call time, not captured at
    import, for this redirection to work. memory.py is written that way; keep
    any new file constant to the same rule."""
    store = tmp_path / "memory"
    store.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(memory, "_LOG_PATH", store / "activity.jsonl", raising=False)
    for name, filename in (("_FACTS_PATH", "facts.json"),
                           ("_SUMMARY_PATH", "last_session.json")):
        if hasattr(memory, name):
            monkeypatch.setattr(memory, name, store / filename)


@pytest.fixture(autouse=True)
def assume_online(monkeypatch):
    """Conversations in tests must not depend on this machine's real internet connection, nor fall into
    offline mode and start talking through the speakers. Tests of offline mode turn this off themselves."""
    import state_manager

    monkeypatch.setattr(state_manager.TronStateMachine, "_online", lambda self: True)


@pytest.fixture(autouse=True)
def isolate_app_dir(tmp_path, monkeypatch, request):
    """Logs, skills, the dictionary and dictation history all live under config.app_dir(): point it at a temp
    dir, or a test run writes fake conversations into the real conversation log (it did). test_config tests
    app_dir() itself."""
    import config
    if request.module.__name__.endswith("test_config"):
        return
    monkeypatch.setattr(config, "app_dir", lambda: tmp_path)


@pytest.fixture(autouse=True)
def no_background_learning(monkeypatch, request):
    """A finished Gemini conversation asks the local model what to remember; tests must not reach Ollama."""
    import state_manager
    if "learn" not in request.node.name:
        monkeypatch.setattr(state_manager.TronStateMachine, "_learn", lambda self, lines: None)
