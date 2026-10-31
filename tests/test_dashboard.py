# tests/test_dashboard.py
import json
import urllib.error
import urllib.request

import pytest

import config
import dashboard


@pytest.fixture
def dash(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "gemini_api_key": "SECRET-KEY-VALUE",
        "smtp_app_password": "SECRET-SMTP-PW",
        "voice_name": "Orus",
        "wake_mode": "openwakeword",
        "mic_device": None,
        "camera_enabled": False,
    }), encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", cfg)
    monkeypatch.setattr(dashboard.config, "CONFIG_PATH", cfg)
    monkeypatch.setattr(dashboard, "_audio_devices", lambda: ([], []))
    d = dashboard.Dashboard()
    d.start()
    yield d
    d.stop()


def _get(d, path, token=None):
    req = urllib.request.Request(
        "http://127.0.0.1:%d%s" % (d._server.server_address[1], path),
        headers={"X-Tron-Token": token if token is not None else d._token},
    )
    return urllib.request.urlopen(req, timeout=5)


def _post(d, patch, token=None):
    req = urllib.request.Request(
        "http://127.0.0.1:%d/api/config" % d._server.server_address[1],
        data=json.dumps(patch).encode(),
        headers={"X-Tron-Token": token if token is not None else d._token,
                 "Content-Type": "application/json"},
        method="POST",
    )
    return json.load(urllib.request.urlopen(req, timeout=5))


def test_serves_the_page(dash):
    body = _get(dash, "/").read().decode()
    assert "TRON" in body and "CONTROL SURFACE" in body


def test_the_page_carries_the_token_not_the_placeholder(dash):
    body = _get(dash, "/").read().decode()
    assert "__TOKEN__" not in body
    assert dash._token in body


def test_a_wrong_token_is_refused(dash):
    # Without this, any website you visit could POST to localhost and rewrite
    # the config — browsers send cross-origin requests to 127.0.0.1 happily.
    with pytest.raises(urllib.error.HTTPError) as err:
        _get(dash, "/api/state", token="not-the-token")
    assert err.value.code == 403


def test_secrets_are_never_sent_to_the_page(dash):
    body = _get(dash, "/api/state").read().decode()
    assert "SECRET-KEY-VALUE" not in body
    assert "SECRET-SMTP-PW" not in body
    state = json.loads(body)
    assert state["config"]["gemini_api_key_set"] is True
    assert "gemini_api_key" not in state["config"]


def test_a_patch_merges_rather_than_replaces(dash):
    _post(dash, {"voice_name": "Charon"})
    data = json.loads(config.CONFIG_PATH.read_text())
    assert data["voice_name"] == "Charon"
    assert data["gemini_api_key"] == "SECRET-KEY-VALUE"   # untouched
    assert data["wake_mode"] == "openwakeword"


def test_a_blank_secret_leaves_the_stored_one_alone(dash):
    # The field is empty on every page load; submitting it must not wipe the key.
    _post(dash, {"gemini_api_key": "   "})
    data = json.loads(config.CONFIG_PATH.read_text())
    assert data["gemini_api_key"] == "SECRET-KEY-VALUE"


def test_a_real_secret_does_get_written(dash):
    _post(dash, {"gemini_api_key": "NEW-KEY"})
    assert json.loads(config.CONFIG_PATH.read_text())["gemini_api_key"] == "NEW-KEY"


def test_restart_required_is_reported_for_startup_only_settings(dash):
    state = _post(dash, {"voice_name": "Kore"})
    assert "voice_name" in state["restart_required"]


def test_switching_assistant_is_persisted(dash):
    state = _post(dash, {"active_assistant": "friday"})
    assert state["active_assistant"] == "friday"


def test_assistants_default_when_config_has_none(dash):
    state = json.loads(_get(dash, "/api/state").read())
    assert [a["id"] for a in state["assistants"]] == ["tron", "jarvis", "friday"]
