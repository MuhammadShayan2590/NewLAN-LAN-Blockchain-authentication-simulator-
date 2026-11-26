"""NewLAN shared look: the "Midnight Aurora" theme, an animation clock, and the custom widgets.

Everything visual that more than one page uses lives here: colours, buttons that fade on hover,
sidebar items, status cards with a pulsing light, toggle switches, toast notifications, the animated
network on the Home page, the "how it works" pipeline, stat tiles and a live bar chart.
"""
import math
import random
import time
import tkinter as tk

# ------------------------------------------------------------------ palette
BG = "#0A0F1F"            # window background
SURFACE = "#111A2F"       # cards and bars
SURFACE2 = "#18233F"      # raised: inputs, hover, headers
BORDER = "#25345A"
TEXT = "#E8EDF8"
MUTED = "#94A1BE"
DIM = "#5C6B8C"
OFF = DIM
ACCENT = "#22D3EE"        # cyan: primary
ACCENT_HI = "#7CE9FA"
ACCENT_LO = "#0D3647"     # cyan tint for selections
ON_ACCENT = "#04202A"     # text on a cyan fill
VIOLET = "#8B5CF6"
VIOLET_LO = "#2B2150"
OK = "#34D399"
OK_LO = "#0E3A30"
WARN = "#FBBF24"
WARN_LO = "#3B2F0E"
ERR = "#F87171"
ERR_LO = "#3A1C27"
CONSOLE = "#0C1326"       # terminal-style panels
FONT = "Segoe UI"
MONO = "Consolas"


# ------------------------------------------------------------------ colour and motion helpers
def _rgb(c):
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def mix(a, b, t):
    """Blend colour a towards colour b by t (0..1). Used for fades, glows and 'transparency'."""
    t = max(0.0, min(1.0, t))
    ra, rb = _rgb(a), _rgb(b)
    return "#%02x%02x%02x" % tuple(round(ra[i] + (rb[i] - ra[i]) * t) for i in range(3))


def ease(p):
    p = max(0.0, min(1.0, p))
    return p * p * (3 - 2 * p)


def wave(t, period=1.6):
    """Smooth 0..1..0 oscillation."""
    return 0.5 - 0.5 * math.cos(2 * math.pi * (t % period) / period)


def _bg_of(widget, default):
    try:
        return widget["bg"]
    except Exception:
        return default


