from types import SimpleNamespace

import computer
import desktop_control


class FakeElement:
    def __init__(self, name):
        self.CurrentName = name


def test_a_number_whose_control_changed_is_never_clicked(monkeypatch):
    """LinkedIn redrew: #20 had been "Clear Selection", was blank by the second click, and the click landed
    elsewhere. Now that's refused and a fresh list is required."""
    element = FakeElement("Clear Selection")
    computer._elements.clear(); computer._listed_names.clear()
    computer._elements[20], computer._listed_names[20] = element, "Clear Selection"
    element.CurrentName = ""                                   # the page re-rendered
    clicked = []
    monkeypatch.setattr(computer, "_real_click", lambda el, double=False: clicked.append(el))
    reply = computer.click_element({"number": 20})
    assert "screen changed" in reply and clicked == [] and 20 not in computer._elements


def test_nothing_is_typed_when_no_text_box_has_focus(monkeypatch):
    typed = []
    monkeypatch.setattr("keyboard.write", lambda text, delay=0: typed.append(text))
    monkeypatch.setattr("keyboard.send", lambda key: typed.append(key))
    monkeypatch.setattr(computer, "_typing_target_ok", lambda: False)
    assert "didn't type" in computer.type_text({"text": "founder's office #hiring", "enter": True})
    assert typed == []                                         # and no stray Enter
    monkeypatch.setattr(computer, "_typing_target_ok", lambda: True)
    assert computer.type_text({"text": "hi", "enter": True}).startswith('typed "hi"') and typed == ["hi", "enter"]


def test_focus_app_finds_a_browser_tab_when_no_window_matches(monkeypatch):
    monkeypatch.setattr(desktop_control, "_app_hits", lambda q: [])
    monkeypatch.setattr(computer, "switch_to_tab", lambda q: 'switched to the "Jobs | LinkedIn" tab' if "linkedin" in q.lower() else "")
    assert "LinkedIn" in desktop_control.focus_app({"name": "LinkedIn"})
    assert "not open" in desktop_control.focus_app({"name": "Notion"})
