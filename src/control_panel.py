# control_panel.py
"""TRON's control panel: a dark, grid-lit window in TRON's own colours, built with CustomTkinter.

Rail on the left (glowing status orb, pages, live timers), a status bar with quick actions on top, and pages:
Home (greeting, system status, quick actions, stats, recent conversation), Conversations, Memory (facts and
skills), Dictionary, Dictation history, Privacy, Settings, Keys. Jev's waveform bubble shows at the bottom of
the screen while dictating.

It lives on the orb's Tk root as a Toplevel, because tkinter allows one interpreter per process and the orb
already owns it. Everything that changes it from another thread goes through the _updates queue.
"""
import json
import math
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

import autostart
import config
import dictation
import memory
import timers

W, H = 1080, 700
FONT, ICONS, MONO = "Segoe UI", "Segoe Fluent Icons", "Cascadia Mono"
# TRON palette: near-black grid, one cyan light. Status colours are separate from the accent.
BG, RAIL, CARD, CARD_HI, LINE = "#070b10", "#0b1118", "#0f1821", "#142230", "#1b2a37"
TEXT, MUTED, FAINT = "#e3eef3", "#8aa0ac", "#56697a"
ACCENT, ACCENT_DIM, ACCENT_TEXT = "#2ee6ff", "#0e5966", "#04141a"
GOOD, WARN, BAD = "#3ddc84", "#f5b942", "#ff5c6c"
SECONDARY, HINT = MUTED, FAINT   # names older code and tests use

TABS = (("home", "Home"), ("convo", "Conversations"), ("memory", "Memory & skills"), ("dict", "Dictionary"),
        ("hist", "Dictation history"), ("faces", "People"), ("priv", "Privacy"), ("settings", "Settings"),
        ("keys", "Keys"))
TAB_ICONS = {"home": "", "convo": "", "memory": "", "dict": "", "hist": "",
             "faces": "\uE8D4", "priv": "", "settings": "", "keys": ""}
TYPING_WPM, SPEAKING_WPM = 40, 150   # for "time saved" by dictating instead of typing
VOICES = ["Orus", "Puck", "Charon", "Kore", "Fenrir", "Aoede", "Leda", "Zephyr"]
UI_MODELS = (("halo-ring", "Halo Ring (small, on top, draggable)"), ("aurora-orb", "Aurora Orb (large, on the desktop)"),
             ("dust-orb", "Dust Orb (particle cloud, on top, draggable)"))
STATES = {  # State name -> (headline, colour)
    "IDLE": ("Ready", GOOD), "LISTENING": ("Listening", ACCENT), "THINKING": ("Thinking", "#b48cff"),
    "SPEAKING": ("Speaking", "#2ee6b0"), "ACTING": ("Doing it", WARN),
    "ERROR": ("Something went wrong", BAD), "DICTATING": ("Dictating", BAD),
}
HOW_TO = ("Say “hey tron” (or press {hotkey}) and just talk: “open Spotify and play Blinding Lights”, "
          "“set a timer for ten minutes”, “turn Spotify down”, “clip this video from 1:20 to 2:05”.\n\n"
          "Say “hey tron, take dictation” to type by voice: talk after the chime, then say “hey tron” "
          "or press the hotkey, and it’s pasted where your cursor is.")
PRIVACY = (
    ("Stays on your PC", "The wake word, and in Local mode everything TRON hears, thinks and says, runs on this "
                         "PC. Your memory, dictionary, dictation history, clips and logs stay in TRON’s folder."),
    ("Google Gemini  ·  audio", "Gemini mode only: your voice during a conversation, to understand it and answer."),
    ("OpenRouter, or Gemini  ·  audio", "Dictation audio between the chime and “hey tron”, when a key is set "
                                        "and TRON isn’t in Local mode. Local mode transcribes on this PC first."),
    ("Google Gemini  ·  images", "Gemini mode only: a screenshot or webcam frame when you ask TRON to look, and "
                                 "only if Screen or Camera is switched on below."),
    ("Email  ·  your SMTP server", "An email, only after TRON reads it back and you say yes."),
)
LOCAL_VOICES = (("david", "Microsoft David (Windows)"), ("zira", "Microsoft Zira (Windows)"),
                ("hazel", "Microsoft Hazel (Windows, British)"), ("am_michael", "Michael (Kokoro)"),
                ("am_adam", "Adam (Kokoro)"), ("bm_george", "George (Kokoro, British)"),
                ("af_heart", "Heart (Kokoro)"), ("bf_emma", "Emma (Kokoro, British)"))


def _scale(root) -> float:
    return root.winfo_fpixels("1i") / 96   # text grows with Windows display scaling; sizes must too


def _font(size=13, weight="normal", family=FONT):
    return ctk.CTkFont(family=family, size=size, weight=weight)


