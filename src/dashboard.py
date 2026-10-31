# dashboard.py
"""
TRON's control surface: a HUD served to the browser on localhost.

Why the browser rather than a native window — the look asked for (concentric
gauges, hairline strokes, corner brackets, tracked mono caps) is a page of SVG
and CSS, and tkinter would fight every pixel of it. Nothing new is installed:
this is `http.server` from the standard library.

The page is embedded in this module rather than shipped as a file beside the
exe. A data file next to a frozen binary silently goes stale when the Python
around it is rebuilt — that already cost a debugging session once with the orb's
HTML — and a string here simply cannot.

Security, because this is an HTTP server holding an API key:

* bound to 127.0.0.1, so nothing off this machine can reach it;
* every request must carry a token minted at launch, which only the page opened
  from the tray is given. Without this, any website you visited could POST to
  http://127.0.0.1:<port>/api/config, since browsers happily send cross-origin
  requests to localhost;
* secrets are never sent to the page. The API key and the SMTP password go out
  as a boolean "is it set", and only ever come back in.
"""
import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import config

# Values that are read once when TRON starts, so editing them here only takes
# effect on the next launch. The page badges these rather than pretending.
RESTART_REQUIRED = {
    "ui_model", "voice_name", "mic_device", "speaker_device", "wake_mode", "hotkey",
    "model_name", "active_assistant", "camera_enabled", "screen_enabled",
    "silence_timeout_s", "gemini_api_key",
}

# Never leaves the process. Written, never read back.
_SECRET_KEYS = {"gemini_api_key", "smtp_app_password"}

# Gemini Live's prebuilt voices. The field accepts anything, so a voice added
# after this was written can still be typed in.
VOICES = ["Orus", "Puck", "Charon", "Kore", "Fenrir", "Aoede", "Leda", "Zephyr"]

# Every renderer the orb can be drawn with. One today; the selector exists so
# adding another is data rather than a new control.
UI_MODELS = [
    {"id": "halo-ring", "name": "Halo Ring",
     "note": "Compact amber widget — floats on top, drag it anywhere", "available": True},
    {"id": "aurora-orb", "name": "Aurora Orb",
     "note": "Large iridescent sphere, sits on the desktop behind your windows",
     "available": True},
]


def _editable(cfg_data):
    """The config as the page should see it — secrets reduced to a flag."""
    out = {k: v for k, v in cfg_data.items() if k not in _SECRET_KEYS}
    for key in _SECRET_KEYS:
        out[key + "_set"] = bool(str(cfg_data.get(key, "")).strip())
    return out


def _audio_devices():
    """Input and output devices, or empty lists if the audio stack will not load.

    Imported lazily and defensively: sounddevice touches PortAudio, and a
    dashboard that will not open because a driver is unhappy is worse than one
    showing an empty device list."""
    try:
        import audio_io
        return (
            [{"index": i, "name": n, "channels": c} for i, n, c in audio_io.input_devices()],
            [{"index": i, "name": n, "channels": c} for i, n, c in audio_io.output_devices()],
        )
    except Exception:
        return [], []


