# local_brain.py
"""TRON with no Gemini at all: hears with Parakeet, thinks with a local model, speaks with a local voice.

The brain is a small decision engine around the model (see LocalBrain): context built per request with
only the memories that matter (memory_service), the model decides by calling tools, the tool registry and
brain.Guard decide risk and confirmation in code, every result is verified (decision.verify), failures are
replanned a bounded number of times, each stage is logged to logs/brain_events.jsonl, and after the
conversation the model proposes what's worth remembering, which code filters before storing.

The model was chosen by testing on this PC (RTX 4070 laptop, 8 GB): 22 real requests sent with all of
TRON's tools and house rules.

    Qwen3.5-4B   21/22 right, 1.5 s typical     <- the default
    Qwen3.5-9B   20/22, 3.2 s (made up the time; said "locking" without locking)
    Phi-4-mini    3/22 (described tools instead of calling them)

Two findings shaped this file: TRON's 52 tool descriptions need a 16k context (at Ollama's default the
model saw a cut-off prompt and answered nonsense), and a local model has no clock, so the real time goes
into every request.
"""
import base64
import datetime
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import brain
import convo_log
import tools

OLLAMA = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3.5:4b"
NUM_CTX = 16384
HISTORY = 16
# Tools whose result is data for the model to read, not a sentence to say as it is.
FOLLOW_UP = {"remember_fact", "screen_elements", "list_windows", "recall_activity", "use_skill", "look_at_screen",
             "look_via_camera", "hardware_status", "check_timers", "find_file", "draft_email"}
_NO_WINDOW = 0x08000000
DANGLING = (r"\b(and|to|for|the|a|an|my|of|with|in|on|at|play|open|search|send|set|turn|called|named|about|"
            r"from|then|is|me|please)[\s,.]*$")


def _ollama_exe():
    found = shutil.which("ollama")
    if found:
        return found
    candidate = Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe"
    return str(candidate) if candidate.exists() else None


def server_up(timeout=2.0) -> bool:
    import requests
    try:
        return requests.get(f"{OLLAMA}/api/version", timeout=timeout).ok
    except Exception:
        return False


def models_dir():
    """Where the Ollama app keeps models, from its own settings. A server started without it looks in the
    default folder instead and sees a different set of models (here: the app uses C:\\Users\\shiva)."""
    import sqlite3
    db = Path.home() / "AppData" / "Local" / "Ollama" / "db.sqlite"
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            row = conn.execute("select models from settings limit 1").fetchone()
        return row[0] if row and row[0] else None
    except Exception:
        return None


def enabled() -> bool:
    """The Settings switch "Local brain": off means TRON never starts or uses Ollama (read live from
    config.json, so it applies without a restart)."""
    import json
    import config
    try:
        return json.loads(config.CONFIG_PATH.read_text(encoding="utf-8")).get("local_brain_enabled", True) is not False
    except (OSError, ValueError):
        return True


def unload(model=DEFAULT_MODEL) -> None:
    """Frees the GPU memory and RAM the model holds, now. Never raises."""
    import requests
    try:
        if server_up(1.0):
            requests.post(f"{OLLAMA}/api/generate", json={"model": model, "keep_alive": 0}, timeout=10)
    except Exception:
        pass