def fade_to(w, steps=6, ms=120, **targets):
    """Fade a widget's colour options (bg=..., fg=..., highlightbackground=...) to new values."""
    cur = getattr(w, "_cur", None) or {}
    start = {k: cur.get(k, v) for k, v in targets.items()}
    tok = getattr(w, "_fade_tok", 0) + 1
    w._fade_tok = tok

    def step(i):
        if getattr(w, "_fade_tok", 0) != tok:
            return
        vals = {k: mix(start[k], targets[k], ease(i / steps)) for k in targets}
        try:
            w.config(**vals)
        except Exception:
            return
        w._cur = {**(getattr(w, "_cur", None) or {}), **vals}
        if i < steps:
            w.after(max(8, ms // steps), step, i + 1)
    step(1)


def set_colors(w, **vals):
    """Set colours immediately (and remember them as the starting point for the next fade)."""
    w._fade_tok = getattr(w, "_fade_tok", 0) + 1
    w.config(**vals)
    w._cur = {**(getattr(w, "_cur", None) or {}), **vals}


class Clock:
    """One shared animation clock. Widgets register a callback for a page; it only runs while that page shows."""

    def __init__(self):
        self.root = None
        self.cbs = []
        self.page = None
        self.errors = []
        self.interval = 40
        self.n = 0

    def add(self, page, fn, every=1):
        self.cbs.append([page, fn, every])

    def set_page(self, page):
        self.page = page

    def attach(self, root):
        if self.root is None:
            self.root = root
            root.after(self.interval, self._loop)

    def _loop(self):
        self.n += 1
        t = time.time()
        for page, fn, every in list(self.cbs):
            if (page is None or page == self.page) and self.n % every == 0:
                try:
                    fn(t)
                except Exception as e:        # an animation must never be able to break the app
                    if len(self.errors) < 50:
                        self.errors.append(repr(e))
        self.root.after(self.interval, self._loop)


clock = Clock()


# ------------------------------------------------------------------ drawing helpers
def round_rect(c, x1, y1, x2, y2, r=12, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
           x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def glow_rect(c, x1, y1, x2, y2, r, color, bg=BG, layers=3, **kw):
    """A soft glow: a few outlines around the shape that fade into the background."""
    for i in range(layers, 0, -1):
        round_rect(c, x1 - i * 2, y1 - i * 2, x2 + i * 2, y2 + i * 2, r + i * 2, fill="",
                   outline=mix(bg, color, 0.55 - i * 0.14), width=2)


def card(parent, pad=14, **kw):
    return tk.Frame(parent, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER, padx=pad, pady=pad, **kw)


def make_entry(parent, var, **kw):
    return tk.Entry(parent, textvariable=var, relief="flat", bd=0, bg=SURFACE2, fg=TEXT, insertbackground=ACCENT,
                    disabledbackground=SURFACE, disabledforeground=DIM, selectbackground=ACCENT_LO, selectforeground=TEXT,
                    highlightthickness=2, highlightbackground=BORDER, highlightcolor=ACCENT, font=(FONT, 11), **kw)


class GradientBar(tk.Canvas):
    def __init__(self, parent, c1=ACCENT, c2=VIOLET, height=3, width=None):
        super().__init__(parent, height=height, bg=BG, highlightthickness=0, **({"width": width} if width else {}))
        self.c1, self.c2, self.fixed = c1, c2, width
        self.bind("<Configure>", lambda e: self._draw())
        if width:
            self._draw()

    def _draw(self):
        self.delete("all")
        w = self.fixed or max(self.winfo_width(), 40)
        step = 3
        for x in range(0, w, step):
            self.create_line(x, 0, x, 40, fill=mix(self.c1, self.c2, x / max(w, 1)), width=step)


def page_header(parent, title, subtitle):
    box = tk.Frame(parent, bg=BG)
    box.pack(fill="x", padx=36, pady=(26, 14))
    tk.Label(box, text=title, font=(FONT, 22, "bold"), fg=TEXT, bg=BG).pack(anchor="w")
    tk.Label(box, text=subtitle, font=(FONT, 10), fg=MUTED, bg=BG, wraplength=820, justify="left").pack(anchor="w", pady=(2, 0))
    GradientBar(box, ACCENT, VIOLET, height=3, width=56).pack(anchor="w", pady=(10, 0))
    return box


def chrome_bar(parent, title, bg=SURFACE2):
    """A little window title bar (three dots and a file-name style title) for terminal-like panels."""
    bar = tk.Frame(parent, bg=bg)
    dots = tk.Canvas(bar, width=56, height=14, bg=bg, highlightthickness=0)
    dots.pack(side="left", padx=(12, 4), pady=9)
    for i, col in enumerate((ERR, WARN, OK)):
        dots.create_oval(2 + i * 18, 2, 12 + i * 18, 12, fill=col, outline="")
    lbl = tk.Label(bar, text=title, font=(MONO, 9), fg=MUTED, bg=bg)
    lbl.pack(side="left")
    return bar, lbl


# ------------------------------------------------------------------ buttons and navigation
class Btn(tk.Label):
    """Flat button that fades on hover and dips when pressed. style: primary | outline | danger."""
    STYLES = {
        "primary": dict(bg=ACCENT, fg=ON_ACCENT, hbg=ACCENT_HI, hfg=ON_ACCENT, border=ACCENT, hborder=ACCENT_HI),
        "outline": dict(bg=SURFACE, fg=ACCENT, hbg=ACCENT, hfg=ON_ACCENT, border=ACCENT, hborder=ACCENT),
        "danger": dict(bg=SURFACE, fg=ERR, hbg=ERR, hfg="#2A0B12", border=ERR, hborder=ERR),
    }
    SIZES = {"sm": (12, 5, 9), "md": (18, 9, 10), "lg": (34, 14, 13)}

    def __init__(self, parent, text, command=None, style="primary", size="md", **kw):
        s = dict(self.STYLES[style])
        if style != "primary":
            s["bg"] = _bg_of(parent, SURFACE)
        px, py, fs = self.SIZES[size]
        super().__init__(parent, text=text, bg=s["bg"], fg=s["fg"], font=(FONT, fs, "bold"), padx=px, pady=py,
                         cursor="hand2", highlightthickness=1, highlightbackground=s["border"], bd=0, **kw)
        self.s, self.command, self.enabled, self.hover, self.down = s, command, True, False, False
        self._cur = {"bg": s["bg"], "fg": s["fg"], "highlightbackground": s["border"]}
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False, down=False))
        self.bind("<Button-1>", lambda e: self._press())
        self.bind("<ButtonRelease-1>", lambda e: self._set(down=False))

    def _target(self):
        s = self.s
        if not self.enabled:
            return dict(bg=SURFACE, fg=DIM, highlightbackground=BORDER)
        if self.down:
            return dict(bg=mix(s["hbg"], BG, 0.3), fg=s["hfg"], highlightbackground=s["hborder"])
        if self.hover:
            return dict(bg=s["hbg"], fg=s["hfg"], highlightbackground=s["hborder"])
        return dict(bg=s["bg"], fg=s["fg"], highlightbackground=s["border"])

    def _set(self, **state):
        for k, v in state.items():
            setattr(self, k, v)
        fade_to(self, steps=5, ms=100, **self._target())

    def _press(self):
        if self.enabled:
            self._set(down=True)
            if self.command:
                self.command()

    def set_enabled(self, enabled):
        self.enabled = enabled
        self.config(cursor="hand2" if enabled else "arrow")
        set_colors(self, **self._target())


class NavItem(tk.Frame):
    """Sidebar entry: quiet normally, lights up on hover, soft cyan with a bright bar when it is the current page."""

    def __init__(self, parent, icon, text, command):
        super().__init__(parent, bg=SURFACE, cursor="hand2")
        self.command, self.active, self.hover = command, False, False
        self.bar = tk.Frame(self, width=4, bg=SURFACE)
        self.bar.pack(side="left", fill="y")
        self.label = tk.Label(self, text=f"{icon}   {text}", anchor="w", bg=SURFACE, fg=MUTED,
                              font=(FONT, 11), padx=18, pady=11, cursor="hand2")
        self.label.pack(side="left", fill="x", expand=True)
        self._cur = {"bg": SURFACE}
        self.label._cur = {"bg": SURFACE, "fg": MUTED}
        self.bar._cur = {"bg": SURFACE}
        for w in (self, self.label, self.bar):
            w.bind("<Enter>", lambda e: self._h(True))
            w.bind("<Leave>", lambda e: self._h(False))
            w.bind("<Button-1>", lambda e: self.command())

    def _h(self, value):
        self.hover = value
        self._paint(True)

    def set_active(self, value):
        self.active = value
        self._paint(False)

    def _paint(self, animate):
        if self.hover:
            bg, fg, bar, font = SURFACE2, ACCENT_HI, VIOLET, (FONT, 11, "bold")
        elif self.active:
            bg, fg, bar, font = ACCENT_LO, ACCENT, ACCENT, (FONT, 11, "bold")
        else:
            bg, fg, bar, font = SURFACE, MUTED, SURFACE, (FONT, 11)
        self.label.config(font=font)
        if animate:
            fade_to(self, steps=5, ms=100, bg=bg)
            fade_to(self.label, steps=5, ms=100, bg=bg, fg=fg)
            fade_to(self.bar, steps=5, ms=100, bg=bar)
        else:
            set_colors(self, bg=bg)
            set_colors(self.label, bg=bg, fg=fg)
            set_colors(self.bar, bg=bar)


class SegTab(tk.Label):
    """Sub-section tab: quiet pill, lights up on hover, filled soft cyan when it is the current one."""

    def __init__(self, parent, text, command):
        super().__init__(parent, text=text, font=(FONT, 10, "bold"), padx=20, pady=8, cursor="hand2",
                         highlightthickness=1, bd=0)
        self.command, self.active, self.hover = command, False, False
        self.bind("<Enter>", lambda e: self._h(True))
        self.bind("<Leave>", lambda e: self._h(False))
        self.bind("<Button-1>", lambda e: self.command())
        self._cur = {}
        self._paint(False)

    def _h(self, value):
        self.hover = value
        self._paint(True)

    def set_active(self, value):
        self.active = value
        self._paint(False)

    def _paint(self, animate):
        if self.active:
            vals = dict(bg=ACCENT_LO, fg=ACCENT, highlightbackground=ACCENT)
        elif self.hover:
            vals = dict(bg=SURFACE2, fg=ACCENT_HI, highlightbackground=ACCENT)
        else:
            vals = dict(bg=BG, fg=MUTED, highlightbackground=BORDER)
        if animate and self._cur:
            fade_to(self, steps=5, ms=100, **vals)
        else:
            set_colors(self, **vals)


class Switch(tk.Canvas):
    """Toggle switch bound to a BooleanVar; the knob slides."""

    def __init__(self, parent, variable, command=None, base=SURFACE):
        super().__init__(parent, width=46, height=24, bg=base, highlightthickness=0, cursor="hand2")
        self.var, self.command = variable, command
        self.pos = 1.0 if variable.get() else 0.0
        self.bind("<Button-1>", lambda e: self.toggle())
        self._draw()

    def _draw(self):
        self.delete("all")
        track = mix(BORDER, ACCENT, self.pos)
        self.create_oval(1, 2, 23, 22, fill=track, outline=track)
        self.create_oval(23, 2, 45, 22, fill=track, outline=track)
        self.create_rectangle(12, 2, 34, 23, fill=track, outline=track)
        x = 13 + 22 * self.pos
        self.create_oval(x - 9, 3, x + 9, 21, fill=TEXT, outline="")

    def toggle(self):
        self.var.set(not self.var.get())
        target = 1.0 if self.var.get() else 0.0
        start, steps = self.pos, 6

        def step(i):
            self.pos = start + (target - start) * ease(i / steps)
            self._draw()
            if i < steps:
                self.after(16, step, i + 1)
        step(1)
        if self.command:
            self.command()


class StatusCard(tk.Frame):
    """Service status with a light that pulses while the service is running."""

    def __init__(self, parent, title):
        super().__init__(parent, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER, padx=14, pady=12)
        tk.Label(self, text=title.upper(), font=(FONT, 8, "bold"), fg=MUTED, bg=SURFACE).pack(anchor="w")
        row = tk.Frame(self, bg=SURFACE)
        row.pack(anchor="w", fill="x", pady=(6, 0))
        self.light = tk.Canvas(row, width=18, height=18, bg=SURFACE, highlightthickness=0)
        self.light.pack(side="left", anchor="n", pady=2)
        self.text = tk.Label(row, text="Checking...", fg=TEXT, bg=SURFACE, font=(FONT, 10), wraplength=165,
                             justify="left", anchor="w")
        self.text.pack(side="left", padx=(8, 0), fill="x", expand=True)
        self.color = DIM
        self._draw(0.0)
        clock.add("home", self.tick, every=2)

    def set(self, color, text):
        self.color = color
        self.text.config(text=text)
        self._draw(0.0)

    def tick(self, t):
        if self.color in (OK, WARN):
            self._draw(wave(t, 2.0))

    def _draw(self, p):
        c = self.light
        c.delete("all")
        if self.color in (OK, WARN):
            r = 5 + 4 * p
            c.create_oval(9 - r, 9 - r, 9 + r, 9 + r, outline=mix(self.color, SURFACE, 0.35 + 0.65 * p), width=2)
        c.create_oval(4, 4, 14, 14, fill=self.color, outline=mix(self.color, SURFACE, 0.5))


class StatTile(tk.Frame):
    """A big number that counts up to its new value."""

    def __init__(self, parent, title, color=ACCENT, suffix=""):
        super().__init__(parent, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER, padx=14, pady=10)
        tk.Label(self, text=title.upper(), font=(FONT, 8, "bold"), fg=MUTED, bg=SURFACE).pack(anchor="w")
        self.value = tk.Label(self, text="0" + suffix, font=(FONT, 22, "bold"), fg=color, bg=SURFACE)
        self.value.pack(anchor="w")
        self.suffix, self.shown, self.target, self.decimals, self.tok = suffix, 0.0, 0.0, 0, 0

    def set(self, n, decimals=0, color=None):
        if color:
            self.value.config(fg=color)
        self.decimals, self.target = decimals, float(n)
        self.tok += 1
        tok, start, steps = self.tok, self.shown, 8

        def step(i):
            if tok != self.tok:
                return
            self.shown = start + (self.target - start) * ease(i / steps)
            self.value.config(text=f"{self.shown:.{self.decimals}f}{self.suffix}")
            if i < steps:
                self.after(30, step, i + 1)
        step(1)


class Sparkline(tk.Canvas):
    """Small live bar chart."""

    def __init__(self, parent, height=64, bg=SURFACE):
        super().__init__(parent, height=height, bg=bg, highlightthickness=0)
        self.bgc, self.values, self.caption = bg, [], ""
        self.bind("<Configure>", lambda e: self.draw())

    def set(self, values, caption=""):
        self.values, self.caption = list(values), caption
        self.draw()

    def draw(self):
        c = self
        c.delete("all")
        W, H = max(c.winfo_width(), 120), max(c.winfo_height(), 40)
        n = len(self.values)
        top = max(self.values) if self.values else 0
        base = H - 16
        c.create_line(0, base, W, base, fill=BORDER)
        if n:
            bw = W / n
            for i, v in enumerate(self.values):
                h = 0 if top == 0 else (v / top) * (base - 8)
                x1, x2 = i * bw + 2, (i + 1) * bw - 2
                if v:
                    col = ACCENT_HI if i == n - 1 else mix(ACCENT_LO, ACCENT, h / max(base - 8, 1))
                    c.create_rectangle(x1, base - h, x2, base, fill=col, outline="")
                else:
                    c.create_rectangle(x1, base - 2, x2, base, fill=BORDER, outline="")
        c.create_text(4, H - 7, anchor="w", text=self.caption, font=(FONT, 8), fill=DIM)
        if top:
            c.create_text(W - 4, 8, anchor="e", text=f"peak {top}", font=(FONT, 8), fill=MUTED)


# ------------------------------------------------------------------ toast notifications
class Toasts:
    """Small messages that slide in at the bottom right and leave by themselves."""
    KINDS = {"info": ACCENT, "ok": OK, "err": ERR, "warn": WARN}

    def __init__(self, root):
        self.root = root
        self.items = []

    def show(self, text, kind="info"):
        now = time.time()
        if any(i["text"] == text and now - i["t"] < 2.5 for i in self.items):
            return
        col = self.KINDS.get(kind, ACCENT)
        f = tk.Frame(self.root, bg=SURFACE2, highlightthickness=1, highlightbackground=col)
        tk.Frame(f, bg=col, width=4).pack(side="left", fill="y")
        tk.Label(f, text=text, fg=TEXT, bg=SURFACE2, font=(FONT, 9), wraplength=300, justify="left",
                 padx=12, pady=9).pack(side="left")
        item = {"f": f, "text": text, "t": now, "x": 340.0, "h": 40 + 16 * (len(text) // 46), "dead": False}
        self.items.append(item)
        while len(self.items) > 3:
            self._remove(self.items[0])
        self._layout()
        self._slide(item, 0.0, 8)
        self.root.after(3600, self._dismiss, item)

    def _layout(self):
        y = 18
        for it in reversed(self.items):
            it["y"] = y
            y += it["h"] + 8
            it["f"].place(relx=1.0, rely=1.0, x=-18 + int(it["x"]), y=-it["y"], anchor="se")
            it["f"].lift()

    def _slide(self, item, target, steps):
        start = item["x"]

        def step(i):
            if item["dead"]:
                return
            item["x"] = start + (target - start) * ease(i / steps)
            item["f"].place_configure(x=-18 + int(item["x"]))
            if i < steps:
                self.root.after(16, step, i + 1)
        step(1)

    def _dismiss(self, item):
        if item["dead"]:
            return
        self._slide(item, 340.0, 8)
        self.root.after(220, self._remove, item)

    def _remove(self, item):
        if item["dead"]:
            return
        item["dead"] = True
        if item in self.items:
            self.items.remove(item)
        try:
            item["f"].destroy()
        except Exception:
            pass
        self._layout()


# ------------------------------------------------------------------ animated canvases for the Home page
class HeroCanvas(tk.Canvas):
    """The NewLAN banner: a slowly drifting network of nodes and links with signal rings behind the title."""

    def __init__(self, parent, height=170):
        super().__init__(parent, height=height, bg=BG, highlightthickness=0)
        self.nodes, self.last, self.chip, self.chip_id = [], None, None, None
        self.bind("<Configure>", lambda e: self._layout())
        clock.add("home", self.tick)

    def attach_chip(self, chip):
        self.chip = chip
        self._layout()

    def _size(self):
        return max(self.winfo_width(), 600), max(self.winfo_height(), 140)

    def _layout(self):
        W, H = self._size()
        if not self.nodes:
            rng = random.Random(7)
            for i in range(30):
                ang = rng.uniform(0, 2 * math.pi)
                sp = rng.uniform(6, 16)
                self.nodes.append([rng.uniform(0, W), rng.uniform(0, H), math.cos(ang) * sp, math.sin(ang) * sp,
                                   VIOLET if i % 6 == 0 else ACCENT])
        self.delete("title")
        cx = W / 2
        for dx, dy, col in ((-2, 2, ACCENT_LO), (2, 2, VIOLET_LO), (0, 3, ACCENT_LO)):
            self.create_text(cx + dx, H * 0.40 + dy, text="NewLAN", font=(FONT, 44, "bold"), fill=col, tags="title")
        self.create_text(cx, H * 0.40, text="NewLAN", font=(FONT, 44, "bold"), fill=TEXT, tags="title")
        self.create_text(cx, H * 0.40 + 46, text="Blockchain-secured network access control", font=(FONT, 12),
                         fill=MUTED, tags="title")
        if self.chip is not None:
            if self.chip_id is None:
                self.chip_id = self.create_window(cx, H - 22, window=self.chip)
            else:
                self.coords(self.chip_id, cx, H - 22)

    def tick(self, t):
        W, H = self._size()
        dt = 0.04 if self.last is None else min(0.1, t - self.last)
        self.last = t
        self.delete("net")
        for n in self.nodes:
            n[0] += n[2] * dt
            n[1] += n[3] * dt
            if n[0] < 0 or n[0] > W:
                n[2] = -n[2]
            if n[1] < 0 or n[1] > H:
                n[3] = -n[3]
        cx, cy = W / 2, H * 0.40
        for k in range(3):                                     # signal rings behind the title
            p = ((t * 0.35) + k / 3) % 1.0
            r = 60 + p * 190
            self.create_oval(cx - r, cy - r * 0.38, cx + r, cy + r * 0.38, outline=mix(BG, ACCENT, 0.32 * (1 - p)),
                             width=2, tags="net")
        nodes = self.nodes
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                d = math.hypot(nodes[i][0] - nodes[j][0], nodes[i][1] - nodes[j][1])
                if d < 120:
                    self.create_line(nodes[i][0], nodes[i][1], nodes[j][0], nodes[j][1],
                                     fill=mix(BG, nodes[i][4], 0.5 * (1 - d / 120)), tags="net")
        for x, y, _, _, col in nodes:
            self.create_oval(x - 2.5, y - 2.5, x + 2.5, y + 2.5, fill=mix(BG, col, 0.85), outline="", tags="net")
        self.tag_lower("net")


class PipelineCanvas(tk.Canvas):
    """'How it works': a request travels Device -> Router -> RADIUS -> Blockchain and an answer comes back."""
    NODES = [("Device", "asks to join"), ("Router", "passes it on"), ("RADIUS server", "asks the ledger"),
             ("Blockchain", "checks the allowlist")]
    FWD, PAUSE, BACK, HOLD = 1.3, 0.8, 0.9, 1.4

    def __init__(self, parent, height=124):
        super().__init__(parent, height=height, bg=BG, highlightthickness=0)
        self.bind("<Configure>", lambda e: self.tick(time.time()))
        clock.add("home", self.tick, every=2)

    def tick(self, t):
        c = self
        c.delete("all")
        W, H = max(c.winfo_width(), 600), max(c.winfo_height(), 100)
        total = 3 * self.FWD + self.PAUSE + 3 * self.BACK + self.HOLD
        u = t % total
        nw, cy = 112, 46
        xs = [70 + (W - 140) * i / 3 for i in range(4)]
        # which part of the cycle are we in?
        if u < 3 * self.FWD:
            leg, p, back, cap = int(u // self.FWD), (u % self.FWD) / self.FWD, False, None
            active = leg + 1 if p > 0.85 else leg
            cap = ["1  The device asks the router to let it join", "2  The router forwards the request to the RADIUS server",
                   "3  The RADIUS server asks the smart contract"][leg]
        elif u < 3 * self.FWD + self.PAUSE:
            leg, p, back, active = 2, 1.0, False, 3
            cap = "4  The blockchain answers: is this MAC on the allowlist?"
        elif u < 3 * self.FWD + self.PAUSE + 3 * self.BACK:
            v = u - 3 * self.FWD - self.PAUSE
            leg, p, back, active = 2 - int(v // self.BACK), (v % self.BACK) / self.BACK, True, 3 - int(v // self.BACK)
            cap = "5  The answer travels back to the device"
        else:
            leg, p, back, active = 0, 0.0, True, 0
            cap = "6  Access granted: the device is on the network"
        for i in range(3):
            x1, x2 = xs[i] + nw / 2, xs[i + 1] - nw / 2
            lit = (leg == i) and u < 3 * self.FWD + self.PAUSE + 3 * self.BACK
            c.create_line(x1, cy, x2, cy, fill=ACCENT if lit else BORDER, width=2, dash=() if lit else (4, 4))
        for i, (title, sub) in enumerate(self.NODES):
            on = i == active
            if on:
                glow_rect(c, xs[i] - nw / 2, cy - 26, xs[i] + nw / 2, cy + 26, 12, ACCENT, layers=2)
            round_rect(c, xs[i] - nw / 2, cy - 26, xs[i] + nw / 2, cy + 26, 12, fill=SURFACE2 if on else SURFACE,
                       outline=ACCENT if on else BORDER, width=2)
            c.create_text(xs[i], cy - 7, text=title, font=(FONT, 9, "bold"), fill=TEXT if on else MUTED)
            c.create_text(xs[i], cy + 10, text=sub, font=(FONT, 8), fill=ACCENT_HI if on else DIM)
        if u < 3 * self.FWD + self.PAUSE + 3 * self.BACK:
            x1, x2 = xs[leg] + nw / 2, xs[leg + 1] - nw / 2
            e = ease(p)
            px = x2 - (x2 - x1) * e if back else x1 + (x2 - x1) * e
            col = OK if back else ACCENT
            for k in range(1, 5):                              # comet trail
                tx = px + k * 9 if back else px - k * 9
                c.create_oval(tx - 4 + k * 0.6, cy - 4 + k * 0.6, tx + 4 - k * 0.6, cy + 4 - k * 0.6,
                              fill=mix(BG, col, 0.5 - k * 0.1), outline="")
            c.create_oval(px - 6, cy - 6, px + 6, cy + 6, fill=col, outline=mix(col, BG, 0.5), width=2)
        c.create_text(W / 2, H - 20, text=cap, font=(FONT, 10), fill=OK if cap.startswith("6") else MUTED)
