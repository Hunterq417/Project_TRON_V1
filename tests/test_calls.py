import calls
import tools

WA = "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"
PHONE = "Microsoft.YourPhone_8wekyb3d8bbwe!App"


def toast(*lines):
    return "<toast><visual><binding template='ToastGeneric'>" + "".join(f"<text>{t}</text>" for t in lines) + \
        "</binding></visual></toast>"


def test_whatsapp_call_says_who_and_where():
    e = calls.parse(WA, toast("Mayukh", "Incoming voice call"))
    assert calls.sentence(e) == "Boss, Mayukh is calling you on WhatsApp."


def test_whatsapp_video_call():
    assert calls.sentence(calls.parse(WA, toast("Mayukh", "Incoming video call"))) == \
        "Boss, Mayukh is video calling you on WhatsApp."


def test_iphone_call_through_phone_link():
    assert calls.sentence(calls.parse(PHONE, toast("Incoming call", "Mom"))) == "Boss, Mom is calling you."
    assert calls.sentence(calls.parse(PHONE, toast("WhatsApp", "Riya is calling…"))) == \
        "Boss, Riya is calling you on WhatsApp."


def test_messages_are_told_apart_and_other_apps_ignored():
    assert calls.parse(WA, toast("Mayukh", "see you at 8"))["kind"] == "message"
    assert calls.parse("Microsoft.ScreenSketch_8wekyb3d8bbwe!App", toast("Incoming call", "x")) == {}
    assert calls.parse(WA, toast("You may have new messages")) == {}


def test_not_for_me_exists_for_both_brains():
    assert any(d["name"] == "not_for_me" for d in tools.TOOL_DECLARATIONS)
