# panel_api.py
"""The control panel's backend. The page (assets/panel/index.html) runs in its own window process
(panel_window.py: a native WebView2 window, which needs a main thread of its own, and TRON's main thread runs
the orb). It talks to TRON through this small HTTP server:

* bound to 127.0.0.1, so nothing off this PC can reach it;
* every call carries a token minted at launch and handed only to the window TRON opens, so a web page in a
  browser can't drive TRON through localhost;
* keys are never sent to the page, only whether each one is set.

Every page method uses the same modules the old CustomTkinter panel used (memory, convo_log, dictation,
faces, voices, skills, scheduler, routine, timers, config), so nothing it could do is lost.
"""
import base64
import datetime
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config

PAGE = "panel/index.html"
VOICES = ["Orus", "Puck", "Charon", "Kore", "Fenrir", "Aoede", "Leda", "Zephyr"]
LOCAL_VOICES = [("david", "Microsoft David"), ("zira", "Microsoft Zira"), ("hazel", "Microsoft Hazel (British)"),
                ("am_michael", "Michael (Kokoro)"), ("am_adam", "Adam (Kokoro)"), ("bm_george", "George (Kokoro, British)"),
                ("af_heart", "Heart (Kokoro)"), ("bf_emma", "Emma (Kokoro, British)")]
UI_MODELS = [("dust-orb", "Dust Orb"), ("aurora-orb", "Aurora Orb"), ("halo-ring", "Halo Ring")]
KEYS = ("gemini_api_key", "openrouter_api_key", "smtp_app_password")
PLAIN = ("smtp_host", "smtp_user", "hotspot_ssid", "hotkey")
SWITCHES = ("local_brain_enabled", "memory_enabled", "brain_debug", "camera_enabled", "screen_enabled",
            "announce_calls", "announce_messages")
_FAIL = re.compile(r"\b(fail|couldn't|could not|can't|cannot|isn't|not found|no tool|error|refused)", re.I)


