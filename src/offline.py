# offline.py
"""TRON without the internet.

Gemini is TRON's voice and brain, so with no connection a conversation can't even start. The wake word and
the hotkey are local, though, so "hey tron" still works — and what happens next is this:

1. TRON says it can't reach the internet and tries to fix that: Wi-Fi radio on, then each saved network
   that is in range, checking for a connection after each. If one works, the normal conversation starts.
2. If none does, TRON stays in offline mode: speech is recognised on this PC (NVIDIA Parakeet),
   understood by fixed rules below, and answered with Windows' built-in voice. The actions
   are TRON's ordinary tools, so "turn bluetooth on" offline does exactly what it does online.

Offline commands: Wi-Fi on/off, Bluetooth on/off, fix/troubleshoot the Wi-Fi, volume up/down/mute/set,
the time, battery, open/close an app, play/pause/next/previous, timers, lock, and (with a yes) shutdown or
restart.
"""
import collections
import re
import socket
import subprocess
import time

import numpy as np

import config

SAMPLE_RATE = 16000
_CREATE_NO_WINDOW = 0x08000000
_HOSTS = (("generativelanguage.googleapis.com", 443), ("8.8.8.8", 53), ("1.1.1.1", 53))


def online(timeout: float = 1.5) -> bool:
    """True when the internet (and Gemini) can be reached. Several hosts, so one blocked one isn't fatal."""
    for host, port in _HOSTS:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


# --------------------------------------------------------------------------- reconnecting
def _netsh(*args) -> str:
    return subprocess.run(["netsh", "wlan", *args], capture_output=True, text=True, timeout=20,
                          stdin=subprocess.DEVNULL, creationflags=_CREATE_NO_WINDOW).stdout


def saved_networks() -> list:
    """Wi-Fi networks this PC has connected to before."""
    return [m.strip() for m in re.findall(r"All User Profile\s*:\s*(.+)", _netsh("show", "profiles"))]


def visible_networks() -> list:
    return [m.strip() for m in re.findall(r"^SSID \d+\s*:\s*(.+)$", _netsh("show", "networks"), re.M) if m.strip()]


def fix_wifi(say=lambda text: None) -> tuple:
    """Tries to get back online. Returns (online, what happened as one sentence)."""
    import radio_control
    if online():
        return True, "We're online, sir."
    say("Checking the Wi-Fi radio.")
    state = radio_control.radio_status().lower()
    if "wi-fi is off" in state:
        radio_control.set_radio("wifi", True)
        time.sleep(4)
        if online():
            return True, "Wi-Fi was switched off. It's back on and we're online, sir."
    saved = saved_networks()
    in_range = [n for n in visible_networks() if n in saved]
    if not saved:
        return False, "This PC has no saved Wi-Fi networks, sir, so I can't reconnect on my own."
    if not in_range:
        return False, "None of your saved Wi-Fi networks are in range, sir."
    for network in in_range:
        say(f"Trying {network}.")
        _netsh("connect", f"name={network}")
        for _ in range(10):
            time.sleep(1)
            if online():
                return True, f"Connected to {network}, sir. We're back online."
    subprocess.run(["ipconfig", "/flushdns"], capture_output=True, stdin=subprocess.DEVNULL,
                   creationflags=_CREATE_NO_WINDOW)
    if online():
        return True, "Fixed it by clearing the DNS cache, sir. We're online."
    return False, (f"I connected to Wi-Fi but the internet still isn't reachable, sir. The router may be "
                   f"down. I tried {', '.join(in_range)}.")


# --------------------------------------------------------------------------- speaking
class Voice:
    """Windows' own text-to-speech (SAPI): installed on every Windows PC, needs no internet."""

    def __init__(self):
        import comtypes.client
        self._voice = comtypes.client.CreateObject("SAPI.SpVoice")
        for i in range(self._voice.GetVoices().Count):   # prefer a male voice, closer to TRON's
            token = self._voice.GetVoices().Item(i)
            if "david" in token.GetDescription().lower():
                self._voice.Voice = token
                break

    def say(self, text: str) -> None:
        self._voice.Speak(text)


# --------------------------------------------------------------------------- hearing
_model = None


def speech_model():
    """NVIDIA Parakeet TDT 0.6B v2, run on the CPU through ONNX (onnx-asr), loaded from models\\.

    Picked by testing on the user's own recorded voice against Whisper base.en (the previous model),
    small.en and large-v3-turbo. It got every "shut down the computer" right (base.en heard "shut down a
    little bit"), never invented words from silence (large-v3-turbo wrote "Thank you." twice), and took
    2.1s for all 12 clips where base.en took 18.8s and large-v3-turbo 132s."""
    global _model
    if _model is None:
        import onnx_asr
        _model = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v2",
                                     config.app_dir() / "models" / "parakeet-tdt-0.6b-v2", quantization="int8")
    return _model


