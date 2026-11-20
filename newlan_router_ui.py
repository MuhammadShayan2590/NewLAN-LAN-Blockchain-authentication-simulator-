"""NewLAN Router page: the eduroam mesh network, and live communication between any two devices.

Two sub-sections:
  * Network      - the five routers as a full mesh, every device attached to its best router.
  * Connections  - open a link between any two connected devices (on the same or different routers)
                   and watch them talk, each in its own interface box. Every packet is stored on the
                   Packet store page.
"""
import math
import time
import tkinter as tk
from tkinter import ttk

import newlan_core as core
import newlan_eduroam as ed
from newlan_widgets import (INK, LINE, MUTED, OFF, OK, PANEL, RED, RED_DARK, RED_MID, RED_SOFT, WHITE, FONT,
                            Btn, SegTab, make_entry, round_rect)


def other(side):
    return "b" if side == "a" else "a"


class InterfaceBox(tk.Frame):
    """One end device's screen: status header, scrolling output, and a message line."""

    def __init__(self, parent, on_send):
        super().__init__(parent, bg=WHITE, highlightthickness=1, highlightbackground=LINE)
        self.on_send = on_send
        head = tk.Frame(self, bg=RED_SOFT)
        head.pack(fill="x")
        self.title = tk.Label(head, text="Interface", font=(FONT, 10, "bold"), fg=RED_DARK, bg=RED_SOFT, padx=12, pady=7)
        self.title.pack(side="left")
        self.chip = tk.Label(head, text="\u25cf  DOWN", font=(FONT, 8, "bold"), fg=OFF, bg=RED_SOFT, padx=12)
        self.chip.pack(side="right")
        self.meta = tk.Label(self, text="", font=("Consolas", 8), fg=MUTED, bg=WHITE, anchor="w", padx=12)
        self.meta.pack(fill="x", pady=(6, 0))
        wrap = tk.Frame(self, bg=WHITE)
        wrap.pack(fill="both", expand=True, padx=1, pady=(4, 0))
        self.text = tk.Text(wrap, bg=PANEL, fg=INK, font=("Consolas", 9), relief="flat", bd=0, wrap="word", padx=10,
                            pady=8, height=7, width=30, state="disabled", cursor="arrow", highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.text.tag_configure("time", foreground=OFF)
        self.text.tag_configure("tx", foreground=RED, font=("Consolas", 9, "bold"))
        self.text.tag_configure("rx", foreground=OK, font=("Consolas", 9, "bold"))
        self.text.tag_configure("sys", foreground=MUTED)
        self.text.tag_configure("err", foreground=RED_DARK, font=("Consolas", 9, "bold"))
        bottom = tk.Frame(self, bg=WHITE)
        bottom.pack(fill="x", padx=8, pady=8)
        self.var = tk.StringVar()
        self.entry = make_entry(bottom, self.var)
        self.entry.pack(side="left", fill="x", expand=True, ipady=4)
        self.entry.bind("<Return>", lambda e: self._send())
        self.send_btn = Btn(bottom, "Send", self._send, "primary", "sm")
        self.send_btn.pack(side="left", padx=(8, 0))

    def _send(self):
        text = self.var.get().strip()
        if text:
            self.var.set("")
            self.on_send(text)

    def set_device(self, title, ip, mac, via, up):
        self.title.config(text=title)
        self.meta.config(text=f"eth0  {ip or '-'}  {mac or '-'}  {('via ' + via) if via else ''}")
        self.chip.config(text="\u25cf  UP" if up else "\u25cf  DOWN", fg=OK if up else OFF)
        self.send_btn.set_enabled(up)
        self.entry.config(state="normal" if up else "disabled")

    def write(self, text, tag="", stamp=None):
        self.text.config(state="normal")
        self.text.insert("end", (stamp or time.strftime("%H:%M:%S")) + "  ", "time")
        self.text.insert("end", text + "\n", tag)
        self.text.see("end")
        self.text.config(state="disabled")

    def clear(self):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.config(state="disabled")


def router_label(rid):
    r = ed.ROUTER_BY_ID.get(rid)
    return f"{rid} {r['name']}" if r else "-"


class RouterPage:
    DUR_LEG, DUR_DROP = 0.45, 0.9

    def __init__(self, app, parent):
        self.app = app
        self.be = app.be
        self.net = app.net
        self.active_cid = None
        self.transcripts = {}       # cid -> {"a": [(stamp, text, tag)], "b": [...]}
        self.seen_router = {}       # mac -> router id (to announce roaming inside sessions)
        self.pkts = []
        self.ticking = False
        self.demo_token = 0
        self.visible = False
        self.periodic_token = 0
        self.hover_row = None
        self.combo_macs = []
        self._build(parent)

    # ================================================================== layout
    def _build(self, parent):
        head = tk.Frame(parent, bg=WHITE)
        head.pack(fill="x", padx=36, pady=(22, 0))
        tk.Label(head, text="Router", font=(FONT, 22, "bold"), fg=INK, bg=WHITE).pack(side="left")
        tk.Label(head, text=f"5 routers in a full mesh  \u00b7  network {ed.SUBNET}.0/24  \u00b7  one registration works at every router",
                 font=(FONT, 9), fg=MUTED, bg=WHITE).pack(side="left", padx=14, pady=(10, 0))
        tk.Frame(parent, bg=RED, height=3, width=46).pack(anchor="w", padx=36, pady=(8, 0))

        tabs = tk.Frame(parent, bg=WHITE)
        tabs.pack(fill="x", padx=36, pady=(12, 10))
        self.tab_net = SegTab(tabs, "Network", lambda: self.show_tab("network"))
        self.tab_con = SegTab(tabs, "Connections", lambda: self.show_tab("connections"))
        self.tab_net.pack(side="left")
        self.tab_con.pack(side="left", padx=8)

        self.stage = tk.Frame(parent, bg=WHITE)
        self.stage.pack(fill="both", expand=True, padx=36, pady=(0, 14))
        self.f_net = tk.Frame(self.stage, bg=WHITE)
        self.f_con = tk.Frame(self.stage, bg=WHITE)
        for f in (self.f_net, self.f_con):
            f.place(x=0, y=0, relwidth=1, relheight=1)
        self._build_network(self.f_net)
        self._build_connections(self.f_con)
        self.show_tab("network")

    def _build_network(self, f):
        split = tk.Frame(f, bg=WHITE)
        split.pack(fill="both", expand=True)
        split.columnconfigure(0, weight=5, minsize=380)
        split.columnconfigure(1, weight=6)
        split.rowconfigure(0, weight=1)
        left = tk.Frame(split, bg=WHITE, highlightthickness=1, highlightbackground=LINE)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.topo = tk.Canvas(left, bg=WHITE, highlightthickness=0)
        self.topo.pack(fill="both", expand=True)
        self.topo.bind("<Configure>", lambda e: self.draw_topology())

        right = tk.Frame(split, bg=WHITE, highlightthickness=1, highlightbackground=LINE)
        right.grid(row=0, column=1, sticky="nsew")
        self.tree = ttk.Treeview(right, columns=("name", "mac", "router", "ip", "state"), show="headings",
                                 selectmode="browse")
        for c, t, w in (("name", "NAME", 110), ("mac", "MAC ADDRESS", 150), ("router", "ROUTER", 70),
                        ("ip", "IP", 90), ("state", "STATUS", 100)):
            self.tree.heading(c, text=t, anchor="w")
            self.tree.column(c, width=w, anchor="w")
        sb = ttk.Scrollbar(right, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.tag_configure("ok", foreground=OK)
        self.tree.tag_configure("bad", foreground=RED)
        self.tree.tag_configure("off", foreground=MUTED)
        self.tree.tag_configure("hover", background=RED_SOFT)
        self.tree.bind("<Motion>", self._tree_hover)
        self.tree.bind("<Leave>", lambda e: self._tree_hover(None))
        self.tree.bind("<<TreeviewSelect>>", self._pick_row)

        bar = tk.Frame(f, bg=WHITE)
        bar.pack(fill="x", pady=(10, 0))
        tk.Label(bar, text="Name", font=(FONT, 10, "bold"), fg=INK, bg=WHITE).pack(side="left")
        self.var_name = tk.StringVar()
        make_entry(bar, self.var_name, width=14).pack(side="left", padx=(8, 10), ipady=5)
        Btn(bar, "Connect (best router)", self.connect_selected, "primary").pack(side="left")
        Btn(bar, "Connect all", self.connect_all, "outline").pack(side="left", padx=6)
        Btn(bar, "Disconnect", self.disconnect_selected, "outline").pack(side="left")
        Btn(bar, "Save name", self.save_name, "outline").pack(side="left", padx=6)
        self.net_msg = tk.Label(f, text="", font=(FONT, 9), fg=MUTED, bg=WHITE, anchor="w")
        self.net_msg.pack(fill="x", pady=(6, 0))

    def _build_connections(self, f):
        form = tk.Frame(f, bg=WHITE, highlightthickness=1, highlightbackground=LINE, padx=14, pady=10)
        form.pack(fill="x")
        tk.Label(form, text="Device A", font=(FONT, 10, "bold"), fg=INK, bg=WHITE).pack(side="left")
        self.cb_a = ttk.Combobox(form, state="readonly", width=26, font=(FONT, 10))
        self.cb_a.pack(side="left", padx=(8, 10), ipady=3)
        tk.Label(form, text="\u21c4", font=(FONT, 16, "bold"), fg=RED, bg=WHITE).pack(side="left")
        tk.Label(form, text="Device B", font=(FONT, 10, "bold"), fg=INK, bg=WHITE).pack(side="left", padx=(10, 0))
        self.cb_b = ttk.Combobox(form, state="readonly", width=26, font=(FONT, 10))
        self.cb_b.pack(side="left", padx=(8, 12), ipady=3)
        Btn(form, "Establish connection", self.establish, "primary").pack(side="left")
        self.con_msg = tk.Label(f, text="Pick any two connected devices, on the same router or different ones. "
                                        "Connect devices on the Network tab or the Eduroam testbed first.",
                                font=(FONT, 9), fg=MUTED, bg=WHITE, anchor="w")
        self.con_msg.pack(fill="x", pady=(6, 0))

        self.chip_row = tk.Frame(f, bg=WHITE)
        self.chip_row.pack(fill="x", pady=(6, 0))

        session = tk.Frame(f, bg=WHITE)
        session.pack(fill="both", expand=True, pady=(8, 0))
        tool = tk.Frame(session, bg=WHITE)
        tool.pack(fill="x")
        self.session_title = tk.Label(tool, text="No connection selected", font=(FONT, 12, "bold"), fg=INK, bg=WHITE)
        self.session_title.pack(side="left")
        self.stats = tk.Label(tool, text="", font=(FONT, 9, "bold"), fg=MUTED, bg=WHITE)
        self.stats.pack(side="left", padx=14)
        Btn(tool, "Close connection", self.close_active, "outline", "sm").pack(side="right")
        Btn(tool, "Clear screens", self.clear_screens, "outline", "sm").pack(side="right", padx=6)
        Btn(tool, "Run demo", self.run_demo, "primary", "sm").pack(side="right")
        Btn(tool, "Ping B \u2192 A", lambda: self.ping("b"), "outline", "sm").pack(side="right", padx=6)
        Btn(tool, "Ping A \u2192 B", lambda: self.ping("a"), "outline", "sm").pack(side="right")

        self.link = tk.Canvas(session, bg=WHITE, height=108, highlightthickness=1, highlightbackground=LINE)
        self.link.pack(fill="x", pady=(8, 8))
        self.link.bind("<Configure>", lambda e: self.draw_link())

        boxes = tk.Frame(session, bg=WHITE)
        boxes.pack(fill="both", expand=True)
        boxes.columnconfigure(0, weight=1, uniform="b")
        boxes.columnconfigure(1, weight=1, uniform="b")
        boxes.rowconfigure(0, weight=1)
        self.boxes = {"a": InterfaceBox(boxes, lambda t: self.send_message("a", t)),
                      "b": InterfaceBox(boxes, lambda t: self.send_message("b", t))}
        self.boxes["a"].grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.boxes["b"].grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.refresh_session()
        self.rebuild_chips()

    def show_tab(self, which):
        self.tab_net.set_active(which == "network")
        self.tab_con.set_active(which == "connections")
        (self.f_net if which == "network" else self.f_con).tkraise()
        self.draw_topology() if which == "network" else self.draw_link()

    # ================================================================== lifecycle
    def on_show(self):
        self.visible = True
        self.app.refresh_registry(then=self.refresh_views)
        self.periodic_token += 1
        self.app.after(8000, self._periodic, self.periodic_token)

    def on_hide(self):
        self.visible = False

    def _periodic(self, token):
        if self.visible and token == self.periodic_token:
            self.app.refresh_registry(then=self.refresh_views)
            self.app.after(8000, self._periodic, token)

    def on_kicked(self, kicked, closed):
        names = ", ".join(self.net.name(m) for m in kicked)
        self._notify_closed(closed, f"{names} was revoked on the blockchain and removed from the network.")
        self._msg(f"{names} was revoked on the blockchain and removed from the network.", RED)
        self.refresh_views()

    def refresh_views(self):
        """Redraw everything from the shared state (called after any change anywhere in the app)."""
        for conn in self.net.open_connections():           # announce roaming inside open sessions
            for side, mac in (("a", conn["a"]), ("b", conn["b"])):
                cur, prev = self.net.router_of(mac), self.seen_router.get(mac)
                if prev and cur and prev != cur:
                    self._say(conn["id"], side, f"Roamed from {router_label(prev)} to {router_label(cur)}.", "sys")
        for m, r in list(self.net.attached.items()):
            self.seen_router[m] = r
        self._fill_tree()
        self._fill_combos()
        self.draw_topology()
        self.rebuild_chips()
        self.refresh_session()

    # ================================================================== network tab
    def _msg(self, text, color=MUTED):
        self.net_msg.config(text=text, fg=color)

    def _fill_tree(self):
        selected = self._selected_mac()
        self.hover_row = None
        self.tree.delete(*self.tree.get_children())
        if self.app.registry_problem:
            self._msg(self.app.registry_problem, RED)
        for r in self.app.registry:
            mac = r["mac"]
            if not r["auth"]:
                state, tag = "Revoked", "bad"
            elif self.net.is_connected(mac):
                state, tag = "Connected", "ok"
            else:
                state, tag = "Not connected", "off"
            self.tree.insert("", "end", iid=mac, tags=(tag,), values=(
                self.net.name(mac), r["pretty"], self.net.router_of(mac) or "-",
                self.net.ip(mac) or "-", state))
        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected)

    def _tree_hover(self, event):
        row = self.tree.identify_row(event.y) if event else ""
        if row == self.hover_row:
            return
        if self.hover_row and self.tree.exists(self.hover_row):
            self.tree.item(self.hover_row, tags=tuple(t for t in self.tree.item(self.hover_row, "tags") if t != "hover"))
        self.hover_row = row or None
        if row:
            self.tree.item(row, tags=tuple(self.tree.item(row, "tags")) + ("hover",))

    def _pick_row(self, _):
        mac = self._selected_mac()
        if mac:
            self.var_name.set(self.net.name(mac))
        self.draw_topology()

    def _selected_mac(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _describe_join(self, mac, res):
        name = self.net.name(mac)
        if res["ok"]:
            best = next((r for r in res["eval"] if r["id"] == res["router"]), None)
            extra = f" ({best['dist']} m, {best['rssi']} dBm, load {best['load']}/{best['capacity']})" if best else ""
            return f"{name} connected to {router_label(res['router'])} as {res['ip']}{extra}, checked by {res['how']}."
        return f"{name} could not connect: {res['reason']} (checked by {res['how']})."

    def connect_selected(self):
        mac = self._selected_mac()
        if not mac:
            self._msg("Select a device in the table first.", RED)
            return
        row = next((r for r in self.app.registry if r["mac"] == mac), None)
        if row and not row["auth"]:
            self._msg("That device is revoked, so it cannot join the network.", RED)
            return
        name = self.var_name.get().strip()
        if name:
            self.net.set_name(mac, name)
        self._msg("Authenticating with the network...", MUTED)

        def work():
            res = self.net.join(mac, self.be.router_authenticate)
            text = self._describe_join(mac, res)
            self.app.log("Eduroam: " + text)
            self.app.ui(self._msg, text, OK if res["ok"] else RED)
            self.app.ui(self.app.network_changed)
        self.app.bg(work)

    def connect_all(self):
        macs = [r["mac"] for r in self.app.registry if r["auth"] and not self.net.is_connected(r["mac"])]
        if not macs:
            self._msg("Every registered device is already connected.", MUTED)
            return
        self._msg(f"Connecting {len(macs)} device(s)...", MUTED)

        def work():
            ok = 0
            for mac in macs:
                res = self.net.join(mac, self.be.router_authenticate)
                self.app.log("Eduroam: " + self._describe_join(mac, res))
                ok += 1 if res["ok"] else 0
            self.app.ui(self._msg, f"Connected {ok} of {len(macs)} device(s).", OK if ok == len(macs) else RED)
            self.app.ui(self.app.network_changed)
        self.app.bg(work)

    def disconnect_selected(self):
        mac = self._selected_mac()
        if not mac or not self.net.is_connected(mac):
            self._msg("Select a connected device first.", RED)
            return
        label = self.net.name(mac)
        closed = self.net.leave(mac)
        self._notify_closed(closed, f"{label} disconnected from the network.")
        self._msg(f"{label} disconnected from the network.", MUTED)
        self.app.log(f"Eduroam: {label} disconnected.")
        self.app.network_changed()

    def save_name(self):
        mac = self._selected_mac()
        if not mac:
            self._msg("Select a device in the table first.", RED)
            return
        self.net.set_name(mac, self.var_name.get())
        self._msg(f"Saved name: {self.net.name(mac)}", OK)
        self.app.network_changed()

    def _active_path(self):
        conn = self.net.connections.get(self.active_cid) if self.active_cid else None
        if conn and conn["state"] == "open":
            return self.net.path(conn["a"], conn["b"]), conn
        return [], None

    def draw_topology(self):
        c = self.topo
        c.delete("all")
        W, H = max(c.winfo_width(), 420), max(c.winfo_height(), 280)
        cx, cy = W / 2, H / 2 + 6
        rx, ry = min(W * 0.30, 150), min(H * 0.25, 86)
        pos = {}
        for i, r in enumerate(ed.ROUTERS):
            ang = math.radians(-90 + 72 * i)
            pos[r["id"]] = (cx + rx * math.cos(ang), cy + ry * math.sin(ang), math.cos(ang), math.sin(ang))
        path, conn = self._active_path()
        hot = {frozenset(path)} if len(path) == 2 else set()
        ids = [r["id"] for r in ed.ROUTERS]
        for i, a in enumerate(ids):                                # the full mesh: every router to every other
            for b in ids[i + 1:]:
                on = frozenset((a, b)) in hot
                c.create_line(pos[a][0], pos[a][1], pos[b][0], pos[b][1], fill=RED if on else RED_MID,
                              width=3 if on else 1)
        c.create_text(cx, cy, text="eduroam\nmesh", font=(FONT, 9, "bold"), fill=OFF, justify="center")
        selected = self._selected_mac()
        for r in ed.ROUTERS:
            x, y, ux, uy = pos[r["id"]]
            load = self.net.load(r["id"])
            round_rect(c, x - 52, y - 20, x + 52, y + 20, 10, fill=RED if load else WHITE,
                       outline=RED_DARK if r["id"] in path else RED, width=3 if r["id"] in path else 2)
            c.create_text(x, y - 6, text=f"{r['id']}  {r['name']}", font=(FONT, 9, "bold"), fill=WHITE if load else RED_DARK)
            c.create_text(x, y + 8, text=f"{load}/{r['capacity']} devices", font=(FONT, 8), fill=WHITE if load else MUTED)
            macs = sorted((m for m, rid in self.net.attached.items() if rid == r["id"]), key=self.net.name)
            bx, by = x + ux * 38, y + uy * 34
            vx, vy = -uy, ux
            shown = macs[:10]
            for k, m in enumerate(shown):
                row, col = k // 5, k % 5
                n_in = min(5, len(shown) - row * 5)
                off = (col - (n_in - 1) / 2) * 15
                dx, dy = bx + ux * row * 15 + vx * off, by + uy * row * 15 + vy * off
                c.create_line(x + ux * 20, y + uy * 14, dx, dy, fill=RED_MID)
                is_end = conn and m in (conn["a"], conn["b"])
                c.create_oval(dx - 5, dy - 5, dx + 5, dy + 5, fill=RED if is_end else OK, outline=WHITE, width=1)
                if m == selected:
                    c.create_oval(dx - 9, dy - 9, dx + 9, dy + 9, outline=RED_DARK, width=2)
            if len(macs) > 10:
                c.create_text(bx + ux * 40, by + uy * 40, text=f"+{len(macs) - 10}", font=(FONT, 8), fill=MUTED)
        c.create_text(12, H - 14, anchor="w", font=(FONT, 8), fill=MUTED,
                      text="\u25cf device     \u2500 mesh link     red = path of the selected connection")

    # ================================================================== connections tab
    def _cmsg(self, text, color=MUTED):
        self.con_msg.config(text=text, fg=color)

    def _fill_combos(self):
        prev = []
        for cb in (self.cb_a, self.cb_b):
            i = cb.current()
            prev.append(self.combo_macs[i] if 0 <= i < len(self.combo_macs) else None)
        reg = {r["mac"] for r in self.app.registry if r["auth"]}
        macs = [m for m in self.net.attached if m in reg]
        self.combo_macs = sorted(macs, key=lambda m: self.net.name(m).lower())
        values = [f"{self.net.name(m)}   ({self.net.router_of(m)} \u00b7 {self.net.ip(m)})" for m in self.combo_macs]
        for cb, p in zip((self.cb_a, self.cb_b), prev):
            cb.config(values=values)
            if p in self.combo_macs:
                cb.current(self.combo_macs.index(p))
            else:
                cb.set("")

    def establish(self):
        ia, ib = self.cb_a.current(), self.cb_b.current()
        if ia < 0 or ib < 0:
            self._cmsg("Choose Device A and Device B first (only connected devices are listed).", RED)
            return
        a, b = self.combo_macs[ia], self.combo_macs[ib]
        try:
            conn = self.net.open_connection(a, b)
        except ValueError as e:
            self._cmsg(str(e), RED)
            return
        self._opened(conn)

    def _opened(self, conn):
        cid, a, b = conn["id"], conn["a"], conn["b"]
        route = " \u2192 ".join(self.net.path(a, b))
        if cid not in self.transcripts:
            self.transcripts[cid] = {"a": [], "b": []}
            for side, me, peer in (("a", a, b), ("b", b, a)):
                self._say(cid, side, f"Connected as {self.net.ip(me)} via {router_label(self.net.router_of(me))}.", "sys")
                self._say(cid, side, f"Link to {self.net.name(peer)} ({self.net.ip(peer)}) is open. Route: {route}", "sys")
        self._cmsg(f"Connection open: {self.net.name(a)} \u21c4 {self.net.name(b)} ({route}). "
                   "Type in either box, or use Ping and Run demo.", OK)
        self.app.log(f"Eduroam: connection opened between {self.net.name(a)} and {self.net.name(b)}.")
        self.select_connection(cid)

    def rebuild_chips(self):
        for w in self.chip_row.winfo_children():
            w.destroy()
        tk.Label(self.chip_row, text="Active connections", font=(FONT, 9, "bold"), fg=MUTED, bg=WHITE).pack(side="left", padx=(0, 10))
        conns = self.net.open_connections()
        if not conns:
            tk.Label(self.chip_row, text="none yet", font=(FONT, 9), fg=OFF, bg=WHITE).pack(side="left")
        for c in conns:
            cid = c["id"]
            Btn(self.chip_row, f"{self.net.name(c['a'])}  \u21c4  {self.net.name(c['b'])}",
                lambda x=cid: self.select_connection(x), "primary" if cid == self.active_cid else "outline", "sm"
                ).pack(side="left", padx=4)

    def select_connection(self, cid):
        self.active_cid = cid
        data = self.transcripts.get(cid, {"a": [], "b": []})
        for side in ("a", "b"):
            self.boxes[side].clear()
            for stamp, text, tag in data[side]:
                self.boxes[side].write(text, tag, stamp)
        self.rebuild_chips()
        self.refresh_session()
        self.draw_topology()

    def refresh_session(self):
        conn = self.net.connections.get(self.active_cid) if self.active_cid else None
        if not conn:
            self.session_title.config(text="No connection selected")
            self.stats.config(text="")
            self.boxes["a"].set_device("Device A", "", "", "", False)
            self.boxes["b"].set_device("Device B", "", "", "", False)
        else:
            a, b, up = conn["a"], conn["b"], conn["state"] == "open"
            self.session_title.config(text=f"{self.net.name(a)}  \u21c4  {self.net.name(b)}")
            self.stats.config(text=f"{'OPEN' if up else 'CLOSED'}   sent {conn['sent']}  \u00b7  delivered "
                                   f"{conn['delivered']}  \u00b7  dropped {conn['dropped']}", fg=OK if up else RED)
            for side, mac in (("a", a), ("b", b)):
                self.boxes[side].set_device(f"{self.net.name(mac)}   ({side.upper()})", self.net.ip(mac), core.pretty_mac(mac),
                                            router_label(self.net.router_of(mac)) if self.net.is_connected(mac) else "",
                                            up and self.net.is_connected(mac))
        self.draw_link()

    def _say(self, cid, side, text, tag=""):
        stamp = time.strftime("%H:%M:%S")
        data = self.transcripts.setdefault(cid, {"a": [], "b": []})
        for s in (("a", "b") if side == "both" else (side,)):
            data[s].append((stamp, text, tag))
            if cid == self.active_cid:
                self.boxes[s].write(text, tag, stamp)

    def _notify_closed(self, cids, text):
        for cid in cids:
            self._say(cid, "both", "Connection closed: " + text, "err")
        self.rebuild_chips()
        self.refresh_session()

    def close_active(self):
        conn = self.net.connections.get(self.active_cid) if self.active_cid else None
        if not conn or conn["state"] != "open":
            self._cmsg("There is no open connection selected.", RED)
            return
        self.demo_token += 1
        self.net.close_connection(conn["id"])
        self._say(conn["id"], "both", "Connection closed by user.", "err")
        self._cmsg("Connection closed.", MUTED)
        self.app.log("Eduroam: connection closed.")
        self.rebuild_chips()
        self.refresh_session()
        self.draw_topology()

    def clear_screens(self):
        if self.active_cid is None:
            return
        self.transcripts[self.active_cid] = {"a": [], "b": []}
        for b in self.boxes.values():
            b.clear()

    def _open_conn(self):
        conn = self.net.connections.get(self.active_cid) if self.active_cid else None
        if not conn or conn["state"] != "open":
            self._cmsg("Establish or select an open connection first.", RED)
            return None
        return conn

    # ---- traffic
    def send_message(self, side, text):
        conn = self._open_conn()
        if not conn:
            return
        cid = conn["id"]
        src = conn["a"] if side == "a" else conn["b"]
        self._say(cid, side, f"\u2192 {text}", "tx")

        def deliver(p):
            res = p["verdict"]
            route = " \u2192 ".join(res["path"])
            self._say(cid, other(side), f"\u2190 {text}   (from {res['src_ip']})", "rx")
            self._say(cid, side, f"\u2713 delivered  #{res['seq']}  time={res['ms']} ms  route {route}", "sys")
            self.refresh_session()
        p = self._new_packet(cid, side, text if len(text) <= 14 else text[:13] + "\u2026", "msg", on_deliver=deliver)
        self._forward_async(p, src, True, "message", text)

    def _forward_async(self, p, src, check, kind, payload, size=None):
        def work():
            res = self.net.forward(p["cid"], src, self.be.ledger_allows if check else None, kind, payload, size)
            self.app.ui(self._set_verdict, p, res)
        self.app.bg(work)

    def _set_verdict(self, p, res):
        p["verdict"] = res

    def ping(self, side):
        conn = self._open_conn()
        if not conn:
            return
        cid = conn["id"]
        src, dst = (conn["a"], conn["b"]) if side == "a" else (conn["b"], conn["a"])
        dst_ip = self.net.ip(dst)
        st = {"recv": 0, "lost": 0}
        self._say(cid, side, f"PING {dst_ip} with 32 bytes of data:", "sys")

        def summary():
            if st["recv"] + st["lost"] == 4:
                self._say(cid, side, f"Ping statistics: 4 sent, {st['recv']} received, {st['lost']} lost", "sys")

        def one(i):
            c = self.net.connections.get(cid)
            if not c or c["state"] != "open":
                if i:
                    st["lost"] += 1
                    summary()
                return

            def echo_arrived(p):
                res = p["verdict"]
                self._say(cid, other(side), f"\u2190 ICMP echo request from {res['src_ip']}", "rx")

                def reply_arrived(q):
                    st["recv"] += 1
                    route = " \u2192 ".join(res["path"])
                    self._say(cid, side, f"Reply from {dst_ip}: bytes=32 time={res['ms']}ms TTL=63 route {route}", "rx")
                    self.refresh_session()
                    summary()
                q = self._new_packet(cid, other(side), "reply", "reply", on_deliver=reply_arrived)
                self._forward_async(q, dst, False, "icmp-reply", "ICMP echo reply (32 bytes)", 60)

            def echo_dropped(p):
                st["lost"] += 1
                self._say(cid, side, f"Request timed out. ({p['verdict'].get('reason', 'dropped')})", "err")
                self._after_drop(p)
                summary()
            p = self._new_packet(cid, side, "ping", "icmp", on_deliver=echo_arrived, on_drop=echo_dropped)
            self._forward_async(p, src, True, "icmp-echo", "ICMP echo request (32 bytes)", 60)

        for i in range(4):
            self.app.after(int(i * 900), one, i)

    def run_demo(self):
        conn = self._open_conn()
        if not conn:
            return
        self.demo_token += 1
        token, cid = self.demo_token, conn["id"]
        a, b = self.net.name(conn["a"]), self.net.name(conn["b"])
        script = [(0.0, "a", f"Hello {b}! This is {a}. Can you hear me?"),
                  (2.2, "b", f"Loud and clear, {a}. The mesh link looks good."),
                  (2.4, "a", "/ping"),
                  (5.4, "b", "Sending you a status update: all sensors OK."),
                  (2.4, "a", "Received. Thanks!"),
                  (2.2, "b", f"Talk soon, {a}.")]
        self._say(cid, "both", "--- demo conversation started ---", "sys")
        t = 0.0
        for delay, side, text in script:
            t += delay

            def step(side=side, text=text):
                c = self.net.connections.get(cid)
                if token != self.demo_token or not c or c["state"] != "open":
                    return
                self.ping(side) if text == "/ping" else self.send_message(side, text)
            self.app.after(int(t * 1000), step)

    # ---- packet animation
    def _new_packet(self, cid, src_side, label, kind, on_deliver=None, on_drop=None):
        conn = self.net.connections.get(cid)
        nseg = (len(self.net.path(conn["a"], conn["b"])) + 1) if conn else 2
        p = {"cid": cid, "src": src_side, "label": label, "kind": kind, "phase": "leg", "leg": 0, "nseg": max(nseg, 2),
             "inspected": False, "t0": time.time(), "verdict": None, "min_inspect": 0.1 if kind == "reply" else 0.35,
             "on_deliver": on_deliver, "on_drop": on_drop}
        self.pkts.append(p)
        if not self.ticking:
            self.ticking = True
            self.app.after(30, self._tick)
        return p

    def _tick(self):
        now = time.time()
        alive = []
        for p in self.pkts:
            el, ph = now - p["t0"], p["phase"]
            if ph == "leg" and el >= self.DUR_LEG:
                if p["leg"] == 0 and not p["inspected"]:
                    p["phase"], p["t0"] = "inspect", now
                elif p["leg"] < p["nseg"] - 1:
                    p["leg"] += 1
                    p["t0"] = now
                else:
                    p["phase"] = "done"
                    if p["on_deliver"]:
                        p["on_deliver"](p)
            elif ph == "inspect" and p["verdict"] is not None and el >= p["min_inspect"]:
                p["t0"] = now
                if p["verdict"]["ok"]:
                    p["inspected"], p["phase"], p["leg"] = True, "leg", 1
                else:
                    p["phase"] = "drop"
                    (p["on_drop"] or self._default_drop)(p)
            elif ph == "drop" and el >= self.DUR_DROP:
                p["phase"] = "done"
            if p["phase"] != "done":
                alive.append(p)
        self.pkts = alive
        self.draw_link()
        if alive:
            self.app.after(30, self._tick)
        else:
            self.ticking = False

    def _default_drop(self, p):
        self._say(p["cid"], p["src"], f"\u2717 Dropped: {p['verdict'].get('reason', 'dropped')}", "err")
        self._after_drop(p)

    def _after_drop(self, p):
        res = p["verdict"]
        if res.get("closed"):
            self.app.log("Eduroam: " + res.get("reason", "device removed"))
            self._notify_closed(res["closed"], res.get("reason", "device removed"))
            self.app.network_changed()
        self.refresh_session()

    def draw_link(self):
        c = self.link
        c.delete("all")
        W, H = max(c.winfo_width(), 520), max(c.winfo_height(), 96)
        conn = self.net.connections.get(self.active_cid) if self.active_cid else None
        if not conn:
            c.create_text(W / 2, H / 2, text="Establish or select a connection to watch live traffic here.",
                          font=(FONT, 10), fill=MUTED)
            return
        up = conn["state"] == "open"
        path = self.net.path(conn["a"], conn["b"]) if up else []
        nodes = [("dev", conn["a"])] + [("rt", r) for r in path] + [("dev", conn["b"])]
        n = len(nodes)
        cy, nh = H / 2 + 4, 50
        half = {"dev": 70, "rt": 62}
        margin = 78
        xs = [margin + (W - 2 * margin) * i / (n - 1) for i in range(n)]
        for i in range(n - 1):
            x1, x2 = xs[i] + half[nodes[i][0]], xs[i + 1] - half[nodes[i + 1][0]]
            c.create_line(x1, cy, x2, cy, fill=RED if up else LINE, width=2, dash=() if up else (5, 4))
            if nodes[i][0] == "rt" and nodes[i + 1][0] == "rt":
                c.create_text((x1 + x2) / 2, cy + 12, text="mesh", font=(FONT, 8), fill=MUTED)
        checking = any(p["cid"] == conn["id"] and p["phase"] == "inspect" for p in self.pkts)
        for i, (kind, ident) in enumerate(nodes):
            x, w = xs[i], half[kind]
            if kind == "dev":
                live = up and self.net.is_connected(ident)
                outline, fill, tc, sc = (OK if live else RED), WHITE, INK, MUTED
                title, sub = self.net.name(ident)[:16], self.net.ip(ident)
            else:
                r = ed.ROUTER_BY_ID[ident]
                outline, fill, tc, sc = RED_DARK, RED, WHITE, WHITE
                title = f"{ident} {r['name']}"
                sub = "checking ledger..." if (checking and i == 1) else f"{self.net.load(ident)}/{r['capacity']} devices"
            round_rect(c, x - w, cy - nh / 2, x + w, cy + nh / 2, 10, fill=fill, outline=outline, width=2)
            c.create_text(x, cy - 8, text=title, font=(FONT, 9, "bold"), fill=tc)
            c.create_text(x, cy + 11, text=sub, font=("Consolas", 8), fill=sc)

        def bubble(x, y, label, fill):
            bw = 7 * len(label) + 20
            round_rect(c, x - bw / 2, y - 12, x + bw / 2, y + 12, 9, fill=fill, outline="")
            c.create_text(x, y, text=label, font=(FONT, 8, "bold"), fill=WHITE)
        for p in self.pkts:
            if p["cid"] != conn["id"]:
                continue
            order = list(range(n)) if p["src"] == "a" else list(range(n - 1, -1, -1))
            ph = p["phase"]
            leg = min(p["leg"], n - 2)
            right = p["src"] == "a"
            i, j = order[leg], order[leg + 1]
            start = xs[i] + (half[nodes[i][0]] if right else -half[nodes[i][0]])
            end = xs[j] - (half[nodes[j][0]] if right else -half[nodes[j][0]])
            col = {"msg": RED, "icmp": RED_DARK, "reply": OK}[p["kind"]]
            if p["inspected"] and p["kind"] != "reply":
                col = OK
            if ph == "leg":
                e = self._ease((time.time() - p["t0"]) / self.DUR_LEG)
                bubble(start + (end - start) * e, cy - 34, p["label"], col)
            elif ph == "inspect":
                bubble(end, cy - 34, p["label"], col)
            elif ph == "drop":
                bx = xs[order[1]]
                c.create_oval(bx - 15, cy - 54, bx + 15, cy - 24, fill=RED, outline=WHITE, width=2)
                c.create_text(bx, cy - 40, text="\u2717", font=(FONT, 13, "bold"), fill=WHITE)

    @staticmethod
    def _ease(p):
        p = max(0.0, min(1.0, p))
        return p * p * (3 - 2 * p)
