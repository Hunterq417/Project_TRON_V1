# state_manager.py
import asyncio
import datetime
import json
import latency
import threading
import time
import traceback
from enum import Enum, auto

import brain
import config
import convo_log
import dictation
import faces
import voices
import memory
import local_brain
import offline
import routine
import skills
import perception
import tools
from audio_io import DuplexAudio, SAMPLE_RATE_IN, rms_level
from gemini_live_client import GeminiLiveSession


# In rms_level units (0-1). Separates "the user is talking" from "the microphone
# is switched on". The silence timeout depends on that distinction: it used to
# reset on any mic data at all, and since a live microphone always produces data
# it never once fired — conversations ran until the process died, and the wake
# word never re-armed because the trigger stays disabled for the duration.
# Ambient noise measured well under this on every device tried here; ordinary
# speech measured several times over it.
_SPEECH_LEVEL = 0.02

# Echo gate. TRON's own voice comes out of the speakers and straight back into the microphone, and
# Gemini hears it as the user talking: it answered itself over and over and its turn detection rarely
# saw silence, which is where the two-minute delays came from. Google's cookbook (issue #356) confirms
# it and says to wear headphones; this does it in code. While TRON speaks, and for a short tail after,
# the mic sends silence instead — unless someone is clearly louder than the echo (a barge-in).
_ECHO_TAIL = 1.2          # seconds after TRON's last audio still treated as echo; covers what is
                          # still in the speaker's buffer after the last write
_BARGE_IN_LEVEL = 0.10    # rms_level a voice must reach to cut in while TRON is speaking
_BARGE_IN_OVER_ECHO = 3.0 # ...and how many times the echo's own level

# How long the user must actually be quiet before the orb calls it THINKING.
# Mic blocks arrive every 100ms while the loop polls every 50ms, so without this
# the empty poll in between flipped the state ten times a second.
_PAUSE_BEFORE_THINKING = 0.6


def error_log_path():
    """Where failures are written. A function, not a constant, so the test
    suite can redirect it — tests used to fill the real log with their fake
    "network unreachable" failures, burying any genuine ones."""
    return config.app_dir() / "tron_error.log"


def _log_conversation_error() -> None:
    """Append the current traceback to tron_error.log.

    A failed conversation used to be discarded entirely: the orb turned red and
    that was the only evidence anywhere. The app is built windowed, so there is
    no console to print to either, which left "it listens but nothing happens"
    with nothing to go on. Appends rather than overwrites so a run of failures
    is all still there, and never raises — logging must not be able to break the
    thing it is reporting on."""
    try:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(error_log_path(), "a", encoding="utf-8") as log:
            log.write(f"\n===== conversation failed at {stamp} =====\n")
            log.write(traceback.format_exc())
    except Exception:
        pass


def _time_context() -> str:
    """Gemini has no innate sense of wall-clock time — this is how the persona's
    time-of-day greeting behavior (persona.txt) actually knows what time it is."""
    now = datetime.datetime.now()
    return f"Current time: {now.strftime('%A, %B %d, %Y, %I:%M %p')}"


class State(Enum):
    IDLE = auto()
    LISTENING = auto()
    THINKING = auto()
    SPEAKING = auto()
    ACTING = auto()
    ERROR = auto()
    DICTATING = auto()


_RETRIGGERABLE = (State.IDLE, State.ERROR)


