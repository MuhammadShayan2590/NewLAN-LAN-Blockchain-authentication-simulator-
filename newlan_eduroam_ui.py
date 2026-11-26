"""NewLAN Eduroam testbed page: five routers in a 3D space, devices at (x, y, z), best-router choice and roaming."""
import math
import random
import time
import tkinter as tk
from tkinter import ttk

import newlan_eduroam as ed
from newlan_widgets import (ACCENT, ACCENT_HI, ACCENT_LO, BG, BORDER, DIM, ERR, FONT, MUTED, OFF, OK, SURFACE, SURFACE2, TEXT,
                            VIOLET, WARN, Btn, GradientBar, Switch, clock, make_entry, mix, round_rect)


def rlabel(rid):
    r = ed.ROUTER_BY_ID.get(rid)
    return f"{rid} {r['name']}" if r else "-"


def signal_score(dist):
    return max(0.0, min(1.0, (ed.rssi_at(dist) - ed.RSSI_MIN) / (ed.RSSI_1M - ed.RSSI_MIN)))


def bars(sig):
    n = 1 + int(sig * 3.99)
    return "\u2582\u2584\u2586\u2588"[:n]


class EduroamPage:
    ROAM_FX = 1.8        # seconds a roam highlight stays on the map

    def __init__(self, app, parent):
        self.app = app
        self.be = app.be
        self.net = app.net
        self.sel_mac = None
        self.combo_macs = []
        self.visible = False
        self.token = 0
        self.tf = (0, 0, 1)
        self.disp = {}              # mac -> displayed [x, y, z]; glides towards the real position
        self.last_router = {}       # mac -> router id, to spot roaming
        self.roams = []             # {"mac", "from", "to", "t0"}
        self._dirty = True
        self.var_x, self.var_y, self.var_z = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.var_auto = tk.BooleanVar(value=True)
        self.var_cov = tk.BooleanVar(value=False)
        self.var_cand = tk.BooleanVar(value=False)
        self._build(parent)
        clock.add("eduroam", self._fx_tick)

    # ================================================================== layout
    def _build(self, parent):
        head = tk.Frame(parent, bg=BG)
        head.pack(fill="x", padx=36, pady=(22, 0))
        tk.Label(head, text="Eduroam testbed", font=(FONT, 22, "bold"), fg=TEXT, bg=BG).pack(side="left")
        tk.Label(head, text=f"{ed.SPACE[0]:g} x {ed.SPACE[1]:g} x {ed.SPACE[2]:g} m space  \u00b7  5 routers  \u00b7  "
                            "click the map to move the selected device", font=(FONT, 9), fg=MUTED, bg=BG
                 ).pack(side="left", padx=14, pady=(10, 0))
        GradientBar(parent, ACCENT, VIOLET, height=3, width=56).pack(anchor="w", padx=36, pady=(8, 0))

        body = tk.Frame(parent, bg=BG)
        body.pack(fill="both", expand=True, padx=36, pady=(12, 0))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=0, minsize=348)
        body.rowconfigure(0, weight=1)

        mapcard = tk.Frame(body, bg=BG, highlightthickness=1, highlightbackground=BORDER)
        mapcard.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.map = tk.Canvas(mapcard, bg=BG, highlightthickness=0, cursor="crosshair")
        self.map.pack(fill="both", expand=True)
        self.map.bind("<Configure>", lambda e: self.draw_map())
        self.map.bind("<Button-1>", self._map_click)
        tk.Frame(mapcard, bg=BORDER, height=1).pack(fill="x")
        self.side = tk.Canvas(mapcard, bg=BG, highlightthickness=0, height=116)     # side view: shows the Z coordinate
        self.side.pack(fill="x")
        self.side.bind("<Configure>", lambda e: self.draw_side())

        right = tk.Frame(body, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")
        ctl = tk.Frame(right, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER, padx=12, pady=10)
        ctl.pack(fill="x")
        tk.Label(ctl, text="DEVICE", font=(FONT, 8, "bold"), fg=MUTED, bg=SURFACE).pack(anchor="w")
        self.cb = ttk.Combobox(ctl, state="readonly", font=(FONT, 10))
        self.cb.pack(fill="x", pady=(3, 8), ipady=3)
        self.cb.bind("<<ComboboxSelected>>", lambda e: self.on_pick())
        pos = tk.Frame(ctl, bg=SURFACE)
        pos.pack(fill="x")
        for label, var in (("X", self.var_x), ("Y", self.var_y), ("Z", self.var_z)):
            tk.Label(pos, text=label, font=(FONT, 10, "bold"), fg=ACCENT, bg=SURFACE).pack(side="left")
            e = make_entry(pos, var, width=6)
            e.pack(side="left", padx=(4, 10), ipady=4)
            e.bind("<Return>", lambda ev: self.apply_position())
        tk.Label(pos, text="metres", font=(FONT, 8), fg=MUTED, bg=SURFACE).pack(side="left")
        grid = tk.Frame(ctl, bg=SURFACE)
        grid.pack(fill="x", pady=(10, 0))
        for i in range(2):
            grid.columnconfigure(i, weight=1, uniform="g")
        buttons = [("Move here", self.apply_position, "primary"), ("Random position", self.random_position, "outline"),
                   ("Connect (best router)", self.connect_selected, "primary"), ("Reconnect to best", self.reconnect_selected, "outline"),
                   ("Disconnect", self.disconnect_selected, "danger"), ("Connect all", self.connect_all, "outline")]
        for i, (t, cmd, style) in enumerate(buttons):
            Btn(grid, t, cmd, style, "sm").grid(row=i // 2, column=i % 2, sticky="ew", padx=2, pady=3)
        Btn(ctl, "Reconnect all devices to their best router", self.reconnect_all, "outline", "sm").pack(fill="x", padx=2, pady=(3, 0))
        for text, var, cmd in (("Reconnect automatically after moving", self.var_auto, None),
                               ("Show coverage range", self.var_cov, self._redraw),
                               ("Show other routers in range", self.var_cand, self._redraw)):
            row = tk.Frame(ctl, bg=SURFACE)
            row.pack(fill="x", pady=(6, 0))
            Switch(row, var, command=cmd, base=SURFACE).pack(side="left")
            tk.Label(row, text=text, font=(FONT, 9), fg=TEXT, bg=SURFACE).pack(side="left", padx=10)
        self.msg = tk.Label(ctl, text="Select a device to place it.", font=(FONT, 9), fg=MUTED, bg=SURFACE,
                            wraplength=316, justify="left", anchor="w")
        self.msg.pack(fill="x", pady=(8, 0))

        tcard = tk.Frame(parent, bg=BG)
        tcard.pack(fill="x", padx=36, pady=(10, 14))
        self.table_title = tk.Label(tcard, text="Router choice", font=(FONT, 9, "bold"), fg=MUTED, bg=BG, anchor="w")
        self.table_title.pack(fill="x", pady=(0, 4))
        wrap = tk.Frame(tcard, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        wrap.pack(fill="x")
        self.tree = ttk.Treeview(wrap, style="Compact.Treeview", columns=("router", "dist", "rssi", "load", "score", "status"),
                                 show="headings", height=5, selectmode="none")
        for c, t, w in (("router", "ROUTER", 160), ("dist", "DISTANCE", 100), ("rssi", "SIGNAL", 130), ("load", "LOAD", 90),
                        ("score", "SCORE", 90), ("status", "STATUS", 200)):
            self.tree.heading(c, text=t, anchor="w")
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="x")
        self.tree.tag_configure("best", foreground=OK)
        self.tree.tag_configure("cur", foreground=ACCENT_HI)
        self.tree.tag_configure("out", foreground=DIM)

    def _redraw(self):
        self._dirty = True
        self.draw_map()

    # ================================================================== lifecycle
    def on_show(self):
        self.visible = True
        self.token += 1
        self._dirty = True
        self.app.refresh_registry(then=self.refresh_views)
        self.app.after(1500, self._tick, self.token, 1)

    def on_hide(self):
        self.visible = False

    def _tick(self, token, n):
        if not self.visible or token != self.token:
            return
        if n % 5 == 0:
            self.app.refresh_registry(then=self.refresh_views)
        else:
            self.draw_all()
        self.app.after(1500, self._tick, token, n + 1)

    def refresh_views(self):
        regs = [r for r in self.app.registry if r["auth"]]
        self.combo_macs = [r["mac"] for r in regs]
        self.cb.config(values=[f"{self.net.name(r['mac'])}   ({r['pretty']})" for r in regs])
        if self.sel_mac not in self.combo_macs:
            self.sel_mac = None
            self.cb.set("")
        else:
            self.cb.current(self.combo_macs.index(self.sel_mac))
        if self.sel_mac and not self.var_x.get():
            self._sync_coords()
        if self.app.registry_problem:
            self._say(self.app.registry_problem, ERR)
        self._dirty = True
        self.draw_all()

    def draw_all(self):
        self.draw_map()
        self.draw_side()
        self.fill_table()

    def _say(self, text, color=MUTED):
        self.msg.config(text=text, fg=color)

    # ================================================================== selection and coordinates
    def on_pick(self):
        i = self.cb.current()
        self.sel_mac = self.combo_macs[i] if 0 <= i < len(self.combo_macs) else None
        self._sync_coords()
        self.draw_all()

    def select_mac(self, mac):
        if mac in self.combo_macs:
            self.cb.current(self.combo_macs.index(mac))
            self.on_pick()

    def _sync_coords(self):
        pos = self.net.pos(self.sel_mac) if self.sel_mac else None
        for var, v in zip((self.var_x, self.var_y, self.var_z), pos or ("", "", "")):
            var.set(f"{v:g}" if v != "" else "")

    def _need_device(self):
        if not self.sel_mac:
            self._say("Select a device first.", ERR)
            return None
        return self.sel_mac

    def apply_position(self):
        mac = self._need_device()
        if not mac:
            return
        try:
            pos = self.net.set_pos(mac, (self.var_x.get(), self.var_y.get(), self.var_z.get()))
        except ValueError as e:
            self._say(str(e), ERR)
            return
        self._sync_coords()
        name = self.net.name(mac)
        if self.var_auto.get() and self.net.is_connected(mac):
            self.reconnect_selected(prefix=f"{name} moved to ({pos[0]:g}, {pos[1]:g}, {pos[2]:g}). ")
        else:
            hint = " Press Reconnect to switch to the best router." if self.net.is_connected(mac) else ""
            self._say(f"{name} moved to ({pos[0]:g}, {pos[1]:g}, {pos[2]:g}).{hint}", OK)
            self.app.network_changed()

    def random_position(self):
        mac = self._need_device()
        if not mac:
            return
        x, y, z = ed.random_position(random)
        self.var_x.set(f"{x:g}")
        self.var_y.set(f"{y:g}")
        self.var_z.set(f"{z:g}")
        self.apply_position()

    # ================================================================== connection actions
    def _describe(self, mac, res, prefix=""):
        name = self.net.name(mac)
        if res.get("changed") and res.get("to"):
            if res.get("from"):
                best = next((r for r in res["eval"] if r["id"] == res["to"]), None)
                why = f" ({best['dist']} m, {best['rssi']} dBm, load {best['load']}/{best['capacity']})" if best else ""
                return f"{prefix}{name} roamed {rlabel(res['from'])} \u2192 {rlabel(res['to'])}{why}."
            return f"{prefix}{name} connected to {rlabel(res['to'])} as {self.net.ip(mac)}, checked by {res.get('how')}."
        if res["ok"]:
            return f"{prefix}{name} stays on {rlabel(res.get('to') or res.get('router'))}: {res.get('reason') or 'connected'}."
        return f"{prefix}{name}: {res['reason']}."

    def _finish(self, mac, res, prefix=""):
        text = self._describe(mac, res, prefix)
        self.app.log("Eduroam: " + text)
        self._say(text, OK if res["ok"] else ERR)
        self.app.network_changed(closed=res.get("closed"), note=text)

    def connect_selected(self):
        mac = self._need_device()
        if not mac:
            return
        self._say("Authenticating with the network...", MUTED)

        def work():
            res = self.net.join(mac, self.be.router_authenticate)
            res.setdefault("changed", res["ok"])
            res["to"] = res.get("router")
            res["from"] = None
            self.app.ui(self._finish, mac, res)
        self.app.bg(work)

    def reconnect_selected(self, prefix=""):
        mac = self._need_device()
        if not mac:
            return
        self._say("Re-evaluating routers...", MUTED)

        def work():
            res = self.net.reconnect(mac, self.be.router_authenticate)
            self.app.ui(self._finish, mac, res, prefix)
        self.app.bg(work)

    def disconnect_selected(self):
        mac = self._need_device()
        if not mac:
            return
        if not self.net.is_connected(mac):
            self._say(f"{self.net.name(mac)} is not connected.", ERR)
            return
        closed = self.net.leave(mac)
        text = f"{self.net.name(mac)} disconnected."
        self.app.log("Eduroam: " + text)
        self._say(text, MUTED)
        self.app.network_changed(closed=closed, note=text)

    def connect_all(self):
        macs = [m for m in self.combo_macs if not self.net.is_connected(m)]
        if not macs:
            self._say("Every registered device is already connected.", MUTED)
            return
        self._say(f"Connecting {len(macs)} device(s)...", MUTED)

        def work():
            ok = 0
            for m in macs:
                res = self.net.join(m, self.be.router_authenticate)
                ok += 1 if res["ok"] else 0
                self.app.log(f"Eduroam: {self.net.name(m)} " + (f"connected to {rlabel(res['router'])}." if res["ok"] else f"could not connect: {res['reason']}."))
            self.app.ui(self._say, f"Connected {ok} of {len(macs)} device(s), each to its best router.", OK if ok == len(macs) else ERR)
            self.app.ui(self.app.network_changed)
        self.app.bg(work)

    def reconnect_all(self):
        macs = [m for m in self.net.attached]
        if not macs:
            self._say("No devices are connected.", MUTED)
            return
        self._say("Re-evaluating every device...", MUTED)

        def work():
            moved, closed = 0, []
            for m in macs:
                res = self.net.reconnect(m, self.be.router_authenticate)
                if res.get("changed"):
                    moved += 1
                    self.app.log("Eduroam: " + self._describe(m, res))
                closed += res.get("closed") or []
            self.app.ui(self._say, f"{moved} device(s) switched router; the rest were already on their best one.", OK)
            self.app.ui(self.app.network_changed, closed)
        self.app.bg(work)

    # ================================================================== animation layer
    def _fx_tick(self, t):
        """Runs ~25 times a second while this page shows: glide devices, spot roams, animate the effects layer."""
        for mac, rid in self.net.attached.items():                     # a router change is a roam
            prev = self.last_router.get(mac)
            if prev and prev != rid:
                self.roams.append({"mac": mac, "from": prev, "to": rid, "t0": t})
                self._dirty = True
            self.last_router[mac] = rid
        for mac in [m for m in self.last_router if m not in self.net.attached]:
            self.last_router.pop(mac, None)
        self.roams = [r for r in self.roams if t - r["t0"] < self.ROAM_FX]
        moving = self._step_positions()
        if moving or self._dirty:
            self._dirty = False
            self.draw_map()
        else:
            self.draw_fx(t)

    def _step_positions(self):
        moving = False
        for r in self.app.registry:
            mac, pos = r["mac"], self.net.pos(r["mac"])
            if not (r["auth"] and pos):
                continue
            d = self.disp.get(mac)
            if d is None:
                self.disp[mac] = list(pos)
                continue
            for i in range(3):
                diff = pos[i] - d[i]
                if abs(diff) > 0.05:
                    d[i] += diff * 0.28
                    moving = True
                else:
                    d[i] = pos[i]
        return moving

    def _dpos(self, mac):
        return tuple(self.disp.get(mac) or self.net.pos(mac) or (0, 0, 0))

    def draw_fx(self, t):
        """Pulsing signal rings, energy flowing along connections, and roam highlights."""
        c = self.map
        c.delete("fx")
        ox, oy, s = self.tf

        def P(p):
            return ox + p[0] * s, oy + p[1] * s
        for i, r in enumerate(ed.ROUTERS):
            x, y = P(r["pos"])
            for k in range(2):
                p = ((t * 0.45) + k * 0.5 + i * 0.17) % 1.0
                rad = 16 + p * ed.RANGE_M * s * 0.7
                c.create_oval(x - rad, y - rad, x + rad, y + rad, outline=mix(BG, ACCENT, 0.42 * (1 - p)), width=1,
                              tags=("fx", "pulse"))
        for mac, rid in self.net.attached.items():
            if not self.net.pos(mac):
                continue
            x, y = P(self._dpos(mac))
            rx, ry = P(ed.ROUTER_BY_ID[rid]["pos"])
            sig = signal_score(ed.distance(self._dpos(mac), ed.ROUTER_BY_ID[rid]["pos"]))
            c.create_line(x, y, rx, ry, fill=mix(ERR, OK, sig), width=2, dash=(3, 9), dashoffset=int(t * 45) % 12, tags="fx")
        for r in self.roams:
            age = t - r["t0"]
            x1, y1 = P(ed.ROUTER_BY_ID[r["from"]]["pos"])
            x2, y2 = P(ed.ROUTER_BY_ID[r["to"]]["pos"])
            col = mix(VIOLET, BG, age / self.ROAM_FX)
            c.create_line(x1, y1, x2, y2, fill=col, width=4, dash=(8, 6), dashoffset=-int(t * 80) % 14, tags="fx")
            if self.net.pos(r["mac"]):
                dx, dy = P(self._dpos(r["mac"]))
                rad = 10 + age * 26
                c.create_oval(dx - rad, dy - rad, dx + rad, dy + rad, outline=col, width=2, tags="fx")
                c.create_text(dx + 14, dy + 14, anchor="w", text="roaming", font=(FONT, 8, "bold"), fill=mix(ACCENT_HI, BG, age / self.ROAM_FX), tags="fx")
        c.tag_lower("pulse")

    # ================================================================== drawing
    def _geometry(self, c):
        W, H = max(c.winfo_width(), 420), max(c.winfo_height(), 260)
        m = 30
        s = min((W - 2 * m) / ed.SPACE[0], (H - 2 * m) / ed.SPACE[1])
        return W, H, (W - ed.SPACE[0] * s) / 2, (H - ed.SPACE[1] * s) / 2, s

    def draw_map(self):
        c = self.map
        c.delete("all")
        W, H, ox, oy, s = self._geometry(c)
        self.tf = (ox, oy, s)
        sx, sy = ed.SPACE[0], ed.SPACE[1]
        c.create_rectangle(ox, oy, ox + sx * s, oy + sy * s, fill=mix(BG, SURFACE, 0.55), outline=BORDER, width=2)
        grid = mix(BG, BORDER, 0.45)
        for gx in range(10, int(sx), 10):
            c.create_line(ox + gx * s, oy, ox + gx * s, oy + sy * s, fill=grid)
        for gy in range(10, int(sy), 10):
            c.create_line(ox, oy + gy * s, ox + sx * s, oy + gy * s, fill=grid)
        for gx in range(0, int(sx) + 1, 20):
            c.create_text(ox + gx * s, oy + sy * s + 11, text=str(gx), font=(FONT, 7), fill=DIM)
        for gy in range(0, int(sy) + 1, 10):
            c.create_text(ox - 12, oy + gy * s, text=str(gy), font=(FONT, 7), fill=DIM)
        c.create_text(ox + sx * s, oy - 12, anchor="e", text="top view (X across, Y down, metres)", font=(FONT, 8), fill=MUTED)

        def P(p):
            return ox + p[0] * s, oy + p[1] * s
        ids = [r["id"] for r in ed.ROUTERS]
        for i, a in enumerate(ids):                                          # router mesh
            for b in ids[i + 1:]:
                (x1, y1), (x2, y2) = P(ed.ROUTER_BY_ID[a]["pos"]), P(ed.ROUTER_BY_ID[b]["pos"])
                c.create_line(x1, y1, x2, y2, fill=mix(BG, VIOLET, 0.5), dash=(4, 4))
        if self.var_cov.get():
            for r in ed.ROUTERS:
                x, y = P(r["pos"])
                rad = ed.RANGE_M * s
                c.create_oval(x - rad, y - rad, x + rad, y + rad, outline=mix(BG, ACCENT, 0.35), dash=(2, 4))
        regs = [r for r in self.app.registry if r["auth"] and self.net.pos(r["mac"])]
        for r in regs:                                                       # connections, coloured by signal strength
            mac = r["mac"]
            dp = self._dpos(mac)
            x, y = P(dp)
            cur = self.net.router_of(mac)
            if self.var_cand.get():
                for row in self.net.evaluate(mac):
                    if row["in_range"] and row["id"] != cur:
                        rx, ry = P(ed.ROUTER_BY_ID[row["id"]]["pos"])
                        c.create_line(x, y, rx, ry, fill=mix(BG, BORDER, 0.9), dash=(3, 3))
            if cur:
                rx, ry = P(ed.ROUTER_BY_ID[cur]["pos"])
                sig = signal_score(ed.distance(dp, ed.ROUTER_BY_ID[cur]["pos"]))
                c.create_line(x, y, rx, ry, fill=mix(BG, mix(ERR, OK, sig), 0.6), width=1 + int(sig * 2))
        for r in ed.ROUTERS:                                                 # routers: glow + load ring
            x, y = P(r["pos"])
            load = self.net.load(r["id"])
            for k in (3, 2, 1):
                c.create_oval(x - 13 - k * 3, y - 13 - k * 3, x + 13 + k * 3, y + 13 + k * 3, outline=mix(BG, ACCENT, 0.5 - k * 0.14))
            c.create_oval(x - 13, y - 13, x + 13, y + 13, fill=SURFACE2, outline=ACCENT, width=2)
            if load:
                c.create_arc(x - 19, y - 19, x + 19, y + 19, start=90, extent=-359.9 * load / r["capacity"], style="arc",
                             outline=ACCENT_HI, width=3)
            c.create_text(x, y, text=r["id"], font=(FONT, 8, "bold"), fill=ACCENT_HI)
            c.create_text(x, y + 28, text=f"{r['name']}  {load}/{r['capacity']}", font=(FONT, 8, "bold"), fill=TEXT)
        for r in regs:                                                       # devices
            mac = r["mac"]
            x, y = P(self._dpos(mac))
            on = self.net.is_connected(mac)
            col = OK if on else OFF
            if mac == self.sel_mac:
                c.create_oval(x - 12, y - 12, x + 12, y + 12, outline=ACCENT_HI, width=2)
            c.create_oval(x - 9, y - 9, x + 9, y + 9, outline=mix(BG, col, 0.4))
            c.create_oval(x - 6, y - 6, x + 6, y + 6, fill=col, outline=BG, width=1)
            c.create_text(x + 11, y - 10, anchor="w", text=self.net.name(mac)[:14], font=(FONT, 8), fill=TEXT)
        c.create_text(ox, oy + sy * s + 24, anchor="w", font=(FONT, 8), fill=MUTED,
                      text="\u25cf connected   \u25cf offline   \u2500 link colour = signal (green strong, red weak)   - - router mesh")
        self.draw_fx(time.time())

    def draw_side(self):
        c = self.side
        c.delete("all")
        W, H = max(c.winfo_width(), 300), max(c.winfo_height(), 100)
        mx, my = 28, 18
        sx, sz = (W - 2 * mx - 24) / ed.SPACE[0], (H - 2 * my - 8) / ed.SPACE[2]

        def P(pos):
            return mx + pos[0] * sx, H - my - pos[2] * sz
        for i, (z0, z1) in enumerate(((0, 4), (4, 8), (8, 12))):            # floors as alternating bands
            y0, y1 = H - my - z0 * sz, H - my - z1 * sz
            c.create_rectangle(mx, y1, W - mx - 24, y0, fill=mix(BG, SURFACE, 0.9 if i % 2 == 0 else 0.4), outline="")
            c.create_text(W - mx - 20, (y0 + y1) / 2, anchor="w", text=f"F{i + 1}", font=(FONT, 7, "bold"), fill=DIM)
        for z in (0, 4, 8, 12):
            y = H - my - z * sz
            c.create_line(mx, y, W - mx - 24, y, fill=BORDER if z else MUTED)
            c.create_text(mx - 4, y, anchor="e", text=str(z), font=(FONT, 7), fill=DIM)
        c.create_text(W - mx, 8, anchor="e", text="side view (X across, height Z up, metres)", font=(FONT, 8), fill=MUTED)
        for r in self.app.registry:
            mac = r["mac"]
            if r["auth"] and self.net.pos(mac) and self.net.router_of(mac):
                x, y = P(self._dpos(mac))
                rx, ry = P(ed.ROUTER_BY_ID[self.net.router_of(mac)]["pos"])
                sig = signal_score(ed.distance(self._dpos(mac), ed.ROUTER_BY_ID[self.net.router_of(mac)]["pos"]))
                c.create_line(x, y, rx, ry, fill=mix(BG, mix(ERR, OK, sig), 0.7), width=1)
        for r in ed.ROUTERS:
            x, y = P(r["pos"])
            round_rect(c, x - 8, y - 8, x + 8, y + 8, 4, fill=SURFACE2, outline=ACCENT, width=2)
            c.create_text(x, y, text=r["id"][1:], font=(FONT, 7, "bold"), fill=ACCENT_HI)
        for r in self.app.registry:
            mac = r["mac"]
            if r["auth"] and self.net.pos(mac):
                x, y = P(self._dpos(mac))
                if mac == self.sel_mac:
                    c.create_oval(x - 8, y - 8, x + 8, y + 8, outline=ACCENT_HI, width=2)
                c.create_oval(x - 4, y - 4, x + 4, y + 4, fill=OK if self.net.is_connected(mac) else OFF, outline=BG)

    def fill_table(self):
        self.tree.delete(*self.tree.get_children())
        mac = self.sel_mac
        if not mac or not self.net.pos(mac):
            self.table_title.config(text="Router choice: select a device to see how each router scores")
            return
        cur = self.net.router_of(mac)
        pos = self.net.pos(mac)
        self.table_title.config(
            text=f"Router choice for {self.net.name(mac)} at ({pos[0]:g}, {pos[1]:g}, {pos[2]:g})   "
                 f"score = {int(ed.W_SIGNAL * 100)}% signal quality + {int(ed.W_LOAD * 100)}% spare capacity")
        for r in self.net.evaluate(mac):
            if not r["in_range"]:
                status, tag = "Out of range", "out"
            elif r["full"]:
                status, tag = "Full", "out"
            elif r["best"] and r["id"] == cur:
                status, tag = "\u2605 Best  (connected)", "best"
            elif r["best"]:
                status, tag = "\u2605 Best", "best"
            elif r["id"] == cur:
                status, tag = "Connected", "cur"
            else:
                status, tag = "Available", ""
            sig = bars(signal_score(r["dist"])) if r["in_range"] else "-"
            self.tree.insert("", "end", tags=(tag,), values=(
                rlabel(r["id"]), f"{r['dist']} m", f"{r['rssi']} dBm  {sig}", f"{r['load']}/{r['capacity']}",
                f"{r['total']:.2f}", status))

    # ================================================================== map click
    def _map_click(self, e):
        ox, oy, s = self.tf
        x, y = (e.x - ox) / s, (e.y - oy) / s
        near, nd = None, 12.0
        for r in self.app.registry:
            pos = self.net.pos(r["mac"]) if r["auth"] else None
            if pos:
                dpos = self._dpos(r["mac"])
                d = math.hypot(ox + dpos[0] * s - e.x, oy + dpos[1] * s - e.y)
                if d < nd:
                    near, nd = r["mac"], d
        if near:
            self.select_mac(near)
            return
        if not (0 <= x <= ed.SPACE[0] and 0 <= y <= ed.SPACE[1]):
            return
        if not self._need_device():
            return
        pos = self.net.pos(self.sel_mac)
        self.var_x.set(f"{x:.1f}")
        self.var_y.set(f"{y:.1f}")
        self.var_z.set(f"{pos[2]:g}" if pos else "1.5")
        self.apply_position()