def transcribe(audio: np.ndarray) -> str:
    return str(speech_model().recognize(audio.astype(np.float32), sample_rate=SAMPLE_RATE)).strip()


def listen(device=None, wait_for_speech: float = 7.0, max_secs: float = 10.0, stream_factory=None):
    """Records one utterance: waits for speech to start, stops after 0.8s of quiet. None if nobody spoke."""
    import audio_io
    blocks = collections.deque()

    def on_block(indata, *_):
        blocks.append(np.frombuffer(bytes(indata), dtype=np.int16).astype(np.float32) / 32768.0)

    if stream_factory is None:
        import sounddevice as sd
        stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=1600,
                                callback=on_block, device=audio_io.resolve_input(device))
    else:
        stream = stream_factory(on_block)
    speech, noise, quiet, started = [], 0.005, 0, time.time()
    with stream:
        while True:
            if not blocks:
                time.sleep(0.02)
                if not speech and time.time() - started > wait_for_speech:
                    return None
                continue
            block = blocks.popleft()
            rms = float(np.sqrt(np.mean(block ** 2)))
            loud = rms > max(noise * 3, 0.012)
            if not speech:
                if loud:
                    speech.append(block)
                else:
                    noise = 0.95 * noise + 0.05 * rms
                    if time.time() - started > wait_for_speech:
                        return None
                continue
            speech.append(block)
            quiet = 0 if loud else quiet + 1
            if quiet >= 8 or len(speech) >= max_secs * 10:
                return np.concatenate(speech)



# --------------------------------------------------------------------------- understanding
_ON = r"(?:on|enable|start|connect|activate)"
_OFF = r"(?:off|disable|stop|disconnect|deactivate)"
_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
            "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
            "a": 1, "an": 1}


def _number(word: str):
    return int(word) if word.isdigit() else _NUMBERS.get(word.lower())


def understand(said: str):
    """Maps a sentence to (tool, args), or a special ("_fix_wifi"|"_stop"|"_confirm:<tool>", {}), or None.
    Fixed rules, in order: the specific ones first so "turn the wifi off" is never "turn ... off" anything."""
    s = " " + re.sub(r"[^\w\s%-]", " ", said.lower()) + " "
    s = s.replace("wi fi", "wifi").replace("wi-fi", "wifi").replace("blue tooth", "bluetooth")
    if re.search(r"\b(shut up|stop talking|be quiet|never ?mind|goodbye|bye|that'?s all|nothing)\b", s):
        return "_stop", {}
    if re.search(r"\b(fix|troubleshoot|repair|reconnect|reset)\b.*\b(wifi|internet|network|connection)\b", s) \
            or re.search(r"\b(wifi|internet|network)\b.*\b(not working|broken|down|fix|troubleshoot)\b", s):
        return "_fix_wifi", {}
    for kind in ("wifi", "bluetooth"):
        if f" {kind} " in s:
            if re.search(rf"\b{_OFF}\b", s):
                return "set_radio", {"kind": kind, "enabled": False}
            if re.search(rf"\b{_ON}\b", s):
                return "set_radio", {"kind": kind, "enabled": True}
            return "radio_status", {}
    if re.search(r"\bunmute\b", s):
        return "set_mute", {"muted": False}
    if re.search(r"\bmute\b", s):
        return "set_mute", {"muted": True}
    m = re.search(r"\bvolume\b.*?\b(?:to|at)\s+(\d+)", s)
    if m:
        return "set_volume", {"level": int(m.group(1))}
    if re.search(r"\b(volume up|louder|turn it up|increase (?:the )?volume|raise (?:the )?volume)\b", s):
        return "change_volume", {"delta": 20}
    if re.search(r"\b(volume down|quieter|softer|turn it down|decrease (?:the )?volume|lower (?:the )?volume)\b", s):
        return "change_volume", {"delta": -20}
    if re.search(r"\b(what(?:'s| is) the time|what time|time is it|the date|what day)\b", s):
        return "current_time", {}
    if re.search(r"\bbattery\b", s):
        return "battery_status", {}
    m = re.search(r"\b(?:timer|remind me)\b.*?\b(\d+|" + "|".join(_NUMBERS) + r")\s*(second|minute|hour)s?\b", s)
    if m and _number(m.group(1)):
        seconds = _number(m.group(1)) * {"second": 1, "minute": 60, "hour": 3600}[m.group(2)]
        label = re.search(r"\bto\s+(.+?)\s*$", said, re.I)
        return "set_timer", {"seconds": seconds, "label": label.group(1) if label and "remind" in s else ""}
    if re.search(r"\b(next|skip)\b.*\b(song|track)\b|\bnext song\b", s):
        return "media_next", {}
    if re.search(r"\bprevious\b.*\b(song|track)\b|\bgo back\b", s):
        return "media_previous", {}
    if re.search(r"\b(pause|resume)\b", s) or re.search(r"^\s*play(?:\s+(?:the|some))?(?:\s+(?:music|song|spotify))?\s*$", s):
        return "media_play_pause", {}   # a named song ("play dancing with...") needs Spotify search: online only
    if re.search(r"\block\b.*\b(pc|computer|screen|laptop)\b", s):
        return "lock_pc", {}
    if re.search(r"\b(shut ?down|turn off)\b.*\b(pc|computer|laptop|system)\b", s):
        return "_confirm:shutdown_pc", {}
    if re.search(r"\brestart\b.*\b(pc|computer|laptop|system)\b", s):
        return "_confirm:restart_pc", {}
    m = re.search(r"\b(?:open|launch|start)\s+(?:the\s+)?(.+?)\s*$", said.strip(" .!?"), re.I)
    if m:
        return "open_target", {"name": m.group(1)}
    m = re.search(r"\b(?:close|quit|exit)\s+(?:the\s+)?(.+?)\s*$", said.strip(" .!?"), re.I)
    if m:
        return "close_app", {"name": m.group(1)}
    return None


