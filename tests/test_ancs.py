import struct

import ancs
import calls


def test_notification_source_packet():
    n = ancs.parse_notification_source(bytes([0, 0, 1, 1]) + struct.pack("<I", 42))
    assert n == {"event": "added", "category": "incoming_call", "uid": 42, "silent": False, "preexisting": False}


def test_get_attributes_command_layout():
    assert ancs.get_attributes_command(42, 64) == bytes([0]) + struct.pack("<I", 42) + bytes([0, 1, 64, 0, 3, 64, 0])


def attrs_response(uid, app, title, message, ):
    body = b"".join(bytes([i]) + struct.pack("<H", len(v)) + v.encode() for i, v in ((0, app), (1, title), (3, message)))
    return bytes([0]) + struct.pack("<I", uid) + body


def test_whatsapp_call_over_ancs_is_announced_like_phone_link():
    data = attrs_response(42, "net.whatsapp.WhatsApp", "Mayukh", "WhatsApp video call")
    assert ancs.parse_attributes(data[:9]) is None             # first Bluetooth packet only: wait for the rest
    uid, attrs = ancs.parse_attributes(data)
    event = ancs.describe("incoming_call", attrs)
    assert uid == 42 and calls.sentence(event) == "Boss, Mayukh is video calling you on WhatsApp."


def test_phone_call_and_ignored_categories():
    _, attrs = ancs.parse_attributes(attrs_response(7, "com.apple.mobilephone", "Mom", ""))
    assert calls.sentence(ancs.describe("incoming_call", attrs)) == "Boss, Mom is calling you."
    assert ancs.describe("news", attrs) == {}
