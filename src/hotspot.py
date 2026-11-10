# hotspot.py
"""No internet? TRON rejoins the phone's hotspot by itself.

iOS lets nothing switch Personal Hotspot on remotely, not over Bluetooth and not from an app. But with
"Allow Others to Join" on, the iPhone keeps the hotspot available, and Windows can join it if it has joined
once before (that saved Wi-Fi profile is what `netsh wlan connect` uses). Set "hotspot_ssid" in config.json to
the hotspot's name, e.g. "Shivansh's iPhone".
"""
import subprocess
import threading
import time

import offline


def join(ssid: str) -> bool:
    """Asks Windows to connect to the saved Wi-Fi profile; True once the internet answers."""
    subprocess.run(["netsh", "wlan", "connect", f"name={ssid}"], capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for _ in range(15):
        time.sleep(1)
        if offline.online():
            return True
    return False


def start(ssid: str, announce=lambda text: None, every: float = 30) -> None:
    def loop():
        while True:
            time.sleep(every)
            try:
                if not offline.online() and join(ssid):
                    announce("The internet dropped, boss; I've connected us to your phone's hotspot.")
            except Exception:
                pass
    threading.Thread(target=loop, daemon=True).start()