class TronStateMachine:
    def __init__(
        self,
        api_key: str,
        model_name: str,
        voice_name: str,
        persona_text: str,
        silence_timeout_s: float,
        on_state_change=None,
        on_audio_level=None,
        on_conversation_end=None,
        audio: DuplexAudio | None = None,
        session_factory=None,
        cfg=None,
    ):
        self._api_key = api_key
        self._model_name = model_name
        self._voice_name = voice_name
        self._persona_text = persona_text
        self._silence_timeout_s = silence_timeout_s
        self._on_state_change = on_state_change or (lambda state: None)
        self._on_audio_level = on_audio_level or (lambda level: None)
        # Handed the finished conversation as whole turns. What gets done with
        # it — summarised, remembered, discarded — is not this class's business.
        self._on_conversation_end = on_conversation_end or (lambda turns: None)
        self.last_turns: list = []
        self._pending_note = ""      # one-shot line for a self-started conversation
        self.state = State.IDLE
        # Hotkey, wake word and the startup greeting all call trigger() from
        # their own threads. Checking state alone left a window of hundreds of
        # ms (opening audio devices) where two could both start a conversation.
        self._busy = threading.Lock()
        # Dictation (from Hey Jev). start_dictation ends the conversation and asks for this;
        # trigger() then runs it, and the next trigger — wake word or hotkey — stops it.
        self._dictate_after = False
        self._end_requested_at = 0.0
        self.dictation = None
        self._transcriber = None
        # main.py points this at the wake word's resume(): the wake word that started the
        # conversation is still paused for it, and "hey tron" has to be able to stop dictation.
        self.on_dictation_start = lambda: None
        self._stop_now = False   # set by a stop phrase or the hotkey: end this conversation at once
        # The conversation must listen on the same microphone as the wake word —
        # a mic that is right for one is right for both.
        self._audio = audio or DuplexAudio(
            device=getattr(cfg, "mic_device", None),
            output_device=getattr(cfg, "speaker_device", None),
        )
        self._cfg = cfg
        self._session_factory = session_factory or (
            lambda: GeminiLiveSession(
                self._api_key, self._model_name, self._voice_name,
                self._system_prompt(),
                tools=tools.declarations_for(self._cfg),
            )
        )

    def greet(self, note: str) -> None:
        """Start a conversation TRON opens itself, with a one-off instruction.

        No new machinery: it is an ordinary conversation whose system prompt
        carries one extra line telling the model to speak first. Everything
        else — looking through the camera, recognising who is there — is the
        model using tools it already has."""
        self._pending_note = note
        self.trigger()

    def _system_prompt(self) -> str:
        """Everything the model should know before it hears a word.

        Ordered durable-first: who TRON is, when it is, what it knows about the
        user, then what just happened. The empty-block filter is load-bearing —
        most of these are "" most of the time, and an unfiltered join leaves
        blank gaps that read as missing instructions."""
        blocks = (
            self._persona_text,
            brain.HOUSE_RULES,
            skills.context(),
            _time_context(),
            memory.long_term_context(),
            memory.recent_context(),
            voices.context(),
            self._pending_note,
        )
        # Consumed, not kept: the instruction belongs to this conversation only.
        # Leaving it set would make TRON open every later one by greeting.
        self._pending_note = ""
        return "\n\n".join(block for block in blocks if block)

    def _set_state(self, state: State) -> None:
        self.state = state
        self._on_state_change(state)

    async def _handle_vision_tool(self, name: str, session) -> str:
        try:
            frame = (
                perception.capture_screen_jpeg() if name == "look_at_screen"
                else perception.capture_camera_jpeg()
            )
        except Exception as exc:
            return f"couldn't capture that, sir: {exc}"
        await session.send_video_frame(frame)
        return "here's what I see, sir"

    def trigger(self) -> None:
        """Called by the wake word or the hotkey. Starts a conversation from IDLE or
        ERROR, stops a dictation in progress, and is a no-op during a conversation."""
        session = self.dictation
        if session is not None and session.active:
            session.stop()
            return
        if not self._busy.acquire(blocking=False):
            return
        try:
            # Twice at most: "switch to Jarvis" ends this conversation and JARVIS opens the next one himself.
            for _ in range(2):
                if self.state not in _RETRIGGERABLE:
                    break
                who = self._load_assistant()
                faces.refresh(self._cfg)   # who's at the PC, looked up while TRON starts listening
                if self._local_mode():
                    self._run_local()
                elif not self._online():
                    # Gemini can't be reached: TRON tries to reconnect, and works offline meanwhile.
                    if not self._run_offline():
                        return
                    asyncio.run(self._run_conversation())
                else:
                    asyncio.run(self._run_conversation())
                if self._dictate_after:
                    self._dictate_after = False
                    self._run_dictation()
                    break
                if who is None or self._active_id() == who:
                    break
                self._pending_note = ("You have just taken over from another assistant because the user asked "
                                      "for you. Speak first: introduce yourself in one short sentence, in your "
                                      "own manner, and ask what they need.")
        finally:
            self._busy.release()

    @staticmethod
    def _active_id():
        try:
            return config.active_assistant(json.loads(config.CONFIG_PATH.read_text(encoding="utf-8")))["id"]
        except Exception:
            return None

    def _load_assistant(self):
        """Picks up a switch to FRIDAY or JARVIS (by voice or the panel) at the start of the next
        conversation, without a restart. Only the voice and persona change: memory and tools are shared."""
        if not isinstance(self._cfg, config.Config):
            return None
        try:
            fresh = config.load_config()
            self._persona_text = config.resolve_path(fresh.persona_path).read_text(encoding="utf-8")
        except Exception:
            return None   # a half-written config.json: keep the current assistant rather than fail to start
        self._voice_name = fresh.voice_name
        self._cfg.voice_name, self._cfg.persona_path = fresh.voice_name, fresh.persona_path
        self._cfg.local_voice = fresh.local_voice
        import tts
        tts.VOICE = fresh.local_voice   # offline fallback and announcements speak as the new assistant too
        return self._active_id()

    def _online(self) -> bool:
        return offline.online()

    def _learn(self, lines: list) -> None:
        """After a Gemini conversation too, keep what's worth remembering ("for Hindi music, Karan Aujla"): the
        local model proposes, memory_service filters. Background thread; skipped when Ollama isn't running
        (learning must never start it up, or slow the next conversation)."""
        if not getattr(self._cfg, "memory_enabled", True):
            return

        def learn():
            if local_brain.enabled() and local_brain.server_up():
                local_brain.LocalBrain(cfg=self._cfg, model=getattr(self._cfg, "local_model", None)
                                       or local_brain.DEFAULT_MODEL).learn(lines)
        threading.Thread(target=learn, daemon=True).start()

    def _local_mode(self) -> bool:
        return getattr(self._cfg, "brain", "gemini") == "local"

    def _run_local(self) -> None:
        """A whole conversation on this PC: no Gemini, no internet needed."""
        greet, self._pending_note = bool(self._pending_note), ""
        self._stop_now = False
        events: list = []
        log = convo_log.Session()
        try:
            session = local_brain.LocalSession(self._cfg, lambda name: self._set_state(State[name]), events,
                                               persona=self._persona_text, should_stop=lambda: self._stop_now)
            session.run(greet=greet)
            self._dictate_after = session.dictate_after
        except Exception:
            _log_conversation_error()
            self._set_state(State.ERROR)
        log.flush(events)
        if self.state is not State.ERROR:
            self._set_state(State.IDLE)

    def _run_offline(self) -> bool:
        """The offline session. True when it got the internet back, so the real conversation can start."""
        self._pending_note = ""   # a greeting meant for Gemini; offline has nothing to give it to
        events: list = []
        log = convo_log.Session()
        try:
            session = offline.Session(self._cfg, lambda name: self._set_state(State[name]), events)
            back_online = session.run()
        except Exception:
            _log_conversation_error()
            back_online = False
        log.flush(events)
        self._set_state(State.IDLE)
        return back_online

    def hotkey(self) -> None:
        """The hotkey: starts a conversation, stops a dictation, and during a conversation means
        "stop talking" — the one interruption that never depends on being heard over TRON's voice."""
        if self.dictation is None and self._busy.locked():
            self._stop_now = True
            import browser_intel
            browser_intel.cancel()   # and whatever TRON is doing in the browser
            return
        self.trigger()

    def _run_dictation(self) -> None:
        """Records until the next trigger, then pastes the write-up where the cursor is."""
        import winsound
        chime = r"C:\Windows\Media\Speech On.wav"
        try:
            if self._transcriber is None:
                self._transcriber = dictation.best_transcriber(
                    self._api_key, getattr(self._cfg, "openrouter_api_key", ""),
                    local_first=self._local_mode())
            self.dictation = dictation.Session(self._transcriber, device=getattr(self._cfg, "mic_device", None))
            winsound.PlaySound(chime, winsound.SND_FILENAME | winsound.SND_NODEFAULT)
            self._set_state(State.DICTATING)
            self.on_dictation_start()
            text, failed, total = self.dictation.run(on_stopped=lambda: self._set_state(State.THINKING))
            winsound.PlaySound(chime, winsound.SND_FILENAME | winsound.SND_NODEFAULT)
            if failed:
                # never paste a dictation with holes in it as if it worked; keep what did work
                if text.replace("[missing part]", "").strip():
                    dictation.copy(text)
                result = (f"{failed} of {total} parts failed, not pasted. What worked is on the clipboard; "
                          "the missing audio is in memory/dictation_failed")
                self._set_state(State.ERROR)
            elif text:
                dictation.paste(text)
                result = f"pasted {len(text.split())} words"
                self._set_state(State.IDLE)
            else:
                result = "heard nothing to paste"
                self._set_state(State.IDLE)
            memory.log_activity({"tool": "dictation", "args": {}, "result": result})
        except Exception:
            _log_conversation_error()
            self._set_state(State.ERROR)
        finally:
            self.dictation = None

    async def _run_tool(self, call: dict, session) -> str:
        """Runs one tool call and always returns a result for the model.

        A tool that raised, or a name the model invented, used to kill the
        receive task without a trace: the conversation then sat silent until
        the timeout. Blocking handlers (PowerShell, SMTP, the first app-index
        scan) run on a worker thread so mic audio keeps flowing meanwhile."""
        name = call["name"]
        try:
            if name == "start_dictation":
                self._dictate_after = True
                self._end_requested_at = time.monotonic()
                return ("dictation starts after the chime once you finish this sentence. Tell the user to "
                        "start talking after the chime, and to say 'hey tron' or press the hotkey to stop")
            if name == "not_for_me":
                self._stop_now = True    # they're talking to someone else: go quiet, back to the wake word
                return "ok, silent"
            if name in tools.VISION_TOOL_NAMES:
                return await self._handle_vision_tool(name, session)
            handler = tools.TOOL_DISPATCH.get(name)
            if handler is None:
                return f"there is no tool called {name}, sir"
            routine.observe(name, call["args"], self._cfg)
            result = await asyncio.to_thread(handler, call["args"], self._cfg)
            if name == "switch_assistant":
                self._end_requested_at = time.monotonic()   # hand over now, in the new voice
            return result
        except Exception as exc:
            _log_conversation_error()
            return f"that failed, sir: {type(exc).__name__}: {exc}"

    async def _run_conversation(self) -> None:
        self._end_requested_at = 0.0
        self._stop_now = False
        started = datetime.datetime.now()
        guard = brain.Guard()
        log = convo_log.Session(started)
        last_user_words = [0.0]   # when the user's last transcribed words arrived
        last_activity = time.monotonic()
        last_audio = [0.0]
        spoke_ns = [0]   # end of the user's latest speech, waiting for the reply's first audio (latency.py)
        ended_in_error = False
        fragments: list = []    # (role, text) in order: user/assistant speech, tool calls, notes

        def stop_phrase_heard() -> bool:
            """Checked when TRON is about to answer: was the user's whole turn "shut up"?"""
            said = guard.current()
            if brain.is_stop(said):
                fragments.append(("note", f'stopped at once: "{said}" means stop talking'))
                self._stop_now = True
            return self._stop_now

        def touch() -> None:
            nonlocal last_activity
            last_activity = time.monotonic()

        try:
            # Inside the try: an unplugged headset must turn the orb red and
            # leave a log line, not raise into the hotkey thread.
            self._audio.start()
            self._set_state(State.LISTENING)
            async with self._session_factory() as session:

                def wrapping_up() -> bool:
                    """A tool asked to end the conversation (start_dictation): let TRON finish
                    saying so, then hang up — once a second has passed with no audio from it."""
                    now = time.monotonic()
                    return bool(self._end_requested_at) and now - self._end_requested_at > 2.0 \
                        and now - last_audio[0] > 1.2

                speaker = voices.Collector()

                async def send_loop() -> None:
                    was_listening = True
                    last_voice = time.monotonic()
                    echo_floor, loud_run = 0.0, 0
                    while (time.monotonic() - last_activity < self._silence_timeout_s
                           and not recv_task.done() and not wrapping_up() and not self._stop_now):
                        # A stop phrase is acted on as soon as the user has finished saying it, even if
                        # TRON already started answering: "shut up" got "Okay sir" and then "Understood,
                        # I shall remain quiet" when this waited for the answer to begin.
                        if last_user_words[0] and time.monotonic() - last_user_words[0] > 0.5 \
                                and brain.is_stop(guard.current()):
                            stop_phrase_heard()
                            break
                        chunk = self._audio.drain_mic()
                        if chunk:
                            level = rms_level(chunk)
                            if time.monotonic() - last_audio[0] < _ECHO_TAIL:
                                # TRON is talking: what the mic hears is mostly TRON.
                                loud = level >= max(_BARGE_IN_LEVEL, echo_floor * _BARGE_IN_OVER_ECHO)
                                loud_run = loud_run + 1 if loud else 0
                                echo_floor = 0.9 * echo_floor + 0.1 * level if not loud else echo_floor
                                if loud_run < 2:
                                    await session.send_audio_chunk(bytes(len(chunk)), SAMPLE_RATE_IN)
                                    await asyncio.sleep(0.05)
                                    continue
                            else:
                                echo_floor, loud_run = 0.0, 0
                                speaker.add_pcm16(chunk)   # TRON is quiet: this is the user's voice
                            # Gemini's own turn detection needs the stream to be
                            # continuous, so every chunk goes out including the
                            # quiet ones. Only speech counts as activity.
                            await session.send_audio_chunk(chunk, SAMPLE_RATE_IN)
                            if level >= _SPEECH_LEVEL:
                                # Loudness only drives the orb. It used to keep the conversation alive too,
                                # and with music playing a conversation never ended (nor got logged). Only
                                # words Gemini actually transcribes count as the user still talking.
                                last_voice = time.monotonic()
                                spoke_ns[0] = latency.now_ns()
                                if not was_listening:
                                    self._set_state(State.LISTENING)
                                    was_listening = True
                        if was_listening and time.monotonic() - last_voice > _PAUSE_BEFORE_THINKING:
                            self._set_state(State.THINKING)
                            was_listening = False
                        await asyncio.sleep(0.05)

                async def recv_loop() -> None:
                    async for event in session.receive():
                        if event["type"] in ("audio", "tool_call") and stop_phrase_heard():
                            return          # ends the conversation; nothing more is said or done
                        if event["type"] == "audio":
                            if self._stop_now:
                                return
                            guard.turn_over()
                            if spoke_ns[0]:
                                latency.record("response", spoke_ns[0])
                                spoke_ns[0] = 0
                            self._set_state(State.SPEAKING)
                            # Off the loop: write() blocks until the device
                            # buffer has room, which starved send_loop.
                            await asyncio.to_thread(self._audio.play_chunk, event["data"])
                            last_audio[0] = time.monotonic()
                            self._on_audio_level(rms_level(event["data"]))
                            touch()
                        elif event["type"] == "tool_call":
                            self._set_state(State.ACTING)
                            for call in event["calls"]:
                                refused = guard.check(call["name"], call["args"])
                                began = latency.now_ns()
                                result = refused or await self._run_tool(call, session)
                                latency.record("tool", began, detail=call["name"])
                                fragments.append(("tool", convo_log.tool_line(
                                    call["name"], call["args"], ("REFUSED BY SAFETY CHECK: " if refused else "") + result)))
                                memory.log_activity({
                                    "tool": call["name"], "args": call["args"], "result": result
                                })
                                await session.send_tool_response(call["id"], call["name"], result)
                            touch()
                        elif event["type"] == "transcript":
                            # Fragments, not utterances — joined into turns when
                            # the conversation ends. See memory.join_transcript.
                            fragments.append((event["role"], event["text"]))
                            if event["role"] == "user":
                                guard.user_said(event["text"])
                                last_user_words[0] = time.monotonic()
                                touch()
                            else:
                                guard.turn_over()
                        elif event["type"] == "turn_complete":
                            self._set_state(State.THINKING)
                            log.flush(fragments)
                        elif event["type"] == "go_away":
                            fragments.append(("note", "Gemini's session time limit reached; conversation closed"))
                            return   # ends the conversation cleanly; "hey tron" starts a fresh one

                recv_task = asyncio.create_task(recv_loop())
                try:
                    await send_loop()
                finally:
                    recv_task.cancel()
                # A receiver that died with an error ends the conversation as
                # one — previously its exception was never even retrieved.
                if recv_task.done() and not recv_task.cancelled():
                    recv_task.result()
        except Exception as exc:
            ended_in_error = True
            _log_conversation_error()
            fragments.append(("note", f"conversation failed: {type(exc).__name__}: {exc}"))
            self._set_state(State.ERROR)
        finally:
            self._audio.stop()
            # Outside the error branch on purpose: a conversation that ended
            # badly still happened, and what was said before it broke is worth
            # keeping. Never let saving take the conversation down with it.
            log.flush(fragments)
            self._learn(convo_log.format_events(fragments))
            try:
                self.last_turns = memory.join_transcript(
                    [(role, text) for role, text in fragments if role in ("user", "assistant")])
                self._on_conversation_end(self.last_turns)
            except Exception:
                pass
            if not ended_in_error:
                self._set_state(State.IDLE)
