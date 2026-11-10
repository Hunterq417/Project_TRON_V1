import json
import urllib.request
from types import SimpleNamespace

import config
import panel_api


def call(server, name, *args, token=None):
    req = urllib.request.Request(server.url.split("?")[0] + "api/" + name, data=json.dumps(args).encode(),
                                 headers={"X-Tron-Token": token or server.token}, method="POST")
    try:
        return json.loads(urllib.request.urlopen(req, timeout=10).read())
    except urllib.error.HTTPError as exc:
        return exc.code


def test_the_page_and_api_need_the_launch_token(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    server = panel_api.Server(panel_api.Api())
    page = urllib.request.urlopen(server.url, timeout=10).read().decode()
    assert "window.TRON_TOKEN" in page and "Find anything" in page
    assert call(server, "status", token="wrong") == 403          # a web page can't drive TRON through localhost
    assert call(server, "_act_restart") == 403                   # private methods aren't reachable
    try:
        urllib.request.urlopen(server.url.split("?")[0], timeout=10)
        assert False, "the page must not be served without the token"
    except urllib.error.HTTPError as exc:
        assert exc.code == 404


def test_settings_save_only_what_changed_and_never_send_keys(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"gemini_api_key": "secret", "voice_name": "Puck", "brain": "gemini"}), encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    monkeypatch.setattr(panel_api.Api, "_ollama_models", staticmethod(lambda: []))
    server = panel_api.Server(panel_api.Api())
    shown = call(server, "settings")
    assert "secret" not in json.dumps(shown) and shown["values"]["gemini_api_key_set"] is True
    result = call(server, "save_settings", {"voice_name": "Puck", "camera_enabled": True, "gemini_api_key": ""})
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert result["ok"] and saved["camera_enabled"] is True
    assert saved["gemini_api_key"] == "secret"                   # an empty key box keeps the saved key
    assert "active_assistant" not in saved


def test_every_page_loads_on_an_empty_install(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(panel_api.Api, "_ollama_models", staticmethod(lambda: []))
    server = panel_api.Server(panel_api.Api())
    for name in ("status", "overview", "conversations", "memory", "people", "words", "settings"):
        assert not isinstance(call(server, name), int), name
    assert call(server, "conversation", "0") == []
    assert call(server, "status")["state"] == "OFF"


def test_restart_switch_and_talk_reach_tron(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    asked = []
    machine = SimpleNamespace(state=SimpleNamespace(name="IDLE"), dictation=None, hotkey=lambda: asked.append("talk"))
    api = panel_api.Api(machine, on_restart=lambda: asked.append("restart"))
    assert api.action("talk")["ok"] and api.action("restart")["ok"]
    import time
    time.sleep(0.8)
    assert sorted(asked) == ["restart", "talk"]
    assert api.switch_assistant("friday")["ok"] and api.status()["who"] == "friday"
    assert api.action("no_such_thing")["ok"] is False