def ensure_server(wait=20.0) -> bool:
    """Ollama's server is what answers; its tray app sometimes leaves it stopped. Start it if needed."""
    import os
    if not enabled():
        return False
    if server_up():
        return True
    exe = _ollama_exe()
    if not exe:
        return False
    env = dict(os.environ)
    if models_dir() and not env.get("OLLAMA_MODELS"):
        env["OLLAMA_MODELS"] = models_dir()
    subprocess.Popen([exe, "serve"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW, env=env)
    deadline = time.time() + wait
    while time.time() < deadline:
        if server_up(1.0):
            return True
        time.sleep(0.5)
    return False


def available(model=DEFAULT_MODEL) -> bool:
    """True when the local brain can answer: Ollama running and the model downloaded."""
    import requests
    if not ensure_server():
        return False
    try:
        names = {m["name"] for m in requests.get(f"{OLLAMA}/api/tags", timeout=5).json().get("models", [])}
    except Exception:
        return False
    return model in names or f"{model}:latest" in names


def _tool_specs():
    return [{"type": "function", "function": {"name": d["name"], "description": d["description"],
                                              "parameters": d.get("parameters") or {"type": "object", "properties": {}}}}
            for d in tools.TOOL_DECLARATIONS + [tools._LOOK_AT_SCREEN_DECLARATION, tools._LOOK_VIA_CAMERA_DECLARATION]]


def warm_up(model=DEFAULT_MODEL) -> None:
    """Loads the model onto the GPU, and the voice and ears into memory, so the first "hey tron" after
    starting doesn't wait ~10 s for them. Never raises."""
    import requests
    try:
        if ensure_server():
            requests.post(f"{OLLAMA}/api/chat", timeout=120, json={
                "model": model, "stream": False, "think": False, "keep_alive": "30m",
                "options": {"num_ctx": NUM_CTX}, "messages": [{"role": "user", "content": "hi"}]})
    except Exception:
        pass
    import tts
    for load in (("tts.engine",) if tts.VOICE not in tts.WINDOWS_VOICES else ()) + ("offline.speech_model",):
        try:
            module, func = load.split(".")
            getattr(__import__(module), func)()
        except Exception:
            pass


def greeting() -> str:
    hour = datetime.datetime.now().hour
    part = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
    return f"Good {part}, sir. How may I help?"


class OllamaProvider:
    """The model behind the local brain. Swapping models means another class with this chat()/healthy()."""

    def __init__(self, model: str = DEFAULT_MODEL, post=None):
        import requests
        self.model = model
        self._post = post or requests.post

    def chat(self, messages: list, tools: list = None, format=None, temperature: float = 0.2) -> dict:
        body = {"model": self.model, "stream": False, "think": False, "keep_alive": "30m",
                "options": {"temperature": temperature, "num_ctx": NUM_CTX}, "messages": messages}
        if tools:
            body["tools"] = tools
        if format is not None:
            body["format"] = format
        reply = self._post(f"{OLLAMA}/api/chat", json=body, timeout=120)
        reply.raise_for_status()
        return reply.json().get("message", {})

    def healthy(self) -> bool:
        return available(self.model)


# Prompt modules, composed per request (spec: several focused prompts, not one giant one).
INTERPRETATION_RULES = (
    "How to decide:\n"
    "- Work out the outcome the user wants, not just their literal words, and do that: \"it's too loud\" "
    "means turn the volume down; \"skip this\" means the next track; \"open Spotify and play X\" means "
    "play_music X.\n"
    "- Do every part of a request: \"mute and lock\" is two tool calls. Use the fewest tools that do it.\n"
    "- Facts about this PC (time, battery, volume, what's open) come from tools, never from memory.\n"
    "- Use what was said earlier in this conversation: \"that\", \"it\", \"the same again\" refer to it.\n"
    "- Ask one short question only when something you need can't reasonably be inferred.\n"
    "- Explain what you already know (an error message, maths, a word) directly, without tools.")
RESPONSE_RULES = (
    "Replies are spoken aloud: one or two short sentences, no lists or markdown. Say what you did, never "
    "claim something worked unless the tool's result shows it, and say plainly what's blocked.")
REPLAN_NOTE = (
    "A step didn't work (results above). Don't repeat the same call: try a different tool or different "
    "arguments, or say briefly what's blocked. Never claim it worked.")
ACT_NOTE = ("You said you'd do it but called no tool, so nothing happened. Call the tool now, or ask the user "
            "if you really can't.")
# "I'll turn it down to 50 percent for you" with no tool call: a promise, and nothing happened (seen live).
_PROMISE = re.compile(r"\b(i'?ll|i will|let me|i'?m going to|i am going to)\b(?! (?:need|have) )", re.I)
_QUESTION = re.compile(r"^\s*(what|how|is|are|was|were|do|does|did|which|when|where|who|why|can|could)\b|\?\s*$",
                       re.I)
EVENTS_MAX_BYTES = 2 * 1024 * 1024


def log_event(stage: str, event: str, request_id: str = "", **meta) -> None:
    """One line per decision stage in logs/brain_events.jsonl (spec section 20). Tool arguments arrive already
    passed through decision._safe, so no key or password is written. Never raises."""
    import json
    import config
    try:
        path = config.app_dir() / "logs" / "brain_events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > EVENTS_MAX_BYTES:
            lines = path.read_text(encoding="utf-8").splitlines()
            path.write_text("\n".join(lines[len(lines) // 2:]) + "\n", encoding="utf-8")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"request_id": request_id, "timestamp": datetime.datetime.now().isoformat(),
                                "stage": stage, "event": event, **meta}, default=str) + "\n")
    except Exception:
        pass


class LocalBrain:
    """The decision engine for one conversation. reply() runs a bounded loop:

        build context -> model decides (tool calls) -> policy check -> run -> verify each result
        -> verified: say it | data: the model reads it | failed: replan another way | blocked: ask the user
    """

    def __init__(self, persona: str = "", model: str = DEFAULT_MODEL, cfg=None, post=None, provider=None):
        self.provider = provider or OllamaProvider(model, post)
        self.model = self.provider.model
        self.persona = persona
        self.cfg = cfg
        self.history: list = []
        self.max_tool_calls = int(getattr(cfg, "brain_max_tool_calls", 8) or 8)
        self.max_replans = int(getattr(cfg, "brain_max_replans", 2) or 2)
        self.debug = bool(getattr(cfg, "brain_debug", False))
        self._specs = [s for s in _tool_specs() if self._allowed(s["function"]["name"])]

    def _allowed(self, name):
        """The model is never shown a tool it may not use."""
        if name == "use_skill":
            import skills
            return bool(skills.all_skills())   # no skills installed: don't tempt the model to look for one
        if name == "look_at_screen":
            return bool(getattr(self.cfg, "screen_enabled", False))
        if name == "look_via_camera":
            return bool(getattr(self.cfg, "camera_enabled", False))
        return True

    def system(self, said: str = "") -> str:
        """Context builder: identity, rules, the memories that matter for this request, skills, the time."""
        import memory_service
        import skills
        now = datetime.datetime.now().strftime("%A %d %B %Y, %I:%M %p")
        tail = " ".join(m.get("content", "") for m in self.history[-6:] if m.get("role") == "user")
        remembered = ""
        if getattr(self.cfg, "memory_enabled", True):
            try:
                remembered = memory_service.context(said, tail, getattr(self.cfg, "memory_weights", None))
            except Exception:
                remembered = ""   # memory unavailable: carry on with the conversation alone
        import voices
        parts = [self.persona or "You are TRON, a voice assistant that controls the user's Windows PC. Address the user as sir.",
                 RESPONSE_RULES, INTERPRETATION_RULES, brain.HOUSE_RULES, skills.context(), remembered,
                 voices.context(),
                 f"The current date and time is {now}. Never guess the time; use this.",
                 f"You run entirely on this PC: your brain is the {self.model} model in Ollama, you hear with "
                 "Parakeet and speak with a voice generated on this PC. No internet service is involved."]
        return "\n\n".join(p for p in parts if p)

    def _chat(self, said):
        messages = [{"role": "system", "content": self.system(said)}] + self.history[-HISTORY:]
        return self.provider.chat(messages, tools=self._specs)

    def reply(self, said: str, guard: "brain.Guard", run_tool, log: list = None) -> str:
        """What TRON says back to `said`, after running and verifying whatever the model decided to do.
        run_tool(name, args) returns a sentence, or (sentence, jpeg_bytes) for the vision tools."""
        import uuid
        import decision
        import tool_registry
        log = log if log is not None else []
        rid = str(uuid.uuid4())
        started = time.time()
        log_event("request", "request_received", rid, chars=len(said))
        self.history.append({"role": "user", "content": said})
        spoken, calls_made, replans, notes, nudged = [], 0, 0, [], False
        for _round in range(self.max_replans + 3):
            t = time.time()
            message = self._chat(said)
            calls = message.get("tool_calls") or []
            text = (message.get("content") or "").strip()
            made = decision.from_calls(said, [(c["function"]["name"], c["function"].get("arguments") or {})
                                              for c in calls], tool_registry, text, rid)
            log_event("decision", "decision_created", rid, latency_ms=int((time.time() - t) * 1000),
                      mode=made.mode.value, intent=made.intent.primary, risk=made.risk.level.value,
                      tools=[p.tool for p in made.plan], confirmation=made.requires_confirmation)
            notes.append(f"{made.mode.value}: {made.intent.primary} (risk {made.risk.level.value})")
            if not calls:
                self.history.append({"role": "assistant", "content": text})
                if not nudged and _PROMISE.search(text) and not text.rstrip().endswith("?"):
                    nudged = True
                    log_event("verification", "promise_without_action", rid)
                    self.history.append({"role": "user", "content": ACT_NOTE})
                    continue
                return self._finish(rid, text, started, notes, replans, log)
            self.history.append({"role": "assistant", "content": text, "tool_calls": calls})
            outcome, spoken = [], []
            for call, step in zip(calls, made.plan):
                name, args = step.tool, call["function"].get("arguments") or {}
                t = time.time()
                if calls_made >= self.max_tool_calls:
                    refused = "NOT DONE: that's too many steps for one request; tell the user what's done so far."
                else:
                    refused = guard.check(name, args)
                result = refused or run_tool(name, args)
                calls_made += 0 if refused else 1
                image = None
                if isinstance(result, tuple):
                    result, image = result
                result = str(result)
                meta = tool_registry.get(name)
                # Read first, then act: "it's too loud" reads the volume, and the model must then turn it down.
                data = (name in FOLLOW_UP or image is not None or len(result) > 160
                        or (meta is not None and meta.category == "READ" and not _QUESTION.search(said)))
                check = decision.verify(result if not refused or result.startswith("NOT DONE") else "REFUSED " + result, data)
                log_event("verification", "verification_completed", rid, tool=name, args=step.args,
                          status=check.status, latency_ms=int((time.time() - t) * 1000))
                log.append(("tool", convo_log.tool_line(name, args, ("REFUSED BY SAFETY CHECK: " if refused else "") + result)))
                self.history.append({"role": "tool", "content": result, "tool_name": name})
                if image:
                    self.history.append({"role": "user", "content": "(this is what you asked to see)",
                                         "images": [base64.b64encode(image).decode()]})
                outcome.append(check.status)
                spoken.append(result)
            if all(s == "verified" for s in outcome):
                # The tools already said it ("Bluetooth is off, sir"): asking the model to repeat that costs a
                # second and a half for nothing.
                text = " ".join(spoken)
                self.history.append({"role": "assistant", "content": text})
                return self._finish(rid, text, started, notes, replans, log)
            if "replan" in outcome:
                replans += 1
                log_event("replan", "replan_started", rid, attempt=replans)
                if replans > self.max_replans:
                    break
                self.history.append({"role": "user", "content": REPLAN_NOTE})
        text = " ".join(s for s in spoken if not s.startswith("NOT DONE")) or "I couldn't finish that, sir."
        return self._finish(rid, text, started, notes, replans, log)

    def _finish(self, rid, text, started, notes, replans, log):
        log_event("response", "response_generated", rid, latency_ms=int((time.time() - started) * 1000),
                  replans=replans)
        if self.debug:
            log.append(("note", f"decision: {' -> '.join(notes)}; replans {replans}; {time.time() - started:.1f}s"))
        return text

    def learn(self, lines: list) -> list:
        """After a conversation: keep what's worth remembering (memory_service decides what that is)."""
        import memory_service
        if not getattr(self.cfg, "memory_enabled", True):
            return []
        stored = memory_service.extract(
            lines, lambda messages, schema: self.provider.chat(messages, format=schema, temperature=0.1).get("content", ""))
        log_event("memory", "memory_written", count=len(stored))
        return stored


class LocalSession:
    """One conversation with no Gemini: chime, listen, think, speak, until the user goes quiet."""

    def __init__(self, cfg=None, set_state=lambda name: None, log: list = None, persona: str = "",
                 should_stop=lambda: False, hear=None, speak=None, local_brain=None):
        import offline
        self.cfg = cfg
        self._set_state = set_state
        self.log = log if log is not None else []
        self._should_stop = should_stop
        import tts
        tts.VOICE = getattr(cfg, "local_voice", None) or tts.VOICE
        self.brain = local_brain or LocalBrain(persona, getattr(cfg, "local_model", None) or DEFAULT_MODEL, cfg)
        self.guard = brain.Guard()
        self.dictate_after = False
        self.handed_over = False   # "switch to Jarvis": end here, the state machine starts JARVIS
        self._hear = hear or (lambda: self._listen(offline))
        import voices
        self._speaker = voices.Collector()
        self._self_started = False   # set by run(greet=True): TRON opened this conversation
        self._speak = speak

    def _listen(self, offline):
        audio = offline.listen(getattr(self.cfg, "mic_device", None), wait_for_speech=8.0)
        if audio is None:
            return None
        self._set_state("THINKING")
        self._speaker.add(audio)          # who's talking, identified in the background
        said = offline.transcribe(audio)
        # People pause mid-request ("open Spotify and play ... blinding lights") and the 0.8 s endpoint
        # cut them off: a sentence ending on a word that needs more is still going, so keep listening.
        for _ in range(2):
            if not re.search(DANGLING, said, re.I):
                break
            self._set_state("LISTENING")
            more = offline.listen(getattr(self.cfg, "mic_device", None), wait_for_speech=3.0)
            if more is None:
                break
            said = f"{said} {offline.transcribe(more)}".strip()
        return said

    def say(self, text: str) -> None:
        if not text:
            return
        self.log.append(("assistant", text))
        self._set_state("SPEAKING")
        if self._speak is not None:
            self._speak(text)
            return
        import tts
        stop = threading.Event()

        def watch():   # the hotkey cuts TRON off mid-sentence
            while not stop.is_set():
                if self._should_stop():
                    stop.set()
                    return
                time.sleep(0.1)

        threading.Thread(target=watch, daemon=True).start()
        tts.say(text, stop=stop)
        stop.set()

    def run_tool(self, name, args):
        import perception
        import voices
        refused = voices.owner_refusal(self._speaker, name, self._self_started)
        if refused:
            return refused
        if name == "not_for_me":
            self.handed_over = True    # ends the conversation quietly; nothing is said
            return "ok, silent"
        if name == "start_dictation":
            self.dictate_after = True
            return "Dictation starts after the chime. Say hey tron or press the hotkey when you're done, sir."
        if name in ("look_at_screen", "look_via_camera"):
            try:
                frame = perception.capture_screen_jpeg() if name == "look_at_screen" else perception.capture_camera_jpeg()
            except Exception as exc:
                return f"couldn't capture that, sir: {exc}"
            return "here it is", frame
        handler = tools.TOOL_DISPATCH.get(name)
        if handler is None:
            return f"there is no tool called {name}"
        tools.routine.observe(name, args, self.cfg)
        self.handed_over = self.handed_over or name == "switch_assistant"
        import latency
        began = latency.now_ns()
        try:
            return str(handler(args, self.cfg))
        except Exception as exc:
            return f"that failed, sir: {type(exc).__name__}: {exc}"
        finally:
            latency.record("tool", began, brain="local", detail=name)

    def run(self, max_turns: int = 12, greet: bool = False) -> None:
        import winsound
        self._self_started = greet
        if greet:
            self.say(greeting())
        else:
            try:
                winsound.PlaySound(r"C:\Windows\Media\Speech On.wav", winsound.SND_FILENAME | winsound.SND_NODEFAULT)
            except Exception:
                pass
        for _ in range(max_turns):
            if self._should_stop():
                break
            self._set_state("LISTENING")
            said = self._hear()
            if not said:
                break                         # the user went quiet: the conversation is over
            self.log.append(("user", said))
            self.guard.user_said(said)
            if brain.is_stop(said):
                self.log.append(("note", f'stopped: "{said}" means stop talking'))
                break
            self._set_state("ACTING")
            import latency
            heard = latency.now_ns()   # speech already ended and was transcribed: this measures thinking
            try:
                answer = self.brain.reply(said, self.guard, self.run_tool, self.log)
            except Exception as exc:
                answer = "My local brain isn't answering, sir. Is Ollama running?"
                self.log.append(("note", f"local brain failed: {type(exc).__name__}: {exc}"))
            self.guard.turn_over()
            latency.record("response", heard, brain="local")
            self.say(answer)
            if self.dictate_after or self.handed_over:
                break
        self._set_state("IDLE")
        lines = [("YOU:  " if kind == "user" else "TRON: ") + text for kind, text in self.log if kind in ("user", "assistant")]
        # Learning runs after the conversation, on its own thread: it never delays an answer.
        threading.Thread(target=self.brain.learn, args=(lines,), daemon=True).start()
