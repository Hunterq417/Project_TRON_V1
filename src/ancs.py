# ancs.py
"""PROTOTYPE: TRON reads the iPhone's notifications itself over Bluetooth LE, through Apple's Notification
Center Service (ANCS), the same channel Phone Link and smartwatches use. Nothing to install on the phone.

Apple's spec: the iPhone is the GATT server; an accessory that is paired (bonded) with it subscribes to three
characteristics. "Notification Source" says a notification arrived (category: incoming call, social, ...),
"Control Point" asks for its details (app, title, message) and "Data Source" sends them back.

    .venv\\Scripts\\python src\\ancs.py --scan          list nearby Bluetooth LE devices
    .venv\\Scripts\\python src\\ancs.py <address>       connect to the iPhone and print what arrives

The iPhone must be paired with this PC (Windows Settings > Bluetooth; Phone Link pairs it too). When TRON first
subscribes, the iPhone asks "Allow ... to receive your notifications?": tap Allow. With "ancs_address" in
config.json, TRON starts this at launch and announces calls ("Boss, Mayukh is calling you on WhatsApp").
"""
import asyncio
import struct
import threading

ANCS = "7905f431-b5ce-4e99-a40f-4b1e122d00d0"
NOTIFICATION_SOURCE = "9fbf120d-6301-42d9-8c58-25e699a21dbd"
CONTROL_POINT = "69d1d8f3-45e1-49a8-9821-9bbdfdaad9d9"
DATA_SOURCE = "22eac6e9-24d6-4bb5-be44-b36ace7c7bfb"

EVENTS = {0: "added", 1: "modified", 2: "removed"}
CATEGORIES = {0: "other", 1: "incoming_call", 2: "missed_call", 3: "voicemail", 4: "social", 5: "schedule",
              6: "email", 7: "news", 8: "health", 9: "business", 10: "location", 11: "entertainment"}
APP_ID, TITLE, SUBTITLE, MESSAGE = 0, 1, 2, 3
APPS = {"com.apple.mobilephone": "your phone", "com.apple.facetime": "FaceTime", "net.whatsapp.WhatsApp": "WhatsApp",
        "net.whatsapp.WhatsAppSMB": "WhatsApp Business", "ph.telegra.Telegraph": "Telegram",
        "com.burbn.instagram": "Instagram", "com.microsoft.skype.teams": "Teams", "com.hammerandchisel.discord":
        "Discord", "org.whispersystems.signal": "Signal", "com.facebook.Messenger": "Messenger",
        "com.apple.MobileSMS": "Messages", "com.google.Gmail": "Gmail"}


def parse_notification_source(data: bytes) -> dict:
    """The 8-byte Notification Source packet: EventID, EventFlags, CategoryID, CategoryCount, NotificationUID."""
    event, flags, category, count, uid = struct.unpack("<BBBBI", bytes(data[:8]))
    return {"event": EVENTS.get(event, event), "category": CATEGORIES.get(category, category), "uid": uid,
            "silent": bool(flags & 1), "preexisting": bool(flags & 4)}


def get_attributes_command(uid: int, max_len: int = 64) -> bytes:
    """Control Point command 0 (Get Notification Attributes): app id, title and message for one notification."""
    return struct.pack("<BI", 0, uid) + bytes([APP_ID]) + struct.pack("<BH", TITLE, max_len) + \
        struct.pack("<BH", MESSAGE, max_len)


def parse_attributes(data: bytes):
    """A complete Data Source response -> (uid, {attribute id: text}), or None while it's still incomplete
    (responses longer than one Bluetooth packet arrive in pieces; keep appending and try again)."""
    data = bytes(data)
    if len(data) < 5 or data[0] != 0:
        return None
    uid, pos, attrs = struct.unpack("<I", data[1:5])[0], 5, {}
    for _ in range(3):   # we always ask for exactly three attributes
        if pos + 3 > len(data):
            return None
        attr, length = data[pos], struct.unpack("<H", data[pos + 1:pos + 3])[0]
        if pos + 3 + length > len(data):
            return None
        attrs[attr] = data[pos + 3:pos + 3 + length].decode("utf-8", "ignore")
        pos += 3 + length
    return uid, attrs


def describe(category: str, attrs: dict) -> dict:
    """The same event shape calls.py announces: {"kind", "who", "app", "video"}, or {} to stay quiet."""
    app = APPS.get(attrs.get(APP_ID, ""), attrs.get(APP_ID, "").split(".")[-1] or "your phone")
    who = attrs.get(TITLE, "").strip() or "Someone"
    text = attrs.get(MESSAGE, "").lower()
    if category == "incoming_call":
        return {"kind": "call", "who": who, "app": app, "video": "video" in text or app == "FaceTime"}
    if category == "social":
        return {"kind": "message", "who": who, "app": app, "video": False}
    return {}


async def run(address: str, on_event, stop: asyncio.Event = None) -> None:
    """Connects to the paired iPhone and calls on_event(event_dict) for each call or message. Reconnects."""
    from bleak import BleakClient
    stop = stop or asyncio.Event()
    while not stop.is_set():
        try:
            async with BleakClient(address, timeout=20) as client:
                try:
                    await client.pair()   # ANCS is only visible over an encrypted, bonded link
                except Exception:
                    pass                  # already paired
                pending, buffer = {}, bytearray()

                def on_source(_, data):
                    n = parse_notification_source(data)
                    if n["event"] == "added" and not n["preexisting"] and n["category"] in ("incoming_call", "social"):
                        pending[n["uid"]] = n["category"]
                        asyncio.ensure_future(client.write_gatt_char(CONTROL_POINT, get_attributes_command(n["uid"]),
                                                                     response=True))

                def on_data(_, data):
                    buffer.extend(data)
                    done = parse_attributes(buffer)
                    if done:
                        buffer.clear()
                        uid, attrs = done
                        event = describe(pending.pop(uid, "other"), attrs)
                        if event:
                            on_event(event)

                await client.start_notify(DATA_SOURCE, on_data)          # data first, as Apple's spec asks
                await client.start_notify(NOTIFICATION_SOURCE, on_source)
                while client.is_connected and not stop.is_set():
                    await asyncio.sleep(1)
        except Exception as exc:
            print(f"ANCS: {type(exc).__name__}: {exc}; retrying in 15 s")
        if not stop.is_set():
            await asyncio.sleep(15)   # iPhone out of range or Bluetooth off: try again quietly


def start(address: str, announce) -> None:
    """For TRON: runs on its own thread and announces each call (messages only if announce wants them)."""
    import calls
    threading.Thread(target=lambda: asyncio.run(run(address, lambda e: announce(calls.sentence(e), e))),
                     daemon=True).start()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--scan":
        from bleak import BleakScanner
        for d in asyncio.run(BleakScanner.discover(timeout=8)):
            print(d.address, d.name)
    elif len(sys.argv) > 1:
        import calls
        asyncio.run(run(sys.argv[1], lambda e: print(calls.sentence(e), e)))
    else:
        print(__doc__)