class Dashboard:
    """Serves the control surface. Start it, hand the URL to a browser."""

    def __init__(self, on_change=None):
        self._token = secrets.token_urlsafe(24)
        self._on_change = on_change
        self._server = None
        self._pending_restart = set()

    # ---- config -----------------------------------------------------------

    def _read(self):
        if config.CONFIG_PATH.exists():
            return json.loads(config.CONFIG_PATH.read_text(encoding="utf-8"))
        return {}

    def _write(self, patch):
        """Merge a patch into config.json, preserving everything else.

        Written to a sibling file and moved into place: a half-written
        config.json is the difference between a settings tweak and an assistant
        that will not start."""
        # blank secret means "leave the stored one alone"
        patch = {k: v for k, v in patch.items()
                 if not (k in _SECRET_KEYS and not str(v).strip())}
        data = config.update_config_file(patch)
        self._pending_restart.update(k for k in patch if k in RESTART_REQUIRED)
        if self._on_change:
            try:
                self._on_change(data)
            except Exception:
                pass
        return data

    def state(self):
        data = self._read()
        mics, speakers = _audio_devices()
        assistants = data.get("assistants") or config.DEFAULT_ASSISTANTS
        return {
            "app": config.APP_LABEL,
            "config": _editable(data),
            "voices": VOICES,
            "ui_models": UI_MODELS,
            "assistants": assistants,
            "active_assistant": data.get("active_assistant", assistants[0]["id"]),
            "ui_model": data.get("ui_model", UI_MODELS[0]["id"]),
            "mics": mics,
            "speakers": speakers,
            "restart_required": sorted(self._pending_restart),
            "restart_keys": sorted(RESTART_REQUIRED),
        }

    # ---- server -----------------------------------------------------------

    def url(self):
        host, port = self._server.server_address[:2]
        return "http://127.0.0.1:%d/?t=%s" % (port, self._token)

    def start(self):
        dash = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass                      # a tray app has nowhere to log to

            def _authorised(self):
                """Token on the query string or the header, and a Host that is
                really loopback — the latter blocks DNS rebinding, where a
                hostile name resolves to 127.0.0.1 and the browser then treats
                the page as same-origin."""
                host = (self.headers.get("Host") or "").split(":")[0]
                if host not in ("127.0.0.1", "localhost"):
                    return False
                token = self.headers.get("X-Tron-Token")
                if not token:
                    token = parse_qs(urlparse(self.path).query).get("t", [""])[0]
                return secrets.compare_digest(token, dash._token)

            def _send(self, code, body, content_type):
                payload = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                path = urlparse(self.path).path
                if not self._authorised():
                    self._send(403, "forbidden", "text/plain; charset=utf-8")
                    return
                if path == "/":
                    self._send(200, PAGE.replace("__TOKEN__", dash._token),
                               "text/html; charset=utf-8")
                elif path == "/api/state":
                    self._send(200, json.dumps(dash.state()), "application/json")
                else:
                    self._send(404, "not found", "text/plain; charset=utf-8")

            def do_POST(self):
                if not self._authorised():
                    self._send(403, "forbidden", "text/plain; charset=utf-8")
                    return
                if urlparse(self.path).path != "/api/config":
                    self._send(404, "not found", "text/plain; charset=utf-8")
                    return
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    patch = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    self._send(400, "bad json", "text/plain; charset=utf-8")
                    return
                if not isinstance(patch, dict):
                    self._send(400, "expected an object", "text/plain; charset=utf-8")
                    return
                try:
                    dash._write(patch)
                except (OSError, ValueError) as exc:
                    # config.json unreadable: refuse rather than overwrite it.
                    self._send(409, "config.json could not be read: %s" % exc,
                               "text/plain; charset=utf-8")
                    return
                self._send(200, json.dumps(dash.state()), "application/json")

        # Port 0 = let the OS pick a free one, so two instances never collide.
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self.url()

    def open(self):
        """Start if needed and show the dashboard. Safe to call repeatedly."""
        if self._server is None:
            self.start()
        webbrowser.open(self.url())
        return self.url()

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server = None


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TRON // CONTROL</title>
<style>
:root{
  --bg:#03101a; --bg2:#061c28; --line:#0e4d5e; --line-dim:#0a3442;
  --cy:#22d3ee; --cy-dim:#0e7f96; --ink:#bfeff8; --ink-dim:#5b93a4;
  --warn:#f2b53a; --ok:#2ee6a8; --bad:#ff5470;
  --mono:ui-monospace,"Cascadia Mono","Consolas","SF Mono",monospace;
}
*{box-sizing:border-box}
html,body{height:100%}
body{
  margin:0;background:
    radial-gradient(900px 600px at 50% 40%,rgba(34,211,238,.07),transparent 65%),
    var(--bg);
  color:var(--ink);font-family:var(--mono);font-size:13px;letter-spacing:.06em;
}
/* faint engineering grid, like the reference boards */
body::before{
  content:"";position:fixed;inset:0;pointer-events:none;opacity:.35;
  background-image:linear-gradient(rgba(34,211,238,.05) 1px,transparent 1px),
                   linear-gradient(90deg,rgba(34,211,238,.05) 1px,transparent 1px);
  background-size:44px 44px;
  mask-image:radial-gradient(circle at 50% 45%,#000 0%,transparent 78%);
}
.wrap{position:relative;max-width:1500px;margin:0 auto;padding:26px 30px 60px}
/* viewport corner brackets */
.bracket{position:fixed;width:34px;height:34px;border:2px solid var(--cy);opacity:.55;pointer-events:none}
.bracket.tl{top:14px;left:14px;border-right:0;border-bottom:0}
.bracket.tr{top:14px;right:14px;border-left:0;border-bottom:0}
.bracket.bl{bottom:14px;left:14px;border-right:0;border-top:0}
.bracket.br{bottom:14px;right:14px;border-left:0;border-top:0}

header{display:flex;align-items:center;justify-content:space-between;gap:20px;
  border-bottom:1px solid var(--line-dim);padding-bottom:14px;margin-bottom:22px}
.brand{display:flex;align-items:baseline;gap:14px}
.brand h1{margin:0;font-size:19px;font-weight:600;letter-spacing:.42em;color:#eafcff;
  text-shadow:0 0 18px rgba(34,211,238,.55)}
.brand .sub{color:var(--ink-dim);font-size:10px;letter-spacing:.3em}
.readouts{display:flex;gap:26px;font-size:10px;letter-spacing:.2em;color:var(--ink-dim)}
.readouts b{display:block;color:var(--cy);font-weight:500;letter-spacing:.14em;font-size:12px;margin-top:3px}

.grid{display:grid;grid-template-columns:minmax(0,1fr) 400px minmax(0,1fr);gap:22px;align-items:start}
@media (max-width:1180px){.grid{grid-template-columns:1fr}.core{order:-1}}

.panel{position:relative;border:1px solid var(--line-dim);background:
  linear-gradient(180deg,rgba(8,38,50,.55),rgba(4,20,28,.4));padding:16px 16px 18px;margin-bottom:20px}
.panel::before,.panel::after{content:"";position:absolute;width:12px;height:12px;border:1px solid var(--cy);opacity:.75}
.panel::before{top:-1px;left:-1px;border-right:0;border-bottom:0}
.panel::after{bottom:-1px;right:-1px;border-left:0;border-top:0}
.panel > h2{margin:0 0 14px;font-size:10px;letter-spacing:.34em;color:var(--cy);font-weight:500;
  display:flex;align-items:center;gap:10px}
.panel > h2::after{content:"";flex:1;height:1px;background:linear-gradient(90deg,var(--line),transparent)}

.row{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:8px 0}
.row + .row{border-top:1px dashed var(--line-dim)}
.row label{font-size:10px;letter-spacing:.2em;color:var(--ink-dim);flex:0 0 auto;max-width:46%}
/* Controls shrink to their column instead of pushing out of the panel — the
   right-hand column is much narrower than the left and a fixed min-width made
   the inputs overhang the border. */
.row > *:not(label){flex:1 1 auto;min-width:0;display:flex;align-items:center;justify-content:flex-end;gap:8px}
.row > .toggle{flex:0 0 auto}
.hint{font-size:9px;color:var(--ink-dim);opacity:.75;letter-spacing:.12em;margin-top:6px;line-height:1.6}

select,input[type=text],input[type=password],input[type=number]{
  background:#04161f;border:1px solid var(--line);color:var(--ink);font-family:var(--mono);
  font-size:12px;letter-spacing:.08em;padding:7px 10px;width:100%;min-width:0;outline:none;
  text-overflow:ellipsis}
select:focus,input:focus{border-color:var(--cy);box-shadow:0 0 0 1px rgba(34,211,238,.35)}
input[type=range]{accent-color:var(--cy);width:100%;min-width:0}

.toggle{position:relative;width:52px;height:24px;border:1px solid var(--line);background:#04161f;cursor:pointer;flex:0 0 auto}
.toggle i{position:absolute;top:2px;left:2px;width:18px;height:18px;background:var(--ink-dim);transition:.18s}
.toggle.on{border-color:var(--cy)}
.toggle.on i{left:30px;background:var(--cy);box-shadow:0 0 12px var(--cy)}

.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{border:1px solid var(--line);padding:9px 12px;cursor:pointer;font-size:10px;letter-spacing:.18em;
  color:var(--ink-dim);background:#04161f;transition:.15s;position:relative}
.chip:hover{border-color:var(--cy-dim);color:var(--ink)}
.chip.on{border-color:var(--cy);color:#eafcff;background:rgba(34,211,238,.1);
  box-shadow:0 0 16px rgba(34,211,238,.22) inset}
.chip small{display:block;color:var(--ink-dim);letter-spacing:.1em;font-size:9px;margin-top:4px}
.chip[disabled]{opacity:.4;cursor:not-allowed}

.core{position:sticky;top:26px;display:flex;flex-direction:column;align-items:center;gap:14px}
.core svg{width:100%;max-width:360px;height:auto;filter:drop-shadow(0 0 26px rgba(34,211,238,.28))}
.core .name{font-size:17px;letter-spacing:.44em;color:#eafcff;text-shadow:0 0 16px rgba(34,211,238,.7)}
.core .role{font-size:9px;letter-spacing:.3em;color:var(--ink-dim)}
.ring-spin{transform-origin:200px 200px;animation:spin 26s linear infinite}
.ring-spin.rev{animation-direction:reverse;animation-duration:38s}
@keyframes spin{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){.ring-spin{animation:none}}

.bars{display:flex;gap:3px;align-items:flex-end;height:26px}
.bars span{width:4px;background:var(--cy);opacity:.75}

footer{margin-top:26px;border-top:1px solid var(--line-dim);padding-top:12px;
  display:flex;justify-content:space-between;align-items:center;gap:16px;font-size:9px;
  letter-spacing:.2em;color:var(--ink-dim)}
.badge{border:1px solid var(--warn);color:var(--warn);padding:6px 10px;font-size:9px;letter-spacing:.2em}
.badge.hidden{display:none}
#toast{position:fixed;right:24px;bottom:24px;border:1px solid var(--cy);background:#04202b;
  color:var(--ink);padding:11px 15px;font-size:10px;letter-spacing:.2em;opacity:0;
  transform:translateY(8px);transition:.2s;pointer-events:none}
#toast.show{opacity:1;transform:none}
</style></head><body>
<i class="bracket tl"></i><i class="bracket tr"></i><i class="bracket bl"></i><i class="bracket br"></i>

<div class="wrap">
  <header>
    <div class="brand">
      <h1>TRON</h1><span class="sub">CONTROL SURFACE</span>
    </div>
    <div class="readouts">
      <div>LINK<b id="r-link">LOCAL</b></div>
      <div>INPUT<b id="r-mic">—</b></div>
      <div>OUTPUT<b id="r-spk">—</b></div>
      <div>WAKE<b id="r-wake">—</b></div>
    </div>
  </header>

  <div class="grid">
    <!-- ============ left ============ -->
    <div>
      <section class="panel">
        <h2>VOICE</h2>
        <div class="row">
          <label>SPEECH MODEL</label>
          <select id="voice"></select>
        </div>
        <div class="row">
          <label>SILENCE TIMEOUT</label>
          <span><input type="range" id="silence" min="10" max="120" step="5">
            <b id="silence-v" style="color:var(--cy);margin-left:8px"></b></span>
        </div>
        <div class="hint">The voice TRON answers in. Takes effect the next time TRON starts.</div>
      </section>

      <section class="panel">
        <h2>AUDIO I/O</h2>
        <div class="row"><label>INPUT</label><select id="mic"></select></div>
        <div class="row"><label>OUTPUT</label><select id="spk"></select></div>
        <div class="hint">SYSTEM DEFAULT follows whatever Windows is using. Pin a device
          when the default is a headset that is not always in your ears — TRON answering
          into a disconnected earbud looks exactly like TRON not answering.</div>
      </section>

      <section class="panel">
        <h2>PERCEPTION</h2>
        <div class="row"><label>CAMERA</label><div class="toggle" id="camera"><i></i></div></div>
        <div class="row"><label>SCREEN</label><div class="toggle" id="screen"><i></i></div></div>
        <div class="hint">Lets TRON see. Off unless you turn it on.</div>
      </section>
    </div>

    <!-- ============ core ============ -->
    <div class="core">
      <svg viewBox="0 0 400 400" aria-hidden="true">
        <defs>
          <radialGradient id="g" cx="50%" cy="50%">
            <stop offset="55%" stop-color="#22d3ee" stop-opacity="0"/>
            <stop offset="100%" stop-color="#22d3ee" stop-opacity=".14"/>
          </radialGradient>
        </defs>
        <circle cx="200" cy="200" r="150" fill="url(#g)"/>
        <g fill="none" stroke="#22d3ee" stroke-width="1">
          <circle cx="200" cy="200" r="150" opacity=".28"/>
          <circle cx="200" cy="200" r="120" opacity=".5"/>
          <circle cx="200" cy="200" r="86"  opacity=".3"/>
          <g class="ring-spin">
            <circle cx="200" cy="200" r="138" opacity=".8" stroke-dasharray="3 14"/>
            <path d="M200 62 A138 138 0 0 1 320 130" opacity=".95" stroke-width="2"/>
            <path d="M200 338 A138 138 0 0 1 80 270" opacity=".95" stroke-width="2"/>
          </g>
          <g class="ring-spin rev">
            <circle cx="200" cy="200" r="104" opacity=".55" stroke-dasharray="30 10 6 10"/>
          </g>
          <circle cx="200" cy="200" r="66" opacity=".25"/>
        </g>
        <g stroke="#22d3ee" stroke-width="1" opacity=".55">
          <path d="M50 200h34M316 200h34M200 50v34M200 316v34"/>
        </g>
      </svg>
      <div class="name" id="core-name">TRON</div>
      <div class="role" id="core-role">ACTIVE ASSISTANT</div>
      <div class="bars" id="bars"></div>
    </div>

    <!-- ============ right ============ -->
    <div>
      <section class="panel">
        <h2>ASSISTANTS</h2>
        <div class="chips" id="assistants"></div>
        <div class="hint">Each profile carries its own voice and persona. Switching here
          changes who answers on the next launch. Saying "hey tron, switch to friday"
          is not wired up yet — this is the surface it will drive.</div>
      </section>

      <section class="panel">
        <h2>INTERFACE MODEL</h2>
        <div class="chips" id="ui-models"></div>
        <div class="hint">How the desktop orb is drawn. More renderers drop in here.</div>
      </section>

      <section class="panel">
        <h2>WAKE</h2>
        <div class="row"><label>MODE</label>
          <select id="wake"><option value="openwakeword">WAKE WORD</option><option value="hotkey">HOTKEY</option></select>
        </div>
        <div class="row"><label>HOTKEY</label><input type="text" id="hotkey" spellcheck="false"></div>
        <div class="hint">Wake word listens for "hey tron". Hotkey is the fallback.</div>
      </section>

      <section class="panel">
        <h2>CONNECTION</h2>
        <div class="row"><label>GEMINI KEY</label>
          <input type="password" id="apikey" placeholder="•••• stored" autocomplete="off"></div>
        <div class="row"><label>MODEL</label><input type="text" id="model" spellcheck="false"></div>
        <div class="hint">The key never leaves this machine and is never sent back to this
          page — leave it blank to keep the stored one.</div>
      </section>
    </div>
  </div>

  <footer>
    <span id="foot">READY</span>
    <span class="badge hidden" id="restart">RESTART REQUIRED TO APPLY</span>
  </footer>
</div>
<div id="toast"></div>

<script>
const TOKEN = "__TOKEN__";
const $ = s => document.querySelector(s);
let STATE = null, saving = false;

async function api(path, body){
  const r = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: {"X-Tron-Token": TOKEN, "Content-Type": "application/json"},
    body: body ? JSON.stringify(body) : undefined,
  });
  if(!r.ok) throw new Error(await r.text());
  return r.json();
}

function toast(msg){
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(()=>t.classList.remove("show"), 1800);
}

async function save(patch){
  if(saving) return;
  saving = true;
  try{ STATE = await api("/api/config", patch); render(); toast("SAVED"); }
  catch(e){ toast("FAILED: " + e.message); }
  finally{ saving = false; }
}

function deviceOptions(sel, list, value){
  sel.innerHTML = "";
  const def = document.createElement("option");
  def.value = ""; def.textContent = "SYSTEM DEFAULT";
  sel.appendChild(def);
  for(const d of list){
    const o = document.createElement("option");
    o.value = d.name; o.textContent = d.name.toUpperCase();
    sel.appendChild(o);
  }
  sel.value = (value === null || value === undefined) ? "" : String(value);
  // A pinned device that is currently unplugged still has to show, or the UI
  // would silently look like it is on the default.
  if(sel.value !== String(value ?? "")){
    const o = document.createElement("option");
    o.value = String(value); o.textContent = String(value).toUpperCase() + "  (NOT PRESENT)";
    sel.appendChild(o); sel.value = String(value);
  }
}

function render(){
  const c = STATE.config;
  const voice = $("#voice");
  voice.innerHTML = "";
  for(const v of STATE.voices){
    const o = document.createElement("option"); o.value = v; o.textContent = v.toUpperCase();
    voice.appendChild(o);
  }
  if(!STATE.voices.includes(c.voice_name)){
    const o = document.createElement("option");
    o.value = c.voice_name; o.textContent = String(c.voice_name).toUpperCase();
    voice.appendChild(o);
  }
  voice.value = c.voice_name;

  deviceOptions($("#mic"), STATE.mics, c.mic_device);
  deviceOptions($("#spk"), STATE.speakers, c.speaker_device);

  $("#silence").value = c.silence_timeout_s;
  $("#silence-v").textContent = c.silence_timeout_s + "s";
  $("#wake").value = c.wake_mode;
  $("#hotkey").value = c.hotkey || "";
  $("#model").value = c.model_name || "";
  $("#apikey").placeholder = c.gemini_api_key_set ? "•••••••••  STORED" : "NOT SET";
  $("#camera").classList.toggle("on", !!c.camera_enabled);
  $("#screen").classList.toggle("on", !!c.screen_enabled);

  const chips = $("#assistants"); chips.innerHTML = "";
  for(const a of STATE.assistants){
    const el = document.createElement("div");
    el.className = "chip" + (a.id === STATE.active_assistant ? " on" : "");
    el.innerHTML = "<span>" + a.name.toUpperCase() + "</span><small>" + (a.voice || "—") + "</small>";
    el.onclick = () => save({active_assistant: a.id});
    chips.appendChild(el);
  }

  const models = $("#ui-models"); models.innerHTML = "";
  for(const m of STATE.ui_models){
    const el = document.createElement("div");
    el.className = "chip" + (m.id === STATE.ui_model ? " on" : "");
    if(!m.available) el.setAttribute("disabled","");
    el.innerHTML = "<span>" + m.name.toUpperCase() + "</span><small>" + m.note + "</small>";
    if(m.available) el.onclick = () => save({ui_model: m.id});
    models.appendChild(el);
  }

  const active = STATE.assistants.find(a => a.id === STATE.active_assistant) || STATE.assistants[0];
  $("#core-name").textContent = (active ? active.name : "TRON").toUpperCase();
  $("#r-mic").textContent  = (c.mic_device ?? "DEFAULT").toString().slice(0,18).toUpperCase();
  $("#r-spk").textContent  = (c.speaker_device ?? "DEFAULT").toString().slice(0,18).toUpperCase();
  $("#r-wake").textContent = c.wake_mode === "hotkey" ? "HOTKEY" : "HEY TRON";
  $("#restart").classList.toggle("hidden", STATE.restart_required.length === 0);
  $("#foot").textContent = "CONFIG " + (STATE.restart_required.length ? "CHANGED" : "IN SYNC");
}

// idle telemetry bars — decoration, deliberately not pretending to be a meter
const bars = $("#bars");
for(let i=0;i<22;i++) bars.appendChild(document.createElement("span"));
setInterval(()=>{
  [...bars.children].forEach((b,i)=>{
    b.style.height = (5 + Math.abs(Math.sin(Date.now()/900 + i*0.55))*20).toFixed(1) + "px";
    b.style.opacity = 0.25 + Math.abs(Math.sin(Date.now()/1400 + i*0.4))*0.6;
  });
}, 90);

$("#voice").onchange   = e => save({voice_name: e.target.value});
$("#mic").onchange     = e => save({mic_device: e.target.value || null});
$("#spk").onchange     = e => save({speaker_device: e.target.value || null});
$("#wake").onchange    = e => save({wake_mode: e.target.value});
$("#hotkey").onchange  = e => save({hotkey: e.target.value.trim()});
$("#model").onchange   = e => save({model_name: e.target.value.trim()});
$("#apikey").onchange  = e => { if(e.target.value.trim()){ save({gemini_api_key: e.target.value.trim()}); e.target.value=""; } };
$("#silence").oninput  = e => $("#silence-v").textContent = e.target.value + "s";
$("#silence").onchange = e => save({silence_timeout_s: parseFloat(e.target.value)});
$("#camera").onclick   = () => save({camera_enabled: !STATE.config.camera_enabled});
$("#screen").onclick   = () => save({screen_enabled: !STATE.config.screen_enabled});

api("/api/state").then(s => { STATE = s; render(); })
                 .catch(e => { $("#foot").textContent = "LINK FAILED: " + e.message; });
</script></body></html>
"""
