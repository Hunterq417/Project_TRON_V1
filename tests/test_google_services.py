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