HELP = ("I'm offline, sir, so I can only do the basics: Wi-Fi and Bluetooth, fixing the Wi-Fi, volume, "
        "the time, opening and closing apps, music controls, timers and locking the PC.")


# --------------------------------------------------------------------------- one offline session
class Session:
    """What happens when TRON is woken with no internet. run() returns True if it got back online."""

    def __init__(self, cfg=None, set_state=lambda name: None, log=None, voice=None, hear=None):
        self._cfg = cfg
        self._set_state = set_state
        self._log = log if log is not None else []
        self._voice = voice
        self._hear = hear     # for tests: a function returning the next sentence, or None

    def say(self, text: str) -> None:
        self._log.append(("assistant", text))
        self._set_state("SPEAKING")
        try:
            (self._voice or Voice()).say(text)
        except Exception:
            pass

    def hear(self):
        self._set_state("LISTENING")
        if self._hear is not None:
            said = self._hear()
        else:
            audio = listen(getattr(self._cfg, "mic_device", None))
            self._set_state("THINKING")
            said = transcribe(audio) if audio is not None else None
        if said:
            self._log.append(("user", said))
        return said

    def run(self, max_turns: int = 6) -> bool:
        import tools
        self._log.append(("note", "offline: the internet couldn't be reached"))
        self.say("I can't reach the internet, sir. Trying to reconnect.")
        self._set_state("ACTING")
        ok, result = fix_wifi(self.say)
        self._log.append(("tool", f"fix_wifi() -> {result}"))
        self.say(result)
        if ok:
            return True
        if self._hear is None and getattr(self._cfg, "brain", "gemini") != "local":
            import local_brain
            if local_brain.available(getattr(self._cfg, "local_model", None) or local_brain.DEFAULT_MODEL):
                # The local brain understands far more than the fixed rules below: hand over to it.
                self.say("I'll carry on with my offline brain, sir.")
                local_brain.LocalSession(self._cfg, self._set_state, self._log).run()
                return False
        self.say("Until then I'm in offline mode. What do you need?")
        pending = None
        for _ in range(max_turns):
            said = self.hear()
            if not said:
                break
            if pending:   # waiting on a yes for shutdown / restart
                tool, pending = pending, None
                if re.search(r"\b(yes|yeah|yep|sure|do it|go ahead|confirm)\b", said.lower()):
                    self._act(tools, tool, {})
                else:
                    self.say("Okay, I won't.")
                continue
            what = understand(said)
            if what is None:
                self.say(HELP)
                continue
            tool, args = what
            if tool == "_stop":
                break
            if tool == "_fix_wifi":
                self._set_state("ACTING")
                ok, result = fix_wifi(self.say)
                self._log.append(("tool", f"fix_wifi() -> {result}"))
                self.say(result)
                if ok:
                    return True
                continue
            if tool.startswith("_confirm:"):
                pending = tool.split(":", 1)[1]
                self.say("Shall I " + ("shut down" if "shutdown" in pending else "restart") + " the PC?")
                continue
            self._act(tools, tool, args)
            if tool == "set_radio" and args.get("kind") == "wifi" and args.get("enabled") and online():
                return True
        return False

    def _act(self, tools, tool, args) -> None:
        self._set_state("ACTING")
        try:
            result = tools.TOOL_DISPATCH[tool](args, self._cfg)
        except Exception as exc:
            result = f"that didn't work, sir: {exc}"
        self._log.append(("tool", f"{tool}({args}) -> {result}"))
        self.say(result)