class Bubble:
    """Jev's pill at the bottom middle of the screen with a live waveform. Click-through, never focused."""
    WIDTH, HEIGHT, BARS, KEY = 132, 36, 20, "#151516"   # KEY is made transparent around the rounded pill

    def __init__(self, root, levels_source, scale=1.0):
        import ctypes
        self.root, self.levels_source, self.k = root, levels_source, scale
        self.w, self.h = int(self.WIDTH * scale), int(self.HEIGHT * scale)
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=self.KEY)
        self.win.attributes("-transparentcolor", self.KEY)
        self.canvas = tk.Canvas(self.win, width=self.w, height=self.h, bg=self.KEY, highlightthickness=0)
        self.canvas.pack()
        self.working, self.phase, self.visible = False, 0.0, False
        self.win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
        # layered + transparent to clicks + never activates + kept out of the taskbar
        ctypes.windll.user32.SetWindowLongW(hwnd, -20, style | 0x80000 | 0x20 | 0x08000000 | 0x80)

    def show(self, working=False):
        self.working = working
        if not self.visible:
            self.visible = True
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            self.win.geometry(f"+{(sw - self.w) // 2}+{sh - self.h - int(80 * self.k)}")
            self.win.deiconify()
            self._tick()

    def hide(self):
        self.visible = False
        self.win.withdraw()

    def _tick(self):
        if not self.visible:
            return
        self.phase += 0.35
        try:
            self._draw()
        except Exception as exc:  # a drawing error must never take the GUI loop down
            print(f"bubble draw failed: {exc}")
        self.root.after(33, self._tick)

    def _draw(self):
        c, w, h, k = self.canvas, self.w, self.h, self.k
        c.delete("all")
        c.create_oval(0, 0, h, h, fill="#141414", outline="")
        c.create_oval(w - h, 0, w, h, fill="#141414", outline="")
        c.create_rectangle(h // 2, 0, w - h // 2, h, fill="#141414", outline="")
        levels = list(self.levels_source())[-self.BARS:]
        levels = [0.0] * (self.BARS - len(levels)) + levels
        gap = bar_w = 3.0 * k
        left = (w - self.BARS * (bar_w + gap) + gap) / 2
        max_h = h - 14 * k
        color = ACCENT if self.working else "#ffffff"
        for i, rms in enumerate(levels):
            if self.working:   # gentle travelling pulse while it's written up
                bh = 0.25 + 0.2 * (1 + math.sin(self.phase - i * 0.5))
            else:
                bh = min(1.0, math.sqrt(rms / 0.08))
            bh = max(3.0 * k, bh * max_h)
            x, y = left + i * (bar_w + gap), (h - bh) / 2
            c.create_rectangle(x, y, x + bar_w, y + bh, fill=color, outline="")


class ControlPanel:
    """Build once on the GUI thread; show() / on_state_change() are safe from any thread via the queue."""

    def __init__(self, root, machine=None, on_restart=None, restart_label="Restart TRON"):
        self.root, self.machine = root, machine
        self.on_restart, self.restart_label = on_restart, restart_label
        self.k = _scale(root)
        self._updates: queue.Queue = queue.Queue()
        ctk.set_appearance_mode("dark")
        self.win = ctk.CTkToplevel(root, fg_color=BG)
        self.win.withdraw()
        self.win.title(f"{config.APP_LABEL} — Control Panel")
        self.win.geometry(f"{W}x{H}")
        self.win.minsize(880, 580)
        self.win.protocol("WM_DELETE_WINDOW", self.win.withdraw)  # the tray brings it back
        self.win.bind("<Escape>", lambda _e: self.win.withdraw())
        self._dark_title_bar()
        self._style_tables()

        self.rail = ctk.CTkFrame(self.win, fg_color=RAIL, corner_radius=0, width=228)
        self.rail.pack(side="left", fill="y")
        self.rail.pack_propagate(False)
        ctk.CTkFrame(self.win, fg_color=LINE, corner_radius=0, width=1).pack(side="left", fill="y")
        main = ctk.CTkFrame(self.win, fg_color=BG, corner_radius=0)
        main.pack(side="left", fill="both", expand=True)
        self._build_rail()
        self._build_header(main)
        self.body = ctk.CTkFrame(main, fg_color=BG, corner_radius=0)
        self.body.pack(fill="both", expand=True)
        self.pages = {"home": self._build_home(), "convo": self._build_conversations(),
                      "memory": self._build_memory(), "dict": self._build_dictionary(),
                      "hist": self._build_history(), "priv": self._build_privacy(),
                      "settings": self._build_settings(), "keys": self._build_keys(), "faces": self._build_faces()}
        self.bubble = Bubble(root, self._levels, self.k)
        self.current, self._state, self._phase = None, "IDLE", 0.0
        self._select_tab("keys" if self._needs_keys() else "home")
        self.win.after(80, self._pump)
        self.win.after(500, self._tick)

    # ------------------------------------------------------------------ thread-safe entry points
    def show(self):
        self._updates.put(("show", None))

    def on_state_change(self, state):
        self._updates.put(("state", state.name))

    def _pump(self):
        try:
            while True:
                kind, value = self._updates.get_nowait()
                if kind == "show":
                    self._select_tab(self.current or "home")
                    self.win.deiconify()
                    self.win.lift()
                    self.win.focus_force()
                elif kind == "state":
                    self._apply_state(value)
                elif kind == "call":
                    value()
        except queue.Empty:
            pass
        self._draw_orb()
        self.win.after(80, self._pump)

    def _later(self, fn):
        """Run fn on the GUI thread (from a worker thread)."""
        self._updates.put(("call", fn))

    def _apply_state(self, name):
        self._state = name
        headline, colour = STATES.get(name, (name.title(), TEXT))
        self.status.configure(text=headline)
        self.pill.configure(border_color=colour)
        self.pill_dot.configure(text_color=colour)
        detail = {"IDLE": self._ready_text(), "DICTATING": "Say “hey tron” or press the hotkey to stop",
                  "ERROR": "Details are in tron_error.log next to TRON"}.get(name, "")
        self.detail.configure(text=detail)
        if name == "DICTATING":
            self.bubble.show()
        elif name == "THINKING" and self.bubble.visible:
            self.bubble.show(working=True)   # dictation stopped, being written up
        else:
            self.bubble.hide()

    def _levels(self):
        session = getattr(self.machine, "dictation", None)
        return session.levels if session is not None else ()

    # ------------------------------------------------------------------ helpers
    def _config(self) -> dict:
        try:
            return json.loads(config.CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _needs_keys(self):
        data = self._config()
        return data.get("brain", "gemini") != "local" and not data.get("gemini_api_key")

    def _ready_text(self):
        data = self._config()
        hotkey = data.get("hotkey", "ctrl+alt+t")
        if data.get("wake_mode") == "openwakeword":
            return f"Say “hey tron” or press {hotkey}"
        return f"Press {hotkey} to talk"

    def _dark_title_bar(self):
        try:
            import ctypes
            self.win.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id())
            on = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), ctypes.sizeof(on))
        except Exception:
            pass   # an older Windows keeps its light title bar; nothing else depends on it

    def _style_tables(self):
        style = ttk.Style(self.win)
        style.theme_use("clam")
        style.configure("Tron.Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT, borderwidth=0,
                        rowheight=int(30 * self.k), font=(FONT, 10))
        style.configure("Tron.Treeview.Heading", background=RAIL, foreground=MUTED, borderwidth=0, relief="flat",
                        font=(FONT, 9, "bold"), padding=(8, 6))
        style.map("Tron.Treeview", background=[("selected", ACCENT_DIM)], foreground=[("selected", TEXT)])
        style.map("Tron.Treeview.Heading", background=[("active", CARD_HI)])
        style.layout("Tron.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    def _label(self, parent, text, size=13, bold=False, color=TEXT, **kw):
        return ctk.CTkLabel(parent, text=text, font=_font(size, "bold" if bold else "normal"), text_color=color,
                            anchor="w", justify="left", **kw)

    def _button(self, parent, text, command, icon="", primary=False, **kw):
        label = f"{icon}  {text}" if icon else text
        return ctk.CTkButton(parent, text=label, command=command, height=34, corner_radius=8,
                             font=_font(12, "bold" if primary else "normal"),
                             fg_color=ACCENT if primary else CARD_HI, hover_color="#7ff1ff" if primary else LINE,
                             text_color=ACCENT_TEXT if primary else TEXT, border_width=0 if primary else 1,
                             border_color=LINE, **kw)

    def _card(self, parent, **kw):
        return ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12, border_width=1, border_color=LINE, **kw)

    def _page(self, title, subtitle):
        page = ctk.CTkScrollableFrame(self.body, fg_color=BG, corner_radius=0, scrollbar_button_color=LINE,
                                      scrollbar_button_hover_color=ACCENT_DIM)
        if title:
            head = ctk.CTkFrame(page, fg_color="transparent")
            head.pack(fill="x", padx=28, pady=(18, 10))
            self._label(head, title, 24, True).pack(fill="x")
            self._label(head, subtitle, 12, color=MUTED, wraplength=720).pack(fill="x", pady=(2, 0))
        return page

    def _section(self, page, title, note=""):
        """A titled card on a page; returns the card's inner frame."""
        card = self._card(page)
        card.pack(fill="x", padx=28, pady=8)
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=18, pady=14)
        self._label(inner, title.upper(), 11, True, color=ACCENT).pack(fill="x")
        if note:
            self._label(inner, note, 12, color=MUTED, wraplength=700).pack(fill="x", pady=(2, 6))
        return inner

    def _table(self, parent, columns, height=8):
        frame = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=8)
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", selectmode="browse",
                            style="Tron.Treeview", height=height)
        for ident, title, width in columns:
            tree.heading(ident, text=title, anchor="w")
            tree.column(ident, width=int(width * self.k), anchor="w", stretch=ident == columns[-1][0])
        bar = ctk.CTkScrollbar(frame, command=tree.yview, button_color=LINE, button_hover_color=ACCENT_DIM)
        tree.configure(yscrollcommand=bar.set)
        tree.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=4)
        bar.pack(side="right", fill="y")
        frame.pack(fill="both", expand=True, pady=8)
        return tree

    def _message(self, parent):
        var = tk.StringVar()
        ctk.CTkLabel(parent, textvariable=var, font=_font(11), text_color=MUTED, anchor="w").pack(side="left", padx=10)
        return var

    def _entry(self, parent, placeholder="", width=240, secret=False):
        return ctk.CTkEntry(parent, placeholder_text=placeholder, width=width, height=34, corner_radius=8,
                            fg_color=BG, border_color=LINE, text_color=TEXT, placeholder_text_color=FAINT,
                            show="•" if secret else "")

    @staticmethod
    def _value(entry):
        return entry.get().strip()

    def _reset(self, entry):
        entry.delete(0, "end")
        self.win.focus_set()   # puts the placeholder back

    def _edit_cell(self, tree, event, on_save):
        """Double-click a cell to edit it in place. on_save(row_index, column_id, text)."""
        row, col = tree.identify_row(event.y), tree.identify_column(event.x)
        if not row or not col:
            return
        x, y, w, h = tree.bbox(row, col)
        column = tree["columns"][int(col[1:]) - 1]
        entry = tk.Entry(tree, bg=BG, fg=TEXT, insertbackground=ACCENT, relief="flat", font=(FONT, 10),
                         highlightthickness=1, highlightcolor=ACCENT, highlightbackground=ACCENT)
        entry.insert(0, tree.set(row, column))
        entry.select_range(0, "end")
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()

        def done(_e=None, save=True):
            if save and entry.winfo_exists():
                on_save(tree.index(row), column, entry.get())
            entry.destroy()

        entry.bind("<Return>", done)
        entry.bind("<FocusOut>", done)
        entry.bind("<Escape>", lambda e: done(e, save=False))

    # ------------------------------------------------------------------ chrome
    def _build_rail(self):
        brand = ctk.CTkFrame(self.rail, fg_color="transparent")
        brand.pack(fill="x", padx=18, pady=(20, 18))
        size = int(46 * self.k)
        self.orb = tk.Canvas(brand, width=size, height=size, bg=RAIL, highlightthickness=0)
        self.orb.pack(side="left")
        names = ctk.CTkFrame(brand, fg_color="transparent")
        names.pack(side="left", padx=(12, 0))
        ctk.CTkLabel(names, text=config.APP_NAME, font=_font(22, "bold", "Segoe UI Black"), text_color=TEXT,
                     anchor="w").pack(fill="x")
        self._label(names, f"v{config.APP_VERSION}  ·  control panel", 10, color=FAINT).pack(fill="x")

        self.tab_buttons = {}
        for key, title in TABS:
            b = ctk.CTkButton(self.rail, text=f"{TAB_ICONS[key]}    {title}", anchor="w", height=38, corner_radius=8,
                              font=_font(13), fg_color="transparent", hover_color=CARD_HI, text_color=MUTED,
                              command=lambda k=key: self._select_tab(k))
            b.pack(fill="x", padx=12, pady=1)
            self.tab_buttons[key] = b

        self.hint = self._label(self.rail, self._ready_text(), 11, color=FAINT, wraplength=190)
        self.hint.pack(side="bottom", fill="x", padx=20, pady=(6, 18))
        self.timer_frame = ctk.CTkFrame(self.rail, fg_color="transparent")
        self.timer_frame.pack(side="bottom", fill="x", padx=14)
        self.timer_rows = []
        for _ in range(3):   # up to 3 timers, soonest on top
            row = ctk.CTkFrame(self.timer_frame, fg_color=CARD, corner_radius=8, border_width=1, border_color=LINE)
            name = self._label(row, "", 11, color=MUTED)
            left = ctk.CTkLabel(row, text="", font=_font(14, "bold", MONO), text_color=ACCENT)
            name.pack(side="left", padx=(10, 0), pady=6)
            left.pack(side="right", padx=10)
            self.timer_rows.append((row, name, left))

    def _draw_orb(self):
        """The rail's orb glows in the state's colour and breathes while TRON is busy."""
        c = self.orb
        size = int(c.cget("width"))
        colour = STATES.get(self._state, ("", ACCENT))[1]
        busy = self._state not in ("IDLE",)
        self._phase += 0.18 if busy else 0.05
        pulse = (math.sin(self._phase) + 1) / 2
        c.delete("all")
        mid = size / 2
        for ring, alpha in ((0.98, 0.10), (0.84, 0.22), (0.70, 0.45)):   # soft glow, faked with blended rings
            r = mid * (ring - (0.0 if busy else 0.06) + 0.05 * pulse)
            c.create_oval(mid - r, mid - r, mid + r, mid + r, fill=_mix(RAIL, colour, alpha), outline="")
        core = mid * 0.42
        c.create_oval(mid - core, mid - core, mid + core, mid + core, fill=_mix(colour, "#ffffff", 0.35), outline="")

    def _build_header(self, main):
        head = ctk.CTkFrame(main, fg_color=BG, corner_radius=0)
        head.pack(fill="x", padx=28, pady=(16, 6))
        self.pill = ctk.CTkFrame(head, fg_color=CARD, corner_radius=18, border_width=1, border_color=GOOD)
        self.pill.pack(side="left")
        self.pill_dot = ctk.CTkLabel(self.pill, text="●", font=_font(14), text_color=GOOD)
        self.pill_dot.pack(side="left", padx=(14, 6), pady=4)
        self.status = ctk.CTkLabel(self.pill, text="Ready", font=_font(14, "bold"), text_color=TEXT)
        self.status.pack(side="left", padx=(0, 16))
        self.detail = self._label(head, self._ready_text(), 12, color=MUTED)
        self.detail.pack(side="left", padx=14)
        if self.on_restart:
            # Most settings and a new key are read once at startup; this applies them in one click.
            self._button(head, self.restart_label, self._restart, icon="").pack(side="right")
        if self.machine is not None:
            self._button(head, "Talk to TRON", self._talk, icon="", primary=True).pack(side="right", padx=8)

    def _talk(self):
        threading.Thread(target=self.machine.hotkey, daemon=True).start()

    def _restart(self):
        self.status.configure(text="Restarting…")
        self.detail.configure(text="TRON will be back in a few seconds")
        self.win.update_idletasks()
        self.on_restart()

    def _select_tab(self, key):
        loaders = {"home": self._load_stats, "convo": self._load_conversations, "memory": self._load_memory,
                   "hist": self._load_history, "settings": self._load_settings, "faces": self._load_faces}
        if key in loaders:
            loaders[key]()
        for name, page in self.pages.items():
            if name == key:
                page.pack(fill="both", expand=True)
            else:
                page.pack_forget()
        for name, b in self.tab_buttons.items():
            on = name == key
            b.configure(fg_color=CARD_HI if on else "transparent", text_color=ACCENT if on else MUTED,
                        font=_font(13, "bold" if on else "normal"))
        self.current = key

    def _tick(self):
        running = timers.snapshot()[:3]
        for i, (row, name_view, time_view) in enumerate(self.timer_rows):
            if i < len(running):
                name, left = running[i]
                m, sec = divmod(int(left + 0.999), 60)
                h, m = divmod(m, 60)
                name_view.configure(text=f"  {name}")
                time_view.configure(text=f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}")
                row.pack(fill="x", pady=3)
            else:
                row.pack_forget()
        self.win.after(500, self._tick)

    # ------------------------------------------------------------------ home
    def _build_home(self):
        page = self._page("", "")
        hero = ctk.CTkFrame(page, fg_color="transparent")
        hero.pack(fill="x", padx=28, pady=(18, 6))
        self.greeting = self._label(hero, "", 28, True)
        self.greeting.pack(fill="x")
        self.subgreeting = self._label(hero, "", 13, color=MUTED)
        self.subgreeting.pack(fill="x")

        # System: what TRON is running on right now
        sysrow = ctk.CTkFrame(page, fg_color="transparent")
        sysrow.pack(fill="x", padx=22, pady=6)
        self.sys_tiles = {}
        for col, (key, title, icon) in enumerate((("brain", "Brain", ""), ("voice", "Voice", ""),
                                                  ("ears", "Hearing", ""), ("engine", "Local engine", ""))):
            tile = self._card(sysrow)
            tile.grid(row=0, column=col, sticky="nsew", padx=6)
            sysrow.columnconfigure(col, weight=1, uniform="tiles")
            top = ctk.CTkFrame(tile, fg_color="transparent")
            top.pack(fill="x", padx=14, pady=(12, 0))
            ctk.CTkLabel(top, text=icon, font=_font(14, family=ICONS), text_color=ACCENT).pack(side="left")
            self._label(top, title.upper(), 10, True, color=MUTED).pack(side="left", padx=8)
            value = self._label(tile, "…", 14, True)
            value.pack(fill="x", padx=14, pady=(4, 0))
            note = self._label(tile, "", 11, color=FAINT, wraplength=180)
            note.pack(fill="x", padx=14, pady=(0, 12))
            self.sys_tiles[key] = (value, note)

        actions = self._section(page, "Quick actions")
        row = ctk.CTkFrame(actions, fg_color="transparent")
        row.pack(fill="x", pady=(6, 0))
        if self.machine is not None:
            self._button(row, "Talk to TRON", self._talk, icon="", primary=True).pack(side="left", padx=(0, 8))
        self._button(row, "Open TRON browser", self._open_browser, icon="").pack(side="left", padx=(0, 8))
        self._button(row, "Test voice", self._test_voice, icon="").pack(side="left", padx=(0, 8))
        self._button(row, "Open conversation log", self._open_log, icon="").pack(side="left", padx=(0, 8))
        self._button(row, "Open TRON folder", self._open_folder, icon="").pack(side="left")
        self.log_message = self._message(row)

        stats = self._section(page, "Your TRON stats", "From the activity log and your dictations.")
        grid = ctk.CTkFrame(stats, fg_color="transparent")
        grid.pack(fill="x", pady=(4, 0))
        self.stat_cards = []
        for i in range(6):
            card = ctk.CTkFrame(grid, fg_color=BG, corner_radius=10, border_width=1, border_color=LINE)
            card.grid(row=i // 3, column=i % 3, sticky="nsew", padx=5, pady=5)
            grid.columnconfigure(i % 3, weight=1)
            views = (ctk.CTkLabel(card, text="", font=_font(26, "bold"), text_color=ACCENT, anchor="w"),
                     self._label(card, "", 13, True), self._label(card, "", 11, color=FAINT))
            views[0].pack(fill="x", padx=14, pady=(10, 0))
            views[1].pack(fill="x", padx=14)
            views[2].pack(fill="x", padx=14, pady=(0, 10))
            self.stat_cards.append(views)
        self.top_actions = self._label(stats, "", 12, color=MUTED, wraplength=720)
        self.top_actions.pack(fill="x", pady=(10, 0))

        recent = self._section(page, "Last conversation")
        self.recent_lines = self._label(recent, "", 12, color=TEXT, wraplength=720)
        self.recent_lines.pack(fill="x", pady=(4, 0))

        how = self._section(page, "How to use")
        self.how_to = self._label(how, "", 12, color=MUTED, wraplength=720)
        self.how_to.pack(fill="x", pady=(4, 0))
        return page

    def _open_browser(self):
        def go():
            import browser_intel
            message = browser_intel.open_browser()
            self._later(lambda: self.log_message.set(message))
        threading.Thread(target=go, daemon=True).start()

    def browser_status(self, stage, detail=""):
        """Browser task progress in the status bar: any thread."""
        words = {"inspecting": "Inspecting the page", "planning": "Planning", "executing": "Doing it",
                 "verifying": "Checking it worked", "recovering": "Trying another way", "completed": "Done",
                 "needs_clarification": "Needs your answer", "failed": "Couldn't do it"}
        text = words.get(stage, stage) + (f": {detail[:80]}" if detail else "")
        self._later(lambda: self.detail.configure(text=text))

    def _test_voice(self):
        def speak():
            try:
                import tts
                tts.VOICE = self._config().get("local_voice", tts.VOICE)
                tts.say("Hello sir. This is how I sound.")
            except Exception as exc:
                self._later(lambda: self.log_message.set(f"Couldn't speak: {exc}"))
        threading.Thread(target=speak, daemon=True).start()

    def _open_log(self):
        """Every request, what TRON did and what it said, as text: the material for training it further."""
        import os
        import convo_log
        path = convo_log.path()
        if not path.exists():
            self.log_message.set("Nothing logged yet. Talk to TRON and it will appear here.")
            return
        os.startfile(str(path))

    def _open_folder(self):
        import os
        os.startfile(str(config.app_dir()))

    def _load_stats(self):
        hour = time.localtime().tm_hour
        data = self._config()
        name = next((f["value"] for f in memory.all_facts() if f.get("key") == "name"), "")
        part = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
        self.greeting.configure(text=f"Good {part}{', ' + name if name else ''}.")
        self.subgreeting.configure(text=time.strftime("%A, %d %B"))
        self._load_system(data)

        today = time.strftime("%Y-%m-%d")
        items = dictation.history()
        words = sum(len(i["text"].split()) for i in items)
        words_today = sum(len(i["text"].split()) for i in items if i["time"].startswith(today))
        actions, clips = {}, 0
        try:
            for line in memory._LOG_PATH.read_text(encoding="utf-8").splitlines():
                try:
                    tool = json.loads(line).get("tool", "?")
                except ValueError:
                    continue
                actions[tool] = actions.get(tool, 0) + 1
                clips += tool == "clip_video"
        except OSError:
            pass
        saved = words / TYPING_WPM - words / SPEAKING_WPM
        saved_text = (f"{int(saved // 60)} h {int(saved % 60)} min" if saved >= 60
                      else f"{saved:.0f} min" if saved >= 1 else f"{saved * 60:.0f} sec")
        facts = memory.all_facts()
        cards = (
            (saved_text, "Time saved", f"dictating vs typing at {TYPING_WPM} wpm"),
            (f"{words:,}", "Words dictated", f"{words_today:,} today"),
            (f"{len(items):,}", "Dictations", "kept in Dictation history"),
            (f"{sum(actions.values()):,}", "Things done", "recent actions in the log"),
            (f"{len(facts):,}", "Things remembered", f"about {name}" if name else "see Memory & skills"),
            (f"{clips:,}", "Video clips", "saved in Videos\\TRON Clips"),
        )
        for views, values in zip(self.stat_cards, cards):
            for view, value in zip(views, values):
                view.configure(text=value)
        top = sorted(actions.items(), key=lambda kv: -kv[1])[:6]
        self.top_actions.configure(text=("Most used:  " + "   ·   ".join(f"{a.replace('_', ' ')} {n}" for a, n in top))
                                   if top else "Nothing yet. Say “hey tron” and ask for something.")
        last = self._conversations()[-1:] or [[]]
        self.recent_lines.configure(text="\n".join(last[0][-8:]) or "No conversations yet.")
        self.how_to.configure(text=HOW_TO.format(hotkey=data.get("hotkey", "ctrl+alt+t")))

    def _load_system(self, data):
        local = data.get("brain", "gemini") == "local"
        voice = data.get("local_voice", "david")
        voice_name = dict(LOCAL_VOICES).get(voice, voice)
        self.sys_tiles["brain"][0].configure(text=data.get("local_model", "qwen3.5:4b") if local else "Gemini Live")
        self.sys_tiles["brain"][1].configure(text="on this PC, no internet" if local else "online, needs a key")
        self.sys_tiles["voice"][0].configure(text=voice_name.split(" (")[0] if local else data.get("voice_name", "Orus"))
        self.sys_tiles["voice"][1].configure(text="generated on this PC" if local else "Gemini voice")
        self.sys_tiles["ears"][0].configure(text="Parakeet" if local else "Gemini")
        self.sys_tiles["ears"][1].configure(text=f"mic: {data.get('mic_device') or 'system default'}")
        self.sys_tiles["engine"][0].configure(text="checking…", text_color=MUTED)
        self.sys_tiles["engine"][1].configure(text="Ollama")

        def check():
            try:
                import requests
                import local_brain
                loaded = requests.get(f"{local_brain.OLLAMA}/api/ps", timeout=1.5).json().get("models", [])
                text, colour = ("running", GOOD) if loaded else ("idle, ready", ACCENT)
                note = f"{loaded[0]['name']} in GPU memory" if loaded else "loads on the next request"
            except Exception:
                text, colour, note = "not running", WARN if local else MUTED, "TRON starts it when needed"

            def show():
                value, note_view = self.sys_tiles["engine"]
                value.configure(text=text, text_color=colour)
                note_view.configure(text=note)
            self._later(show)
        threading.Thread(target=check, daemon=True).start()

    # ------------------------------------------------------------------ conversations
    def _build_conversations(self):
        page = self._page("Conversations", "Everything you asked, what TRON did and what it said, newest last. "
                                          "Saved on this PC as training material for TRON.")
        card = self._card(page)
        card.pack(fill="both", expand=True, padx=28, pady=8)
        self.convo_text = ctk.CTkTextbox(card, fg_color=CARD, text_color=TEXT, font=_font(12, family=MONO),
                                         height=420, wrap="word", corner_radius=10, border_width=0)
        self.convo_text.pack(fill="both", expand=True, padx=6, pady=6)
        box = self.convo_text._textbox
        box.tag_config("you", foreground=TEXT)
        box.tag_config("tron", foreground=ACCENT)
        box.tag_config("did", foreground=WARN)
        box.tag_config("head", foreground=FAINT)
        row = ctk.CTkFrame(page, fg_color="transparent")
        row.pack(fill="x", padx=28, pady=(0, 12))
        self._button(row, "Refresh", self._load_conversations, icon="").pack(side="left")
        self._button(row, "Open as text file", self._open_log, icon="").pack(side="left", padx=8)
        return page

    def _conversations(self):
        """The conversation log, split into conversations (lists of lines)."""
        import convo_log
        try:
            lines = convo_log.path().read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines[-600:]:
            if line.startswith("====="):
                out.append([])
            elif line.strip() and out:
                out[-1].append(line)
        return [c for c in out if c]

    def _load_conversations(self):
        box = self.convo_text
        box.configure(state="normal")
        box.delete("1.0", "end")
        convos = self._conversations()[-40:]
        if not convos:
            box.insert("end", "No conversations yet. Say “hey tron”.", "head")
        for convo in convos:
            box.insert("end", "─" * 60 + "\n", "head")
            for line in convo:
                tag = {"YOU:": "you", "TRON": "tron", "DID:": "did"}.get(line[:4], "head")
                box.insert("end", line + "\n", tag)
        box.configure(state="disabled")
        box.see("end")

    # ------------------------------------------------------------------ memory
    def _build_memory(self):
        page = self._page("Memory & skills", "What TRON remembers about you, and the routines it knows. "
                                             "Forget anything here, or just tell TRON to.")
        facts = self._section(page, "What TRON knows about you")
        self.memory_table = self._table(facts, (("kind", "Kind", 110), ("key", "About", 160),
                                                ("value", "What TRON knows", 360)), height=6)
        bottom = ctk.CTkFrame(facts, fg_color="transparent")
        bottom.pack(fill="x")
        self._button(bottom, "Forget", self._forget, icon="").pack(side="left")
        self.memory_message = self._message(bottom)
        self.facts = []

        # Skills: what TRON knows how to do, as opposed to what it knows about you.
        skills = self._section(page, "Skills", "Teach TRON a routine: a SKILL.md (or a folder or .zip with one, "
                                               "including skills made for Claude). TRON sees each skill's name and "
                                               "description and reads the rest when you ask for it. New skills work "
                                               "from the next conversation.")
        self.skills_table = self._table(skills, (("name", "Skill", 170), ("description", "When TRON uses it", 460)),
                                        height=5)
        row = ctk.CTkFrame(skills, fg_color="transparent")
        row.pack(fill="x")
        self._button(row, "Add skill file…", self._add_skill_file, icon="", primary=True).pack(side="left")
        self._button(row, "Add skill folder…", self._add_skill_folder, icon="").pack(side="left", padx=6)
        self._button(row, "Remove", self._remove_skill, icon="").pack(side="left")
        self._button(row, "Open skills folder", self._open_skills, icon="").pack(side="left", padx=6)
        self.skills_message = self._message(row)
        self.skill_rows = []
        return page

    def _load_skills(self):
        import skills
        skills.install_example()   # one example, so the format is never a mystery
        self.skill_rows = skills.all_skills()
        self.skills_table.delete(*self.skills_table.get_children())
        for skill in self.skill_rows:
            self.skills_table.insert("", "end", values=(skill["name"], skill["description"]))

    def _install_skill(self, source):
        import skills
        if not source:
            return
        try:
            name = skills.install(source)
            self.skills_message.set(f"Added {name}. TRON can use it from the next conversation.")
        except Exception as exc:
            self.skills_message.set(f"Couldn't add that: {exc}")
        self._load_skills()

    def _add_skill_file(self):
        from tkinter import filedialog
        self._install_skill(filedialog.askopenfilename(
            parent=self.win, title="Add a skill",
            filetypes=[("Skill", "*.md *.zip"), ("All files", "*.*")]))

    def _add_skill_folder(self):
        from tkinter import filedialog
        self._install_skill(filedialog.askdirectory(parent=self.win, title="Folder containing SKILL.md"))

    def _remove_skill(self):
        import skills
        sel = self.skills_table.selection()
        if not sel:
            self.skills_message.set("Pick a skill in the list first")
            return
        skill = self.skill_rows[self.skills_table.index(sel[0])]
        skills.remove(skill["id"])
        self.skills_message.set(f"Removed {skill['name']}")
        self._load_skills()

    def _open_skills(self):
        import os
        import skills
        skills.skills_dir().mkdir(parents=True, exist_ok=True)
        os.startfile(str(skills.skills_dir()))

    def _load_memory(self):
        self._load_skills()
        self.facts = memory.all_facts()
        self.memory_table.delete(*self.memory_table.get_children())
        for f in self.facts:
            self.memory_table.insert("", "end", values=(f.get("kind", ""), f.get("key", ""), f.get("value", "")))
        self.memory_message.set("" if self.facts else "Nothing yet. Tell TRON your name, or what you’re working on.")

    def _forget(self):
        sel = self.memory_table.selection()
        if not sel:
            self.memory_message.set("Pick something in the list first")
            return
        fact = self.facts[self.memory_table.index(sel[0])]
        memory.forget(fact.get("key", ""), fact.get("kind", ""))
        self._load_memory()
        self.memory_message.set(f"Forgot {fact.get('key')}")

    # ------------------------------------------------------------------ dictionary
    def _build_dictionary(self):
        page = self._page("Dictionary", "Words dictation gets wrong. Anything under “heard as” is swapped for the word.")
        inner = self._section(page, "Teach a word")
        add = ctk.CTkFrame(inner, fg_color="transparent")
        add.pack(fill="x", pady=(6, 0))
        self.new_word = self._entry(add, "Correct word", 180)
        self.new_alts = self._entry(add, "Heard as, comma separated", 300)
        self.search = self._entry(add, "Search", 160)
        self.new_word.pack(side="left")
        self.new_alts.pack(side="left", padx=6)
        self.new_alts.bind("<Return>", lambda _e: self._add_word())
        self._button(add, "Add word", self._add_word, icon="", primary=True).pack(side="left")
        self.search.pack(side="right")
        self.search.bind("<KeyRelease>", lambda _e: self._filter_vocab())
        self.vocab_table = self._table(inner, (("word", "Word", 170), ("heard", "Heard as (double-click to edit)", 440)))
        self.vocab_table.bind("<Double-1>", lambda e: self._edit_cell(self.vocab_table, e, self._vocab_edited))
        bottom = ctk.CTkFrame(inner, fg_color="transparent")
        bottom.pack(fill="x")
        self._button(bottom, "Remove", self._remove_word, icon="").pack(side="left")
        self.dict_message = self._message(bottom)
        self.vocab = [[w, list(alts)] for w, alts in dictation.read_vocab().items()]
        self._filter_vocab()
        return page

    def _filter_vocab(self):
        q = self._value(self.search).lower()
        self.visible = [i for i, (w, alts) in enumerate(self.vocab)
                        if not q or q in w.lower() or any(q in a.lower() for a in alts)]
        self.vocab_table.delete(*self.vocab_table.get_children())
        for i in self.visible:
            word, alts = self.vocab[i]
            self.vocab_table.insert("", "end", values=(word, ", ".join(alts)))

    def _save_vocab(self, message):
        try:
            dictation.save_vocab({w: alts for w, alts in self.vocab})
            self.dict_message.set(message)
        except Exception as exc:
            self.dict_message.set(f"Couldn't save: {exc}")
        self._filter_vocab()

    def _vocab_edited(self, row, column, value):
        value = value.strip()
        entry = self.vocab[self.visible[row]]
        if column == "word":
            if value:
                entry[0] = value
        else:
            entry[1] = [a.strip() for a in value.split(",") if a.strip()]
        self._save_vocab("Saved, used straight away")

    def _add_word(self):
        word = self._value(self.new_word)
        alts = [a.strip() for a in self._value(self.new_alts).split(",") if a.strip()]
        if not word or not alts:
            self.dict_message.set("Add the word and at least one way it gets misheard")
            return
        for entry in self.vocab:
            if entry[0].lower() == word.lower():   # already there, just add the new spellings
                entry[1] += [a for a in alts if a.lower() not in (x.lower() for x in entry[1])]
                break
        else:
            self.vocab.insert(0, [word, alts])
        for e in (self.new_word, self.new_alts, self.search):
            self._reset(e)
        self._save_vocab(f"Added {word}, used straight away")

    def _remove_word(self):
        sel = self.vocab_table.selection()
        if not sel:
            self.dict_message.set("Pick a word in the list first")
            return
        word = self.vocab.pop(self.visible[self.vocab_table.index(sel[0])])[0]
        self._save_vocab(f"Removed {word}")

    # ------------------------------------------------------------------ dictation history
    # ------------------------------------------------------------------ faces
    def _build_faces(self):
        page = self._page("People", "People TRON recognises by face and by voice, so it knows who it's talking "
                                    "to. Only fingerprints are kept on this PC, never photos or recordings. Enrol "
                                    "people only with their agreement.")
        top = ctk.CTkFrame(page, fg_color="transparent")
        top.pack(fill="x", padx=22, pady=4)
        left = self._card(top)
        left.pack(side="left", fill="both", expand=True, padx=6)
        inner = ctk.CTkFrame(left, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=18, pady=14)
        self._label(inner, "CAPTURE A FACE", 11, True, color=ACCENT).pack(fill="x")
        self._label(inner, "One person in front of the camera, facing it, in good light. Takes about 3 seconds.",
                    12, color=MUTED, wraplength=360).pack(fill="x", pady=(2, 8))
        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x")
        self.face_name = self._entry(row, "Their name", 200)
        self.face_name.pack(side="left")
        self.face_name.bind("<Return>", lambda _e: self._capture_face())
        self._button(row, "Capture face", self._capture_face, icon="\uE722", primary=True).pack(side="left", padx=8)
        self._label(inner, "RECOGNISE", 11, True, color=ACCENT).pack(fill="x", pady=(16, 0))
        row2 = ctk.CTkFrame(inner, fg_color="transparent")
        row2.pack(fill="x", pady=(6, 0))
        self._button(row2, "Who's here?", self._recognise_faces, icon="\uE8D4").pack(side="left")
        self._button(row2, "Forget selected", self._forget_face, icon="\uE74D").pack(side="left", padx=8)
        self._label(inner, "VOICE", 11, True, color=ACCENT).pack(fill="x", pady=(16, 0))
        self._label(inner, "After pressing Capture voice, talk normally for about 8 seconds.", 12, color=MUTED,
                    wraplength=360).pack(fill="x", pady=(2, 6))
        row3 = ctk.CTkFrame(inner, fg_color="transparent")
        row3.pack(fill="x")
        self._button(row3, "Capture voice", self._capture_voice, icon="\uE720", primary=True).pack(side="left")
        self._button(row3, "Whose voice?", self._recognise_voice, icon="\uE767").pack(side="left", padx=8)
        self.face_message = tk.StringVar()
        ctk.CTkLabel(inner, textvariable=self.face_message, font=_font(12), text_color=TEXT, anchor="w",
                     justify="left", wraplength=360).pack(fill="x", pady=(10, 0))
        self.face_table = self._table(inner, (("name", "Person", 140), ("looks", "Face", 80), ("voice", "Voice", 80)),
                                      height=5)

        right = self._card(top)
        right.pack(side="left", padx=6)
        self._label(right, "CAMERA", 11, True, color=ACCENT).pack(fill="x", padx=18, pady=(14, 4))
        self.face_preview = ctk.CTkLabel(right, text="Press Capture or Who's here?", width=400, height=300,
                                         fg_color=BG, corner_radius=10, text_color=FAINT)
        self.face_preview.pack(padx=18, pady=(0, 18))
        return page

    def _camera_cfg(self):
        from types import SimpleNamespace
        return SimpleNamespace(camera_enabled=bool(self._config().get("camera_enabled")))

    def _load_faces(self):
        import faces
        import voices
        people, heard = faces.gallery(), voices.gallery()
        self.face_table.delete(*self.face_table.get_children())
        for name in sorted(set(people) | set(heard), key=str.lower):
            self.face_table.insert("", "end", values=(name, "yes" if name in people else "-",
                                                      "yes" if name in heard else "-"))
        if not people:
            self.face_message.set("Nobody yet. Type your name and press Capture face.")

    def _show_frame(self, bgr):
        import cv2
        from PIL import Image
        image = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        image.thumbnail((400, 300))
        self._face_img = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
        self.face_preview.configure(image=self._face_img, text="")

    def _face_job(self, busy_text, work):
        """Camera work on a thread (it takes a couple of seconds); results come back on the GUI thread."""
        self.face_message.set(busy_text)

        def run():
            try:
                message, frame = work()
            except Exception as exc:
                message, frame = f"Couldn't: {exc}", None

            def done():
                self._load_faces()               # first, or its "Nobody yet" would replace the result
                self.face_message.set(message)
                if frame is not None:
                    self._show_frame(frame)
            self._later(done)
        threading.Thread(target=run, daemon=True).start()

    def _capture_face(self):
        import faces
        name = self._value(self.face_name)
        if not name:
            self.face_message.set("Type the person's name first.")
            return
        cfg = self._camera_cfg()

        def work():
            message = faces.enroll_face({"name": name}, cfg)
            try:
                frame, _found = faces.look(cfg)
            except Exception:
                frame = None
            return message[0].upper() + message[1:], frame
        self._face_job(f"Looking at {name}... hold still for a moment.", work)

    def _recognise_faces(self):
        import faces
        cfg = self._camera_cfg()

        def work():
            frame, found = faces.look(cfg)
            if not found:
                return "I can't see anyone in front of the camera.", frame
            parts = [f"{n} ({s:.2f})" if n else "someone I don't know" for n, s, _b in found]
            return "I can see " + ", ".join(parts) + ".", frame
        self._face_job("Looking...", work)

    def _forget_face(self):
        import faces
        sel = self.face_table.selection()
        if not sel:
            self.face_message.set("Pick someone in the list first.")
            return
        import voices
        name = str(self.face_table.item(sel[0])["values"][0])
        said = [faces.forget_face({"name": name}), voices.forget_voice({"name": name})]
        self._load_faces()
        self.face_message.set(" ".join(s[0].upper() + s[1:] for s in said if s.startswith("forgot")) or said[0])

    def _capture_voice(self):
        import voices
        name = self._value(self.face_name)
        if not name:
            self.face_message.set("Type the person's name first.")
            return
        mic = self._config().get("mic_device")

        def work():
            message = voices.enroll_voice({"name": name}, type("C", (), {"mic_device": mic})())
            return message[0].upper() + message[1:], None
        self._face_job(f"Listening to {name}... talk normally for about 8 seconds.", work)

    def _recognise_voice(self):
        import voices
        mic = self._config().get("mic_device")

        def work():
            audio = voices.record(4.0, mic)
            if len(audio) < voices.SAMPLE_RATE * 1.5:
                return "I didn't hear enough speech. Talk for a few seconds.", None
            name, sim = voices.identify(voices.embed(audio))
            return (f"That's {name}'s voice (match {sim:.2f})." if name
                    else f"I don't recognise that voice (closest match {sim:.2f})."), None
        self._face_job("Listening... say something for a few seconds.", work)

    def _build_history(self):
        page = self._page("Dictation history", "Everything you’ve dictated, newest first. Kept on this PC only.")
        inner = self._section(page, "Dictations")
        self.hist_table = self._table(inner, (("time", "When", 140), ("text", "Text", 480)), height=12)
        bottom = ctk.CTkFrame(inner, fg_color="transparent")
        bottom.pack(fill="x")
        self._button(bottom, "Copy", self._copy_history, icon="").pack(side="left")
        self.hist_message = self._message(bottom)
        self.history = []
        return page

    def _load_history(self):
        self.history = dictation.history()
        self.hist_table.delete(*self.hist_table.get_children())
        for item in self.history:
            self.hist_table.insert("", "end", values=(item["time"], item["text"].replace("\n", " ")))
        self.hist_message.set("" if self.history else "Nothing yet. Say “hey tron, take dictation” to start.")

    def _copy_history(self):
        sel = self.hist_table.selection()
        if not sel:
            self.hist_message.set("Pick one in the list first")
            return
        self.win.clipboard_clear()
        self.win.clipboard_append(self.history[self.hist_table.index(sel[0])]["text"])
        self.hist_message.set("Copied")

    # ------------------------------------------------------------------ privacy
    def _build_privacy(self):
        page = self._page("Privacy", "What TRON hears is handled on this PC first. Only this ever leaves it.")
        for title, body in PRIVACY:
            inner = self._section(page, title)
            self._label(inner, body, 12, color=MUTED, wraplength=720).pack(fill="x", pady=(4, 0))
        return page

    # ------------------------------------------------------------------ settings
    def _row(self, parent, title, note=""):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=6)
        row.columnconfigure(0, weight=1)
        left = ctk.CTkFrame(row, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w")
        self._label(left, title, 13, True).pack(fill="x")
        if note:
            self._label(left, note, 11, color=FAINT).pack(fill="x")
        right = ctk.CTkFrame(row, fg_color="transparent")
        right.grid(row=0, column=1, sticky="e")
        return right

    def _build_settings(self):
        page = self._page("Settings", "Saved to config.json. Most changes take effect when TRON restarts: "
                                      "save, then use the Restart button at the top.")
        self.settings_vars = {}

        def combo(parent, key, title, note="", width=320):
            box = ctk.CTkComboBox(self._row(parent, title, note), state="readonly", width=width, height=34,
                                  corner_radius=8, fg_color=BG, border_color=LINE, button_color=LINE,
                                  button_hover_color=ACCENT_DIM, dropdown_fg_color=CARD, dropdown_hover_color=CARD_HI,
                                  text_color=TEXT, dropdown_text_color=TEXT, values=[])
            box.pack()
            self.settings_vars[key] = box
            return box

        brain = self._section(page, "Brain & voice")
        combo(brain, "brain", "Brain", "Local runs entirely on this PC: no internet, no Gemini")
        self.settings_vars["local_brain_enabled"] = tk.BooleanVar(value=True)
        ctk.CTkSwitch(self._row(brain, "Local brain", "Off: the local model (Ollama) is never started and its "
                                                      "memory is freed. Learning and the update watcher need it."),
                      text="", variable=self.settings_vars["local_brain_enabled"], progress_color=ACCENT,
                      button_color=TEXT, button_hover_color="#ffffff", fg_color=LINE).pack()
        combo(brain, "local_model", "Local model", "Any model you've downloaded in Ollama")
        combo(brain, "local_voice", "Local voice", "Windows voices start instantly; Kokoro sounds more natural")
        combo(brain, "voice_name", "Gemini voice", "Used in Gemini mode", width=200)
        combo(brain, "active_assistant", "Assistant", "Each has its own voice and persona", width=200)

        audio = self._section(page, "Audio")
        combo(audio, "mic_device", "Microphone", "Used for the wake word, conversations and dictation")
        combo(audio, "speaker_device", "Speaker", "Where TRON’s voice comes out")

        wake = self._section(page, "Wake & look")
        combo(wake, "wake_mode", "Wake", "The hotkey always works too", width=240)
        entry = self._entry(self._row(wake, "Hotkey", "e.g. ctrl+alt+t"), "ctrl+alt+t", 240)
        entry.pack()
        self.settings_vars["hotkey"] = entry
        combo(wake, "ui_model", "On-screen widget")

        perms = self._section(page, "Permissions")
        for key, text in (("screen_enabled", "Let TRON look at the screen (needed for “clip the last 30 seconds”)"),
                          ("camera_enabled", "Let TRON use the webcam"),
                          ("autostart", "Start TRON when I sign in to Windows"),
                          ("memory_enabled", "Let TRON learn lasting facts about me after each conversation"),
                          ("brain_debug", "Developer: write each decision into Conversations")):
            var = tk.BooleanVar()
            ctk.CTkSwitch(perms, text=text, variable=var, font=_font(13), text_color=TEXT, progress_color=ACCENT,
                          button_color=TEXT, button_hover_color="#ffffff", fg_color=LINE).pack(anchor="w", pady=5)
            self.settings_vars[key] = var

        bottom = ctk.CTkFrame(page, fg_color="transparent")
        bottom.pack(fill="x", padx=28, pady=(8, 20))
        self._button(bottom, "Save settings", self._save_settings, icon="", primary=True).pack(side="right")
        self.settings_message = self._message(bottom)
        return page

    def _devices(self):
        try:
            import audio_io
            return [n for _i, n, _c in audio_io.input_devices()], [n for _i, n, _c in audio_io.output_devices()]
        except Exception:
            return [], []

    @staticmethod
    def _windows_output() -> str:
        try:
            from pycaw.pycaw import AudioUtilities
            return AudioUtilities.GetSpeakers().FriendlyName or "unknown"
        except Exception:
            return "unknown"

    @staticmethod
    def _ollama_models() -> list:
        try:
            import requests
            import local_brain
            tags = requests.get(f"{local_brain.OLLAMA}/api/tags", timeout=1.5).json().get("models", [])
            return sorted(m["name"] for m in tags)
        except Exception:
            return []

    def _load_settings(self):
        data = self._config()
        mics, speakers = self._devices()
        assistants = data.get("assistants") or config.DEFAULT_ASSISTANTS
        self._choices = {
            "brain": [("local", "Local (on this PC)"), ("gemini", "Gemini Live (online)")],
            "local_model": [(m, m) for m in self._ollama_models()],
            "local_voice": list(LOCAL_VOICES),
            "mic_device": [("", "System default")] + [(n, n) for n in dict.fromkeys(mics)],
            "speaker_device": [("", f"Follow Windows (now: {self._windows_output()})")]
                              + [(n, n) for n in dict.fromkeys(speakers)],
            "voice_name": [(v, v) for v in VOICES],
            "active_assistant": [(a["id"], a["name"]) for a in assistants],
            "wake_mode": [("openwakeword", "Wake word (“hey tron”)"), ("hotkey", "Hotkey only")],
            "ui_model": list(UI_MODELS),
        }
        current = {**data, "active_assistant": config.active_assistant(data).get("id"),
                   "ui_model": data.get("ui_model", "halo-ring"), "brain": data.get("brain", "gemini"),
                   "local_model": data.get("local_model", "qwen3.5:4b"),
                   "local_voice": data.get("local_voice", "david")}
        for key, options in self._choices.items():
            box = self.settings_vars[key]
            value = current.get(key) or ""
            labels = [label for v, label in options if v == value]
            if not labels and value:   # a device name that's partial or unplugged: keep it, don't lose it
                options.append((value, value))
                labels = [value]
            box.configure(values=[label for _v, label in options])
            box.set(labels[0] if labels else options[0][1] if options else "")
        self.settings_vars["hotkey"].delete(0, "end")
        self.settings_vars["hotkey"].insert(0, data.get("hotkey", "ctrl+alt+t"))
        self.settings_vars["screen_enabled"].set(bool(data.get("screen_enabled")))
        self.settings_vars["camera_enabled"].set(bool(data.get("camera_enabled")))
        self.settings_vars["memory_enabled"].set(bool(data.get("memory_enabled", True)))
        self.settings_vars["brain_debug"].set(bool(data.get("brain_debug", False)))
        self.settings_vars["local_brain_enabled"].set(data.get("local_brain_enabled", True) is not False)
        try:
            self.settings_vars["autostart"].set(autostart.is_enabled())
        except Exception:
            self.settings_vars["autostart"].set(False)
        self._loaded = self._form_values()

    def _form_values(self) -> dict:
        values = {}
        for key, options in self._choices.items():
            label = self.settings_vars[key].get()
            value = next((v for v, lab in options if lab == label), "")
            values[key] = (value or None) if key in ("mic_device", "speaker_device") else value
        values["hotkey"] = self.settings_vars["hotkey"].get().strip()
        for key in ("screen_enabled", "camera_enabled", "memory_enabled", "brain_debug", "local_brain_enabled"):
            values[key] = bool(self.settings_vars[key].get())
        return values

    def _save_settings(self):
        # Only what was changed. Writing every field would, for one, switch an untouched
        # assistant profile on, and its voice would then override the Voice you picked.
        values = self._form_values()
        patch = {k: v for k, v in values.items() if v != self._loaded.get(k) and not (k == "hotkey" and not v)}
        if patch.get("local_brain_enabled") is False and values.get("brain") == "local":
            self.settings_message.set("Switch Brain to Gemini first: the local brain is what answers in Local mode.")
            return
        try:
            config.update_config_file(patch)
            (autostart.enable if self.settings_vars["autostart"].get() else autostart.disable)()
            if patch.get("local_brain_enabled") is False:
                import local_brain
                threading.Thread(target=local_brain.unload, args=(values.get("local_model") or
                                                                   local_brain.DEFAULT_MODEL,), daemon=True).start()
            self._loaded = values
            self.settings_message.set(f"Saved. Click {self.restart_label} (top right) to use them." if patch else "Saved.")
        except Exception as exc:
            self.settings_message.set(f"Couldn't save: {exc}")
        self.hint.configure(text=self._ready_text())

    # ------------------------------------------------------------------ keys
    def _build_keys(self):
        page = self._page("Keys", "Saved in config.json next to TRON. Existing values stay hidden; leave a box "
                                  "empty to keep what’s there. Local mode needs none of these.")
        inner = self._section(page, "Services")
        self.key_fields = {}
        for key, title, note, secret in (
                ("gemini_api_key", "Gemini API key", "Gemini mode’s voice and brain. Free at aistudio.google.com", True),
                ("openrouter_api_key", "OpenRouter API key", "Used for dictation, with Gemini as the backup", True),
                ("smtp_host", "Email server", "e.g. smtp.gmail.com, for sending email", False),
                ("smtp_user", "Email address", "The account TRON sends from", False),
                ("smtp_app_password", "Email app password", "A Gmail app password, not your real one", True)):
            right = self._row(inner, title, note)
            field = self._entry(right, "", 320, secret)
            field.pack()
            status = self._label(right, "", 10, color=FAINT)
            status.pack(fill="x")
            self.key_fields[key] = (field, status, secret)
        bottom = ctk.CTkFrame(page, fg_color="transparent")
        bottom.pack(fill="x", padx=28, pady=(8, 20))
        self._button(bottom, "Save keys", self._save_keys, icon="", primary=True).pack(side="right")
        self.keys_message = self._label(bottom, "", 11, color=BAD)
        self.keys_message.pack(side="left")
        self._load_keys()
        return page

    def _load_keys(self):
        data = self._config()
        for key, (field, status, secret) in self.key_fields.items():
            have = bool(str(data.get(key, "")).strip()) and "YOUR_" not in str(data.get(key, ""))
            field.delete(0, "end")
            if not secret and have:
                field.insert(0, data[key])
            status.configure(text="● Already configured" if have else "○ Not set",
                             text_color=GOOD if have else FAINT)

    def _save_keys(self):
        patch = {}
        for key, (field, _status, secret) in self.key_fields.items():
            value = field.get().strip()
            if value or not secret:   # an empty secret box means "keep the stored one"
                patch[key] = value
        try:
            config.update_config_file(patch)
            self._load_keys()
            self.keys_message.configure(text_color=MUTED, text=f"Saved. Click {self.restart_label} (top right) to use a new key.")
        except Exception as exc:
            self.keys_message.configure(text_color=BAD, text=f"Couldn't save: {exc}")


def _mix(a: str, b: str, t: float) -> str:
    """Colour t of the way from a to b (tk has no alpha, so glows are blended by hand)."""
    ca, cb = (int(a[i:i + 2], 16) for i in (1, 3, 5)), (int(b[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))
