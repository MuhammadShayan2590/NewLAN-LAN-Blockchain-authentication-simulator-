"""NewLAN shared theme and widgets (red and white)."""
import tkinter as tk

RED = "#D4202C"
RED_DARK = "#A3151F"
RED_MID = "#F6C2C6"
RED_SOFT = "#FDECEE"
WHITE = "#FFFFFF"
INK = "#1F2430"
MUTED = "#6B7280"
LINE = "#E5E7EB"
PANEL = "#FAFAFB"
OK = "#16A34A"
WARN = "#D97706"
OFF = "#9CA3AF"
FONT = "Segoe UI"


class Btn(tk.Label):
    """Flat button with hover colours. style: primary | outline."""
    STYLES = {
        "primary": dict(bg=RED, fg=WHITE, hbg=RED_DARK, hfg=WHITE, border=RED, hborder=RED_DARK),
        "outline": dict(bg=WHITE, fg=RED, hbg=RED, hfg=WHITE, border=RED, hborder=RED),
    }
    SIZES = {"sm": (12, 5, 9), "md": (18, 9, 10), "lg": (34, 14, 13)}

    def __init__(self, parent, text, command=None, style="primary", size="md", **kw):
        s = self.STYLES[style]
        px, py, fs = self.SIZES[size]
        super().__init__(parent, text=text, bg=s["bg"], fg=s["fg"], font=(FONT, fs, "bold"), padx=px, pady=py,
                         cursor="hand2", highlightthickness=1, highlightbackground=s["border"], bd=0, **kw)
        self.s, self.command, self.enabled, self.hover = s, command, True, False
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<Button-1>", lambda e: self._click())

    def _paint(self):
        s = self.s
        if not self.enabled:
            self.config(bg=PANEL, fg=OFF, highlightbackground=LINE, cursor="arrow")
        elif self.hover:
            self.config(bg=s["hbg"], fg=s["hfg"], highlightbackground=s["hborder"], cursor="hand2")
        else:
            self.config(bg=s["bg"], fg=s["fg"], highlightbackground=s["border"], cursor="hand2")

    def _set_hover(self, value):
        self.hover = value
        self._paint()

    def _click(self):
        if self.enabled and self.command:
            self.command()

    def set_enabled(self, enabled):
        self.enabled = enabled
        self._paint()


class NavItem(tk.Frame):
    """Sidebar entry: grey/white normally, red on hover, soft red when it is the current page."""

    def __init__(self, parent, icon, text, command):
        super().__init__(parent, bg=WHITE, cursor="hand2")
        self.command, self.active, self.hover = command, False, False
        self.bar = tk.Frame(self, width=4, bg=WHITE)
        self.bar.pack(side="left", fill="y")
        self.label = tk.Label(self, text=f"{icon}   {text}", anchor="w", bg=WHITE, fg=INK,
                              font=(FONT, 11), padx=18, pady=13, cursor="hand2")
        self.label.pack(side="left", fill="x", expand=True)
        for w in (self, self.label, self.bar):
            w.bind("<Enter>", lambda e: self._h(True))
            w.bind("<Leave>", lambda e: self._h(False))
            w.bind("<Button-1>", lambda e: self.command())

    def _h(self, value):
        self.hover = value
        self._paint()

    def set_active(self, value):
        self.active = value
        self._paint()

    def _paint(self):
        if self.hover:
            bg, fg, bar, font = RED, WHITE, RED_DARK, (FONT, 11, "bold")
        elif self.active:
            bg, fg, bar, font = RED_SOFT, RED, RED, (FONT, 11, "bold")
        else:
            bg, fg, bar, font = WHITE, INK, WHITE, (FONT, 11)
        self.config(bg=bg)
        self.label.config(bg=bg, fg=fg, font=font)
        self.bar.config(bg=bar)


class StatusCard(tk.Frame):
    def __init__(self, parent, title):
        super().__init__(parent, bg=WHITE, highlightthickness=1, highlightbackground=LINE, padx=14, pady=12)
        tk.Label(self, text=title.upper(), font=(FONT, 8, "bold"), fg=MUTED, bg=WHITE).pack(anchor="w")
        row = tk.Frame(self, bg=WHITE)
        row.pack(anchor="w", fill="x", pady=(6, 0))
        self.dot = tk.Label(row, text="\u25cf", fg=OFF, bg=WHITE, font=(FONT, 13))
        self.dot.pack(side="left", anchor="n")
        self.text = tk.Label(row, text="Checking...", fg=INK, bg=WHITE, font=(FONT, 10),
                             wraplength=165, justify="left", anchor="w")
        self.text.pack(side="left", padx=(6, 0), fill="x", expand=True)

    def set(self, color, text):
        self.dot.config(fg=color)
        self.text.config(text=text)


def make_entry(parent, var, **kw):
    return tk.Entry(parent, textvariable=var, relief="flat", bd=0, bg=WHITE, fg=INK, insertbackground=RED,
                    highlightthickness=2, highlightbackground=LINE, highlightcolor=RED, font=(FONT, 11), **kw)


def round_rect(c, x1, y1, x2, y2, r=12, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
           x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def page_header(parent, title, subtitle):
    box = tk.Frame(parent, bg=WHITE)
    box.pack(fill="x", padx=36, pady=(28, 14))
    tk.Label(box, text=title, font=(FONT, 22, "bold"), fg=INK, bg=WHITE).pack(anchor="w")
    tk.Label(box, text=subtitle, font=(FONT, 10), fg=MUTED, bg=WHITE, wraplength=820, justify="left").pack(anchor="w", pady=(2, 0))
    tk.Frame(box, bg=RED, height=3, width=46).pack(anchor="w", pady=(10, 0))
    return box


class SegTab(tk.Label):
    """Sub-section tab: white with red text, red on hover, dark red when it is the current one."""

    def __init__(self, parent, text, command):
        super().__init__(parent, text=text, font=(FONT, 10, "bold"), padx=20, pady=8, cursor="hand2",
                         highlightthickness=1, bd=0)
        self.command, self.active, self.hover = command, False, False
        self.bind("<Enter>", lambda e: self._h(True))
        self.bind("<Leave>", lambda e: self._h(False))
        self.bind("<Button-1>", lambda e: self.command())
        self._paint()

    def _h(self, value):
        self.hover = value
        self._paint()

    def set_active(self, value):
        self.active = value
        self._paint()

    def _paint(self):
        if self.hover:
            bg, fg, border = RED, WHITE, RED
        elif self.active:
            bg, fg, border = RED_DARK, WHITE, RED_DARK
        else:
            bg, fg, border = WHITE, RED, RED
        self.config(bg=bg, fg=fg, highlightbackground=border)
