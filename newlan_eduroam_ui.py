"""NewLAN Eduroam testbed page: five routers in a 3D space, devices at (x, y, z), best-router choice and roaming."""
import math
import random
import tkinter as tk
from tkinter import ttk

import newlan_eduroam as ed
from newlan_widgets import (INK, LINE, MUTED, OFF, OK, RED, RED_DARK, RED_MID, RED_SOFT, WHITE, FONT,
                            Btn, make_entry, round_rect)


def rlabel(rid):
    r = ed.ROUTER_BY_ID.get(rid)
    return f"{rid} {r['name']}" if r else "-"


class EduroamPage:
    def __init__(self, app, parent):
        self.app = app
        self.be = app.be
        self.net = app.net
        self.sel_mac = None
        self.combo_macs = []
        self.visible = False
        self.token = 0
        self.tf = (0, 0, 1)
        self.var_x, self.var_y, self.var_z = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.var_auto = tk.BooleanVar(value=True)
        self.var_cov = tk.BooleanVar(value=False)
        self.var_cand = tk.BooleanVar(value=False)
        self._build(parent)

    # ================================================================== layout
    def _build(self, parent):
        head = tk.Frame(parent, bg=WHITE)
        head.pack(fill="x", padx=36, pady=(22, 0))
        tk.Label(head, text="Eduroam testbed", font=(FONT, 22, "bold"), fg=INK, bg=WHITE).pack(side="left")
        tk.Label(head, text=f"{ed.SPACE[0]:g} x {ed.SPACE[1]:g} x {ed.SPACE[2]:g} m space  \u00b7  5 routers  \u00b7  "
                            "click the map to move the selected device", font=(FONT, 9), fg=MUTED, bg=WHITE
                 ).pack(side="left", padx=14, pady=(10, 0))
        tk.Frame(parent, bg=RED, height=3, width=46).pack(anchor="w", padx=36, pady=(8, 0))

        body = tk.Frame(parent, bg=WHITE)
        body.pack(fill="both", expand=True, padx=36, pady=(12, 0))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=0, minsize=340)
        body.rowconfigure(0, weight=1)

        mapcard = tk.Frame(body, bg=WHITE, highlightthickness=1, highlightbackground=LINE)
        mapcard.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.map = tk.Canvas(mapcard, bg=WHITE, highlightthickness=0, cursor="crosshair")
        self.map.pack(fill="both", expand=True)
        self.map.bind("<Configure>", lambda e: self.draw_map())
        self.map.bind("<Button-1>", self._map_click)

        right = tk.Frame(body, bg=WHITE)
        right.grid(row=0, column=1, sticky="nsew")
        ctl = tk.Frame(right, bg=WHITE, highlightthickness=1, highlightbackground=LINE, padx=12, pady=10)
        ctl.pack(fill="x")
        tk.Label(ctl, text="DEVICE", font=(FONT, 8, "bold"), fg=MUTED, bg=WHITE).pack(anchor="w")
        self.cb = ttk.Combobox(ctl, state="readonly", font=(FONT, 10))
        self.cb.pack(fill="x", pady=(3, 8), ipady=3)
        self.cb.bind("<<ComboboxSelected>>", lambda e: self.on_pick())
        pos = tk.Frame(ctl, bg=WHITE)
        pos.pack(fill="x")
        for label, var in (("X", self.var_x), ("Y", self.var_y), ("Z", self.var_z)):
            tk.Label(pos, text=label, font=(FONT, 10, "bold"), fg=RED, bg=WHITE).pack(side="left")
            e = make_entry(pos, var, width=6)
            e.pack(side="left", padx=(4, 10), ipady=4)
            e.bind("<Return>", lambda ev: self.apply_position())
        tk.Label(pos, text="metres", font=(FONT, 8), fg=MUTED, bg=WHITE).pack(side="left")
        grid = tk.Frame(ctl, bg=WHITE)
        grid.pack(fill="x", pady=(10, 0))
        for i in range(2):
            grid.columnconfigure(i, weight=1, uniform="g")
        buttons = [("Move here", self.apply_position, "primary"), ("Random position", self.random_position, "outline"),
                   ("Connect (best router)", self.connect_selected, "primary"), ("Reconnect to best", self.reconnect_selected, "outline"),
                   ("Disconnect", self.disconnect_selected, "outline"), ("Connect all", self.connect_all, "outline")]
        for i, (t, cmd, style) in enumerate(buttons):
            Btn(grid, t, cmd, style, "sm").grid(row=i // 2, column=i % 2, sticky="ew", padx=2, pady=3)
        Btn(ctl, "Reconnect all devices to their best router", self.reconnect_all, "outline", "sm").pack(fill="x", padx=2, pady=(3, 0))
        for text, var, cmd in (("Reconnect automatically after moving", self.var_auto, None),
                               ("Show coverage range", self.var_cov, self.draw_map),
                               ("Show other routers in range", self.var_cand, self.draw_map)):
            tk.Checkbutton(ctl, text=text, variable=var, command=cmd, bg=WHITE, fg=INK, activebackground=WHITE,
                           activeforeground=RED, selectcolor=WHITE, font=(FONT, 9), anchor="w").pack(fill="x", pady=(4, 0))
        self.msg = tk.Label(ctl, text="Select a device to place it.", font=(FONT, 9), fg=MUTED, bg=WHITE,
                            wraplength=310, justify="left", anchor="w")
        self.msg.pack(fill="x", pady=(8, 0))

        sidecard = tk.Frame(right, bg=WHITE, highlightthickness=1, highlightbackground=LINE)
        sidecard.pack(fill="both", expand=True, pady=(10, 0))
        self.side = tk.Canvas(sidecard, bg=WHITE, highlightthickness=0, height=120)
        self.side.pack(fill="both", expand=True)
        self.side.bind("<Configure>", lambda e: self.draw_side())

        tcard = tk.Frame(parent, bg=WHITE)
        tcard.pack(fill="x", padx=36, pady=(10, 14))
        self.table_title = tk.Label(tcard, text="Router choice", font=(FONT, 9, "bold"), fg=MUTED, bg=WHITE, anchor="w")
        self.table_title.pack(fill="x", pady=(0, 4))
        wrap = tk.Frame(tcard, bg=WHITE, highlightthickness=1, highlightbackground=LINE)
        wrap.pack(fill="x")
        self.tree = ttk.Treeview(wrap, style="Compact.Treeview", columns=("router", "dist", "rssi", "load", "score", "status"),
                                 show="headings", height=5, selectmode="none")
        for c, t, w in (("router", "ROUTER", 160), ("dist", "DISTANCE", 100), ("rssi", "SIGNAL", 100), ("load", "LOAD", 90),
                        ("score", "SCORE", 90), ("status", "STATUS", 200)):
            self.tree.heading(c, text=t, anchor="w")
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="x")
        self.tree.tag_configure("best", foreground=OK)
        self.tree.tag_configure("cur", foreground=RED)
        self.tree.tag_configure("out", foreground=OFF)

    # ================================================================== lifecycle
    def on_show(self):
        self.visible = True
        self.token += 1
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
            self._say(self.app.registry_problem, RED)
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
            self._say("Select a device first.", RED)
            return None
        return self.sel_mac

    def apply_position(self):
        mac = self._need_device()
        if not mac:
            return
        try:
            pos = self.net.set_pos(mac, (self.var_x.get(), self.var_y.get(), self.var_z.get()))
        except ValueError as e:
            self._say(str(e), RED)
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
        self._say(text, OK if res["ok"] else RED)
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
            self._say(f"{self.net.name(mac)} is not connected.", RED)
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
            self.app.ui(self._say, f"Connected {ok} of {len(macs)} device(s), each to its best router.", OK if ok == len(macs) else RED)
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
        c.create_rectangle(ox, oy, ox + sx * s, oy + sy * s, fill=WHITE, outline=LINE, width=2)
        for gx in range(10, int(sx), 10):
            c.create_line(ox + gx * s, oy, ox + gx * s, oy + sy * s, fill="#F1F2F4")
        for gy in range(10, int(sy), 10):
            c.create_line(ox, oy + gy * s, ox + sx * s, oy + gy * s, fill="#F1F2F4")
        for gx in range(0, int(sx) + 1, 20):
            c.create_text(ox + gx * s, oy + sy * s + 11, text=str(gx), font=(FONT, 7), fill=OFF)
        for gy in range(0, int(sy) + 1, 10):
            c.create_text(ox - 12, oy + gy * s, text=str(gy), font=(FONT, 7), fill=OFF)
        c.create_text(ox + sx * s, oy - 12, anchor="e", text="top view (X across, Y down, metres)", font=(FONT, 8), fill=MUTED)

        def P(p):
            return ox + p[0] * s, oy + p[1] * s
        ids = [r["id"] for r in ed.ROUTERS]
        for i, a in enumerate(ids):                                          # router mesh
            for b in ids[i + 1:]:
                (x1, y1), (x2, y2) = P(ed.ROUTER_BY_ID[a]["pos"]), P(ed.ROUTER_BY_ID[b]["pos"])
                c.create_line(x1, y1, x2, y2, fill=RED_MID, dash=(4, 4))
        if self.var_cov.get():
            for r in ed.ROUTERS:
                x, y = P(r["pos"])
                rad = ed.RANGE_M * s
                c.create_oval(x - rad, y - rad, x + rad, y + rad, outline=RED_MID, dash=(2, 4))
        regs = [r for r in self.app.registry if r["auth"] and self.net.pos(r["mac"])]
        for r in regs:                                                       # connections
            mac = r["mac"]
            x, y = P(self.net.pos(mac))
            cur = self.net.router_of(mac)
            if self.var_cand.get():
                for row in self.net.evaluate(mac):
                    if row["in_range"] and row["id"] != cur:
                        rx, ry = P(ed.ROUTER_BY_ID[row["id"]]["pos"])
                        c.create_line(x, y, rx, ry, fill=LINE, dash=(3, 3))
            if cur:
                rx, ry = P(ed.ROUTER_BY_ID[cur]["pos"])
                c.create_line(x, y, rx, ry, fill=RED, width=2)
        for r in ed.ROUTERS:                                                 # routers
            x, y = P(r["pos"])
            load = self.net.load(r["id"])
            c.create_oval(x - 13, y - 13, x + 13, y + 13, fill=RED, outline=RED_DARK, width=2)
            c.create_text(x, y, text=r["id"], font=(FONT, 8, "bold"), fill=WHITE)
            c.create_text(x, y + 23, text=f"{r['name']}  {load}/{r['capacity']}", font=(FONT, 8, "bold"), fill=RED_DARK)
        for r in regs:                                                       # devices
            mac = r["mac"]
            x, y = P(self.net.pos(mac))
            on = self.net.is_connected(mac)
            if mac == self.sel_mac:
                c.create_oval(x - 11, y - 11, x + 11, y + 11, outline=RED_DARK, width=2)
            c.create_oval(x - 6, y - 6, x + 6, y + 6, fill=OK if on else OFF, outline=WHITE, width=1)
            c.create_text(x + 10, y - 9, anchor="w", text=self.net.name(mac)[:14], font=(FONT, 8), fill=INK)
        c.create_text(ox, oy + sy * s + 24, anchor="w", font=(FONT, 8), fill=MUTED,
                      text="\u25cf connected   \u25cf offline   \u2500 connection   - - router mesh")

    def draw_side(self):
        c = self.side
        c.delete("all")
        W, H = max(c.winfo_width(), 300), max(c.winfo_height(), 100)
        mx, my = 24, 18
        sx, sz = (W - 2 * mx) / ed.SPACE[0], (H - 2 * my - 8) / ed.SPACE[2]

        def P(pos):
            return mx + pos[0] * sx, H - my - pos[2] * sz
        for z in (0, 4, 8, 12):
            y = H - my - z * sz
            c.create_line(mx, y, W - mx, y, fill=LINE if z else MUTED)
            c.create_text(mx - 4, y, anchor="e", text=str(z), font=(FONT, 7), fill=OFF)
        c.create_text(W - mx, 8, anchor="e", text="side view (X across, height Z up, metres)", font=(FONT, 8), fill=MUTED)
        for r in self.app.registry:
            mac = r["mac"]
            if r["auth"] and self.net.pos(mac) and self.net.router_of(mac):
                x, y = P(self.net.pos(mac))
                rx, ry = P(ed.ROUTER_BY_ID[self.net.router_of(mac)]["pos"])
                c.create_line(x, y, rx, ry, fill=RED, width=1)
        for r in ed.ROUTERS:
            x, y = P(r["pos"])
            c.create_rectangle(x - 7, y - 7, x + 7, y + 7, fill=RED, outline=RED_DARK)
            c.create_text(x, y, text=r["id"][1:], font=(FONT, 7, "bold"), fill=WHITE)
        for r in self.app.registry:
            mac = r["mac"]
            if r["auth"] and self.net.pos(mac):
                x, y = P(self.net.pos(mac))
                if mac == self.sel_mac:
                    c.create_oval(x - 8, y - 8, x + 8, y + 8, outline=RED_DARK, width=2)
                c.create_oval(x - 4, y - 4, x + 4, y + 4, fill=OK if self.net.is_connected(mac) else OFF, outline=WHITE)

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
            self.tree.insert("", "end", tags=(tag,), values=(
                rlabel(r["id"]), f"{r['dist']} m", f"{r['rssi']} dBm", f"{r['load']}/{r['capacity']}",
                f"{r['total']:.2f}", status))

    # ================================================================== map click
    def _map_click(self, e):
        ox, oy, s = self.tf
        x, y = (e.x - ox) / s, (e.y - oy) / s
        near, nd = None, 12.0
        for r in self.app.registry:
            pos = self.net.pos(r["mac"]) if r["auth"] else None
            if pos:
                d = math.hypot(ox + pos[0] * s - e.x, oy + pos[1] * s - e.y)
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