def _cfg() -> dict:
    try:
        return json.loads(config.CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _ok(message: str, **more) -> dict:
    return {"ok": True, "message": message, **more}


class Api:
    """What the page can ask for. machine is None in `TRON.exe --panel` (settings only, TRON not running)."""

    def __init__(self, machine=None, on_restart=None, restart_label="Restart"):
        self.machine, self.on_restart, self.restart_label = machine, on_restart, restart_label
        self._detail, self._detail_until = "", 0.0

    # ------------------------------------------------------------ live status, polled by the page
    def status(self):
        import timers
        data = _cfg()
        state = self.machine.state.name if self.machine else "OFF"
        if self.machine and getattr(self.machine, "dictation", None) is not None:
            state = "DICTATING"
        return {"who": config.active_assistant(data).get("id", "tron"), "state": state,
                "hotkey": data.get("hotkey", "ctrl+alt+t").replace("+", " ").title(),
                "wake": data.get("wake_mode") == "openwakeword", "restart_label": self.restart_label,
                "detail": self._detail if time.time() < self._detail_until else "",
                "timers": [[name, left] for name, left in timers.snapshot()]}

    def browser_status(self, stage, detail=""):
        words = {"inspecting": "Inspecting the page", "planning": "Planning", "executing": "Doing it",
                 "verifying": "Checking it worked", "recovering": "Trying another way", "completed": "Done",
                 "needs_clarification": "Needs your answer", "failed": "Couldn't do it"}
        self._detail = words.get(stage, stage) + (f": {detail[:80]}" if detail else "")
        self._detail_until = time.time() + 8

    # ------------------------------------------------------------ Today
    def overview(self):
        import memory
        data = _cfg()
        facts = memory.all_facts()
        name = next((f["value"] for f in facts if f.get("key") == "name"), "")
        activity = self._activity()
        try:
            import latency
            rows = [json.loads(l) for l in latency.PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
            replies = sorted(r["us"] for r in rows if r["kind"] == "response")
            typical = f"{replies[len(replies) // 2] / 1e6:.1f} s" if replies else "not measured yet"
        except (OSError, ValueError, ImportError):
            typical = "not measured yet"
        today = datetime.date.today()
        feed = []
        for row in reversed(activity):
            at = self._local(row.get("at"))
            if at is None or at.date() != today:
                continue
            result = str(row.get("result", "")).strip().rstrip(".").replace(", sir", "")
            text = result[:1].upper() + result[1:140] if result else row.get("tool", "").replace("_", " ")
            feed.append([at.strftime("%H:%M"), text, bool(_FAIL.search(result))])
            if len(feed) == 14:
                break
        return {"who": config.active_assistant(data).get("id", "tron"), "user": name or "there",
                "assistants": [{"id": a["id"], "name": a["name"]} for a in data.get("assistants") or config.DEFAULT_ASSISTANTS],
                "numbers": [[len(activity), "things done recently"], [len(facts), "things remembered"],
                            [len(self._sessions()), "conversations"], [typical, "typical reply time"]],
                "feed": feed}

    @staticmethod
    def _local(stamp):
        try:
            return datetime.datetime.fromisoformat(stamp).astimezone()
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _activity() -> list:
        import memory
        try:
            return [json.loads(l) for l in memory._LOG_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
        except (OSError, ValueError):
            return []

    # ------------------------------------------------------------ Conversations
    @staticmethod
    def _sessions() -> list:
        import convo_log
        try:
            text = convo_log.path().read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        parts = re.split(r"^===== (.+?) =====$", text, flags=re.M)[1:]
        return list(zip(parts[0::2], parts[1::2]))[::-1]   # newest first: [(timestamp, body)]

    def conversations(self):
        items = []
        for raw, body in self._sessions()[:80]:
            stamp = raw
            said = next((l[5:].strip() for l in body.splitlines() if l.startswith("YOU:")), "")
            try:
                when = datetime.datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
                day = {0: "Today", 1: "Yesterday"}.get((datetime.date.today() - when.date()).days, when.strftime("%d %b"))
                stamp = f"{day} {when:%H:%M}"
            except ValueError:
                pass
            items.append({"id": raw, "when": stamp, "preview": said[:70] or "(nothing said)"})
        return items

    def conversation(self, conv_id):
        body = next((b for stamp, b in self._sessions() if stamp == conv_id), None)
        if body is None:
            return []
        kinds = {"YOU:": "you", "TRON": "tron", "DID:": "did"}
        return [[kinds[l[:4]], l[5:].strip()] for l in body.splitlines() if l[:4] in kinds]

    def delete_conversation(self, conv_id):
        import convo_log
        return _ok("Conversation deleted") if convo_log.delete_conversation(conv_id) else \
            {"ok": False, "message": "That conversation was already gone"}

    def delete_line(self, conv_id, index):
        import convo_log
        return _ok("Line deleted") if convo_log.delete_line(conv_id, index) else \
            {"ok": False, "message": "That line was already gone"}

    # ------------------------------------------------------------ Memory
    def memory(self):
        import memory
        import routine
        import scheduler
        import skills
        sched = [[s["id"], f'{s["time"]} {scheduler._say_days(s["days"])}', s["task"]] for s in scheduler._load()]
        return {"facts": [[f.get("key", ""), f.get("value", "")] for f in memory.all_facts()],
                "routines": [[d, n] for d, n in routine.patterns()[:10]],
                "schedules": sched,
                "skills": [[s["id"], s["description"] or s["name"]] for s in skills.all_skills()]}

    def forget_fact(self, key):
        import memory
        return _ok("Forgotten" if memory.forget(key) else "That was already gone")

    def cancel_schedule(self, sched_id):
        import scheduler
        return _ok(scheduler.cancel_schedule({"which": sched_id}))

    def remove_skill(self, skill_id):
        import skills
        return _ok("Skill removed" if skills.remove(skill_id) else "That skill was already gone")

    # ------------------------------------------------------------ People
    def people(self):
        import faces
        import voices
        f, v = set(faces.gallery()), set(voices.gallery())
        return [[n, "face and voice" if n in f and n in v else "face" if n in f else "voice"]
                for n in sorted(f | v, key=str.lower)]

    def forget_person(self, name):
        import faces
        import voices
        faces.forget_face({"name": name})
        voices.forget_voice({"name": name})
        return _ok(f"Forgot {name}")

    # ------------------------------------------------------------ Words
    def words(self):
        import dictation
        vocab = dictation.read_vocab()
        rows = [[heard, word] for word, heards in vocab.items() for heard in (heards or [word])]
        return {"dictionary": rows, "dictations": [[d["time"].replace("T", " "), d["text"]] for d in dictation.history()[:60]]}

    def remove_word(self, heard):
        import dictation
        vocab = dictation.read_vocab()
        for word in list(vocab):
            vocab[word] = [h for h in vocab[word] if h != heard]
            if not vocab[word] or word == heard:
                del vocab[word]
        dictation.save_vocab(vocab)
        return _ok("Removed")

    # ------------------------------------------------------------ Settings
    def settings(self):
        data = _cfg()
        mics, speakers = [], []
        try:
            import audio_io
            mics = list(dict.fromkeys(n for _i, n, _c in audio_io.input_devices()))
            speakers = list(dict.fromkeys(n for _i, n, _c in audio_io.output_devices()))
        except Exception:
            pass
        options = {
            "brain": [["gemini", "Gemini (online, best)"], ["local", "On this PC only"]],
            "local_model": [[m, m] for m in self._ollama_models()] or [[data.get("local_model", "qwen3.5:4b"),
                                                                       data.get("local_model", "qwen3.5:4b")]],
            "local_voice": [list(v) for v in LOCAL_VOICES], "voice_name": [[v, v] for v in VOICES],
            "mic_device": [["", f"Follow Windows ({self._windows_device('mic')})"]] + [[n, n] for n in mics],
            "speaker_device": [["", f"Follow Windows ({self._windows_device('speaker')})"]] + [[n, n] for n in speakers],
            "wake_mode": [["openwakeword", "Wake words and hotkey"], ["hotkey", "Hotkey only"]],
            "ui_model": [list(u) for u in UI_MODELS],
        }
        values = {k: data.get(k) for k in options}
        values.update(brain=data.get("brain", "gemini"), ui_model=data.get("ui_model", "halo-ring"),
                      wake_mode=data.get("wake_mode", "hotkey"), local_voice=data.get("local_voice", "david"),
                      voice_name=data.get("voice_name", "Orus"), mic_device=data.get("mic_device") or "",
                      speaker_device=data.get("speaker_device") or "", local_model=data.get("local_model", "qwen3.5:4b"))
        defaults = {"local_brain_enabled": True, "memory_enabled": True, "announce_calls": True}
        values.update({k: data.get(k, defaults.get(k, False)) is not False and bool(data.get(k, defaults.get(k, False)))
                       for k in SWITCHES})
        values.update({k: data.get(k, "") for k in PLAIN})
        values["hotkey"] = data.get("hotkey", "ctrl+alt+t")
        values.update({k + "_set": bool(str(data.get(k, "")).strip()) and "YOUR_" not in str(data.get(k, "")) for k in KEYS})
        try:
            import autostart
            values["autostart"] = autostart.is_enabled()
        except Exception:
            values["autostart"] = False
        return {"values": values, "options": options}

    def save_settings(self, patch):
        old = _cfg()
        patch = {k: v for k, v in (patch or {}).items()
                 if not (k in KEYS and not str(v).strip()) and k != "autostart"}
        for k in ("mic_device", "speaker_device"):
            if k in patch:
                patch[k] = patch[k] or None
        if patch.get("local_brain_enabled") is False and patch.get("brain", old.get("brain")) == "local":
            return {"ok": False, "message": "Switch the brain to Gemini first: the local brain answers in that mode"}
        changed = {k: v for k, v in patch.items() if old.get(k) != v}
        config.update_config_file(changed)
        auto = (patch or {}).get("autostart")
        try:
            import autostart
            if auto is not None and auto != autostart.is_enabled():
                (autostart.enable if auto else autostart.disable)()
        except Exception:
            pass
        if changed.get("local_brain_enabled") is False:
            import local_brain
            threading.Thread(target=local_brain.unload, args=(old.get("local_model") or local_brain.DEFAULT_MODEL,),
                             daemon=True).start()
        live = {"announce_messages", "camera_enabled", "screen_enabled", "local_brain_enabled", "memory_enabled",
                "brain_debug"}
        if not changed:
            return _ok("Nothing changed")
        if set(changed) - live:
            return _ok(f"Saved. {self.restart_label} TRON to use the new settings", restart=True)
        return _ok("Saved")

    @staticmethod
    def _ollama_models():
        try:
            import requests
            import local_brain
            return sorted(m["name"] for m in requests.get(f"{local_brain.OLLAMA}/api/tags", timeout=1.5).json()["models"])
        except Exception:
            return []

    @staticmethod
    def _windows_device(kind):
        try:
            from pycaw.pycaw import AudioUtilities
            from pycaw.utils import AudioUtilities as AU
            dev = AudioUtilities.GetMicrophone() if kind == "mic" else AudioUtilities.GetSpeakers()
            return getattr(dev, "FriendlyName", None) or AU.CreateDevice(dev).FriendlyName or "now unknown"
        except Exception:
            return "now unknown"

    # ------------------------------------------------------------ identity and actions
    def switch_assistant(self, who):
        names = {a["id"]: a["name"] for a in _cfg().get("assistants") or config.DEFAULT_ASSISTANTS}
        if who not in names:
            return {"ok": False, "message": "Unknown assistant"}
        config.update_config_file({"active_assistant": who})
        return _ok(f"{names[who]} answers from the next conversation")

    def action(self, name, arg=None):
        do = getattr(self, "_act_" + str(name), None)
        if do is None:
            return {"ok": False, "message": f"Unknown action {name}"}
        try:
            return do(arg)
        except Exception as exc:
            return {"ok": False, "message": f"That didn't work: {exc}"}

    def _act_talk(self, _):
        if not self.machine:
            return {"ok": False, "message": "TRON isn't running. Press Start TRON"}
        threading.Thread(target=self.machine.hotkey, daemon=True).start()
        return _ok("Listening")

    def _act_restart(self, _):
        if self.on_restart:
            threading.Thread(target=lambda: (time.sleep(0.4), self.on_restart()), daemon=True).start()
        return _ok("Restarting. Back in a few seconds")

    def _act_open_folder(self, _):
        os.startfile(config.app_dir())
        return _ok("Opened TRON's folder")

    def _act_open_log(self, _):
        import convo_log
        if not convo_log.path().exists():
            return {"ok": False, "message": "No conversations yet"}
        os.startfile(convo_log.path())
        return _ok("Opened the conversation log")

    def _act_open_skills(self, _):
        import skills
        skills.skills_dir().mkdir(parents=True, exist_ok=True)
        os.startfile(skills.skills_dir())
        return _ok("Put a folder with a SKILL.md in here; TRON picks it up on its next conversation")

    _act_add_skill = _act_open_skills

    def _act_open_browser(self, _):
        import browser_intel
        return _ok(browser_intel.open_browser())

    def _act_test_voice(self, _):
        import tts
        tts.VOICE = _cfg().get("local_voice", tts.VOICE)
        threading.Thread(target=lambda: tts.say("This is how I sound, sir."), daemon=True).start()
        return _ok("Speaking")

    def _act_connect_google(self, _):
        import google_services
        return _ok(google_services.connect_google().replace(", sir", ""))

    def _cfg_obj(self):
        return getattr(self.machine, "_cfg", None) if self.machine else config.load_config()

    def _act_capture_face(self, name):
        import faces
        return _ok(faces.enroll_face({"name": name}, self._cfg_obj()).replace(", sir", ""))

    def _act_capture_voice(self, name):
        import voices
        return _ok(voices.enroll_voice({"name": name}, self._cfg_obj()).replace(", sir", "") +
                   " (it listened for 8 seconds after the chime)")

    def _act_whos_here(self, _):
        import cv2
        import faces
        frame, found = faces.look(self._cfg_obj())
        ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        names = [n or "someone I don't know" for n, _s, _b in found]
        message = ("I can see " + ", ".join(names)) if names else "I can't see anyone"
        return _ok(message, image="data:image/jpeg;base64," + base64.b64encode(jpeg.tobytes()).decode() if ok else "")

    def _act_add_word(self, arg):
        import dictation
        heard, meant = [str(x or "").strip() for x in (arg or ["", ""])]
        if not meant:
            return {"ok": False, "message": "Type the word as you want it written"}
        vocab = dictation.read_vocab()
        vocab.setdefault(meant, [])
        if heard and heard not in vocab[meant]:
            vocab[meant].append(heard)
        dictation.save_vocab(vocab)
        return _ok(f"Added {meant}")


class Server:
    """Serves the page and the Api on 127.0.0.1 with a per-launch token."""

    def __init__(self, api: Api):
        self.api, self.token = api, secrets.token_urlsafe(24)
        self.page_path = _page_path()
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body: bytes, kind="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.split("?")[0] != "/" or f"t={server.token}" not in self.path:
                    return self._send(404, b"not found", "text/plain")
                html = server.page_path.read_text(encoding="utf-8").replace(
                    "<head>", f"<head><script>window.TRON_TOKEN={json.dumps(server.token)};</script>", 1)
                self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

            def do_POST(self):
                name = self.path.removeprefix("/api/")
                if self.headers.get("X-Tron-Token") != server.token or name.startswith("_") \
                        or not callable(getattr(server.api, name, None)):
                    return self._send(403, b'{"ok":false,"message":"not allowed"}')
                try:
                    args = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"[]")
                    result = getattr(server.api, name)(*args)
                    self._send(200, json.dumps(result, default=str).encode("utf-8"))
                except Exception as exc:
                    self._send(200, json.dumps({"ok": False, "message": f"That didn't work: {exc}"}).encode("utf-8"))

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/?t={self.token}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


def _page_path():
    base = getattr(sys, "_MEIPASS", None)
    from pathlib import Path
    return Path(base) / "assets" / PAGE if base else Path(__file__).parent / "assets" / PAGE


def window_command(url: str) -> list:
    """How to start the window process: TRON.exe itself when frozen, else this Python with main.py."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--panel-window", url]
    return [sys.executable, str(__import__("pathlib").Path(__file__).parent / "main.py"), "--panel-window", url]


class WebPanel:
    """What main.py holds: show() opens the window (or brings it forward), browser_status() feeds the status
    line, on_state_change() is a no-op (the page polls status)."""

    def __init__(self, machine=None, on_restart=None, restart_label="Restart"):
        self.api = Api(machine, on_restart, restart_label)
        self.server = Server(self.api)
        self.proc = None
        self.browser_status = self.api.browser_status
        import atexit
        atexit.register(self.close)

    def show(self):
        if self.proc is not None and self.proc.poll() is None:
            _focus(self.proc.pid)
            return
        self.proc = subprocess.Popen(window_command(self.server.url),
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def on_state_change(self, state):
        pass

    def close(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()


def _focus(pid: int) -> None:
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        owner = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and u.IsWindowVisible(hwnd):
            u.ShowWindow(hwnd, 9)          # SW_RESTORE
            u.SetForegroundWindow(hwnd)
            return False
        return True
    u.EnumWindows(each, 0)


def run_window(url: str) -> None:
    """`TRON.exe --panel-window <url>`: the native window around the page."""
    import ctypes
    import webview
    ctypes.windll.shcore.SetProcessDpiAwareness(2) if hasattr(ctypes.windll, "shcore") else None
    window = webview.create_window("TRON", url, width=1180, height=760, min_size=(820, 560),
                                   background_color="#0A1A1F")

    def dark_title_bar():
        try:
            hwnd = window.native.Handle.ToInt32()   # this window's own handle (the orb may be titled TRON too)
            on = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), ctypes.sizeof(on))
        except Exception:
            pass
    window.events.shown += dark_title_bar
    webview.start(gui="edgechromium")
