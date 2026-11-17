import asyncio
from unittest.mock import MagicMock

import brain
import google_services as g
import tools


def test_not_connected_is_said_plainly(monkeypatch):
    monkeypatch.setattr(g, "_creds", lambda interactive=False: None)
    assert "isn't connected" in g.gmail_search()
    assert "isn't connected" in tools.TOOL_DISPATCH["calendar_events"]({"days": 2}, None)


def test_send_refuses_a_made_up_address():
    assert "real email address" in g.gmail_send("the college", "Hi", "Body")


def test_send_and_invite_need_a_spoken_yes():
    assert {"gmail_send", "calendar_create"} <= brain.DESTRUCTIVE


def test_search_lists_sender_and_subject(monkeypatch):
    gmail = MagicMock()
    gmail.users().messages().list().execute.return_value = {"messages": [{"id": "m1"}]}
    gmail.users().messages().get().execute.return_value = {"payload": {"headers": [
        {"name": "From", "value": "Mayukh"}, {"name": "Subject", "value": "Demo"}]}}
    monkeypatch.setattr(g, "_service", lambda *a: gmail)
    assert "[m1] Mayukh - Demo" in g.gmail_search("from:mayukh")


def test_tron_and_the_mcp_server_offer_the_same_google_tools():
    import google_mcp
    names = {t.name for t in asyncio.run(google_mcp.server.list_tools())}
    assert names == {fn.__name__ for fn in g.FUNCTIONS}
    assert names <= {d["name"] for d in tools.TOOL_DECLARATIONS}


def test_panel_sign_in_status_and_disconnect(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "CLIENT_FILE", tmp_path / "google_client_secret.json")
    monkeypatch.setattr(g, "TOKEN_FILE", tmp_path / "google_token.json")
    monkeypatch.setattr(g, "_creds", lambda interactive=False: None)
    assert g.account() == {"connected": False, "email": "", "can_sign_in": False}   # no key anywhere
    (tmp_path / "google_client_secret.json").write_text("{}", encoding="utf-8")
    assert g.account()["can_sign_in"] is True
    profile = MagicMock()
    profile.users().getProfile().execute.return_value = {"emailAddress": "shivansh@example.com"}
    monkeypatch.setattr(g, "_service", lambda *a: profile)
    assert g.account() == {"connected": True, "email": "shivansh@example.com", "can_sign_in": True}
    (tmp_path / "google_token.json").write_text('{"refresh_token": "r"}', encoding="utf-8")
    revoked = []
    monkeypatch.setattr("urllib.request.urlopen", lambda url, data=None, timeout=0: revoked.append(url))
    assert g.disconnect_google() == "Signed out of Google"
    assert revoked == ["https://oauth2.googleapis.com/revoke"] and not (tmp_path / "google_token.json").exists()
    assert g.disconnect_google() == "Google wasn't connected"
