"""NewLAN - blockchain-secured network access control.

Double-click this file (or "Start NewLAN.bat") to open the app.
All the logic lives in newlan_core.py; this file only draws the interface.
"""
import queue
import re
import sys
import threading
import time
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import newlan_core as core  # noqa: E402
import newlan_eduroam as ed  # noqa: E402
from newlan_eduroam import EduroamNet  # noqa: E402
from newlan_eduroam_ui import EduroamPage  # noqa: E402
from newlan_packets_ui import PacketsPage  # noqa: E402
from newlan_router_ui import RouterPage  # noqa: E402
from newlan_widgets import (INK, LINE, MUTED, OFF, OK, PANEL, RED, RED_DARK, RED_MID, RED_SOFT, WARN, WHITE,  # noqa: E402
                            FONT, Btn, NavItem, StatusCard, make_entry, page_header, round_rect)

# ------------------------------------------------------------------ theme


def enable_dpi_awareness():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def ensure_dependencies():
    """Install web3 / py-solc-x automatically on first launch."""
    try:
        import solcx  # noqa: F401
        import web3  # noqa: F401
        return True
    except ImportError:
        pass
    splash = tk.Tk()
    splash.title("NewLAN - first-time setup")
    splash.geometry("380x110")
    splash.configure(bg=WHITE)
    tk.Label(splash, text="NewLAN", font=(FONT, 16, "bold"), fg=RED, bg=WHITE).pack(pady=(14, 2))
    tk.Label(splash, text="Installing required Python packages (one time, about a minute)...",
             fg=MUTED, bg=WHITE).pack()
    splash.update()
    try:
        r = subprocess.run([core.python_exe(), "-m", "pip", "install", "-r", str(HERE / "requirements.txt")],
                           capture_output=True, text=True, creationflags=core.NO_WINDOW)
    finally:
        splash.destroy()
    if r.returncode != 0:
        messagebox.showerror("Setup failed", "Could not install packages (is the internet on?):\n\n"
                             + r.stdout[-800:] + r.stderr[-800:])
        return False
    import importlib
    importlib.invalidate_caches()
    return True


# ------------------------------------------------------------------ application
class App(tk.Tk):
    SIDEBAR_W = 250
    PAGES = [("home", "\u2302", "Home"), ("devices", "\u25a4", "Devices"), ("router", "\u21c4", "Router"),
             ("eduroam", "\u25ce", "Eduroam testbed"), ("packets", "\u25a5", "Packet store"),
             ("test", "\u27a4", "Test login"), ("activity", "\u2261", "Activity log"), ("settings", "\u2699", "Settings")]
    PAGE_TITLES = {"home": "Home", "devices": "Devices", "router": "Router", "eduroam": "Eduroam testbed",
                   "packets": "Packet store", "test": "Test login", "activity": "Activity log", "settings": "Settings"}
    LIVE_PAGES = ("router", "eduroam", "packets")      # pages that refresh while they are on screen

    def __init__(self):
        super().__init__()
        self.title("NewLAN")
        self.geometry("1080x740")
        self.minsize(960, 680)
        self.configure(bg=WHITE)

        self.ui_queue = queue.Queue()
        self.task_running = False
        self.polling = False
        self.sidebar_open = False
        self._sx = -self.SIDEBAR_W
        self.anim = None
        self.service_btns = []
        self.hover_row = None
        self.current_page = "home"

        self.be = core.Backend(self.log, self.notify)
        self.net = EduroamNet()
        self.registry = []              # devices on the ledger: {mac, pretty, auth}
        self.registry_problem = ""
        self._registry_busy = False
        self._style()
        self._build_shell()
        self.pages = {}
        for builder in (self._build_home, self._build_devices, self._build_router, self._build_eduroam, self._build_packets,
                        self._build_test, self._build_activity, self._build_settings):
            builder()
        self.show_page("home")

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Escape>", lambda e: self.close_sidebar())
        self.bind_all("<Button-1>", self._click_away, add="+")
        self.after(100, self._drain_queue)
        self.after(300, self._poll_loop)
        self.after(3000, self._net_watch)
        self.log("NewLAN is ready. Press Start on the Home page.")

    # ---- plumbing
    def ui(self, fn, *a):
        self.ui_queue.put((fn, a))

    def _drain_queue(self):
        try:
            while True:
                fn, a = self.ui_queue.get_nowait()
                fn(*a)
        except queue.Empty:
            pass
        self.after(100, self._drain_queue)

    def bg(self, fn, *a):
        def wrapper():
            try:
                fn(*a)
            except Exception as e:
                self.log(f"Error: {e}")
        threading.Thread(target=wrapper, daemon=True).start()

    def run_task(self, name, fn, *a):
        if self.task_running:
            self.log("Please wait, another task is still running.")
            return

        def wrapper():
            self.task_running = True
            self.ui(self._set_busy, True)
            self.log(f"--- {name} ---")
            try:
                fn(*a)
            except Exception as e:
                self.log(f"Error during {name}: {e}")
            finally:
                self.task_running = False
                self.ui(self._set_busy, False)
                self.ui(self.request_poll)
        threading.Thread(target=wrapper, daemon=True).start()

    def notify(self, title, message):
        self.ui(lambda: messagebox.showinfo(title, message))

    def log(self, text):
        self.ui(self._append_log, f"{time.strftime('%H:%M:%S')}  {text}\n")

    # ---- styling
    def _style(self):
        st = ttk.Style(self)
        if "clam" in st.theme_names():
            st.theme_use("clam")
        st.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        st.configure("Treeview", background=WHITE, fieldbackground=WHITE, foreground=INK, rowheight=36,
                     borderwidth=0, font=(FONT, 10))
        st.configure("Treeview.Heading", background=RED_SOFT, foreground=RED_DARK, font=(FONT, 9, "bold"),
                     relief="flat", padding=(12, 9), borderwidth=0)
        st.map("Treeview.Heading", background=[("active", RED_MID)])
        st.map("Treeview", background=[("selected", RED)], foreground=[("selected", WHITE)])
        st.layout("Compact.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        st.configure("Compact.Treeview", background=WHITE, fieldbackground=WHITE, foreground=INK, rowheight=27,
                     borderwidth=0, font=(FONT, 9))
        st.configure("Compact.Treeview.Heading", background=RED_SOFT, foreground=RED_DARK, font=(FONT, 8, "bold"),
                     relief="flat", padding=(10, 6), borderwidth=0)
        st.map("Compact.Treeview.Heading", background=[("active", RED_MID)])
        st.map("Compact.Treeview", background=[("selected", RED)], foreground=[("selected", WHITE)])
        st.configure("Red.Horizontal.TProgressbar", troughcolor=RED_SOFT, background=RED, bordercolor=RED_SOFT,
                     lightcolor=RED, darkcolor=RED)
        st.configure("Vertical.TScrollbar", background=RED_MID, troughcolor=WHITE, bordercolor=WHITE,
                     arrowcolor=RED_DARK, relief="flat")
        st.map("Vertical.TScrollbar", background=[("active", RED)])
        st.configure("TCombobox", fieldbackground=WHITE, background=RED_SOFT, foreground=INK, bordercolor=LINE,
                     arrowcolor=RED, padding=6)
        st.map("TCombobox", fieldbackground=[("readonly", WHITE)], selectbackground=[("readonly", WHITE)],
               selectforeground=[("readonly", INK)], bordercolor=[("focus", RED)], arrowcolor=[("active", RED_DARK)])
        self.option_add("*TCombobox*Listbox.background", WHITE)
        self.option_add("*TCombobox*Listbox.foreground", INK)
        self.option_add("*TCombobox*Listbox.selectBackground", RED)
        self.option_add("*TCombobox*Listbox.selectForeground", WHITE)
        self.option_add("*TCombobox*Listbox.font", (FONT, 10))

    # ---- shell: top bar, pages, sliding sidebar
    def _build_shell(self):
        top = tk.Frame(self, bg=RED, height=58)
        top.pack(fill="x")
        top.pack_propagate(False)
        self.burger = tk.Label(top, text="\u2630", fg=WHITE, bg=RED, font=(FONT, 18), padx=20, cursor="hand2")
        self.burger.pack(side="left", fill="y")
        self.burger.bind("<Enter>", lambda e: self.burger.config(bg=RED_DARK))
        self.burger.bind("<Leave>", lambda e: self.burger.config(bg=RED))
        self.burger.bind("<Button-1>", lambda e: self.toggle_sidebar())
        tk.Label(top, text="NewLAN", fg=WHITE, bg=RED, font=(FONT, 17, "bold")).pack(side="left", padx=(4, 0))
        self.crumb = tk.Label(top, text="", fg=RED_MID, bg=RED, font=(FONT, 11))
        self.crumb.pack(side="left", padx=10)
        self.top_chip = tk.Label(top, text="\u25cf  Checking", fg=MUTED, bg=WHITE, font=(FONT, 9, "bold"), padx=14, pady=5)
        self.top_chip.pack(side="right", padx=18)

        self.body = tk.Frame(self, bg=WHITE)
        self.body.pack(fill="both", expand=True)
        self.page_host = tk.Frame(self.body, bg=WHITE)
        self.page_host.place(x=0, y=0, relwidth=1, relheight=1)

        self.sidebar = tk.Frame(self.body, bg=WHITE, highlightthickness=1, highlightbackground=LINE)
        self.sidebar.place(x=-self.SIDEBAR_W, y=0, width=self.SIDEBAR_W, relheight=1)
        head = tk.Frame(self.sidebar, bg=WHITE)
        head.pack(fill="x", padx=22, pady=(24, 16))
        tk.Label(head, text="NewLAN", font=(FONT, 20, "bold"), fg=RED, bg=WHITE).pack(anchor="w")
        tk.Label(head, text="Network access control", font=(FONT, 9), fg=MUTED, bg=WHITE).pack(anchor="w")
        tk.Frame(self.sidebar, bg=LINE, height=1).pack(fill="x")
        self.nav = {}
        for key, icon, text in self.PAGES:
            item = NavItem(self.sidebar, icon, text, lambda k=key: self.show_page(k, close=True))
            item.pack(fill="x", pady=(6, 0) if key == "home" else 0)
            self.nav[key] = item
        tk.Label(self.sidebar, text="Esc or click outside to close", font=(FONT, 8), fg=OFF, bg=WHITE
                 ).pack(side="bottom", pady=14)

    def show_page(self, key, close=False):
        if self.current_page in self.LIVE_PAGES and key != self.current_page:
            getattr(self, self.current_page + "_page").on_hide()
        self.current_page = key
        self.pages[key].tkraise()
        for k, item in self.nav.items():
            item.set_active(k == key)
        self.crumb.config(text="" if key == "home" else f"/   {self.PAGE_TITLES[key]}")
        if key == "devices":
            self.refresh_devices()
        if key == "activity":
            self.logbox.see("end")
        if key in self.LIVE_PAGES:
            getattr(self, key + "_page").on_show()
        if close:
            self.close_sidebar()
        self.sidebar.lift()

    def toggle_sidebar(self):
        self.close_sidebar() if self.sidebar_open else self.open_sidebar()

    def open_sidebar(self):
        self.sidebar_open = True
        self.sidebar.lift()
        self._slide(0)

    def close_sidebar(self):
        if self.sidebar_open:
            self.sidebar_open = False
            self._slide(-self.SIDEBAR_W)

    def _slide(self, target):
        start, steps = self._sx, 10

        def step(i):
            ease = 1 - (1 - i / steps) ** 3
            self._sx = start + (target - start) * ease
            self.sidebar.place_configure(x=int(self._sx))
            if i < steps:
                self.after(14, step, i + 1)
        step(1)

    def _click_away(self, event):
        if not self.sidebar_open or event.widget is self.burger:
            return
        if not str(event.widget).startswith(str(self.sidebar)):
            self.close_sidebar()

    def _new_page(self, key):
        f = tk.Frame(self.page_host, bg=WHITE)
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.pages[key] = f
        return f

    # ---- HOME
    def _build_home(self):
        f = self._new_page("home")
        hero = tk.Frame(f, bg=WHITE)
        hero.pack(pady=(30, 6))
        tk.Label(hero, text="NewLAN", font=(FONT, 54, "bold"), fg=RED, bg=WHITE).pack()
        tk.Label(hero, text="Blockchain-secured network access control", font=(FONT, 13), fg=MUTED, bg=WHITE).pack()
        self.home_chip = tk.Label(hero, text="\u25cf  Checking...", font=(FONT, 10, "bold"), fg=MUTED, bg=PANEL,
                                  padx=16, pady=6, highlightthickness=1, highlightbackground=LINE)
        self.home_chip.pack(pady=(16, 0))

        row = tk.Frame(hero, bg=WHITE)
        row.pack(pady=(22, 10))
        start = Btn(row, "\u25b6   Start", lambda: self.run_task("Start", self.be.start_all), "primary", "lg")
        stop = Btn(row, "\u25a0   Stop", lambda: self.run_task("Stop", self.be.stop_all), "outline", "lg")
        start.pack(side="left")
        stop.pack(side="left", padx=14)
        self.service_btns += [start, stop]

        slot = tk.Frame(hero, bg=WHITE, height=8, width=360)
        slot.pack()
        slot.pack_propagate(False)
        self.progress = ttk.Progressbar(slot, mode="indeterminate", style="Red.Horizontal.TProgressbar")
        self.latest = tk.StringVar(value="")
        tk.Label(hero, textvariable=self.latest, font=(FONT, 9), fg=MUTED, bg=WHITE, wraplength=640).pack(pady=(8, 0))

        cards = tk.Frame(f, bg=WHITE)
        cards.pack(fill="x", padx=36, pady=(26, 0))
        self.cards = {}
        for i, (key, title) in enumerate((("ganache", "Blockchain"), ("contract", "Smart contract"),
                                          ("docker", "Docker"), ("radius", "RADIUS server"))):
            cards.columnconfigure(i, weight=1, uniform="c")
            card = StatusCard(cards, title)
            card.grid(row=0, column=i, sticky="nsew", padx=6)
            self.cards[key] = card

        adv = tk.Frame(f, bg=WHITE)
        adv.pack(pady=(26, 0))
        tk.Label(adv, text="Advanced", font=(FONT, 9, "bold"), fg=MUTED, bg=WHITE).pack()
        arow = tk.Frame(adv, bg=WHITE)
        arow.pack(pady=(8, 0))
        for text, cmd in (("Deploy / redeploy contract", self.on_deploy),
                          ("Install Ganache", lambda: self.run_task("Install Ganache", self.be.install_ganache))):
            b = Btn(arow, text, cmd, "outline", "sm")
            b.pack(side="left", padx=5)
            self.service_btns.append(b)
        Btn(arow, "View server log", self.on_view_server_log, "outline", "sm").pack(side="left", padx=5)

    def _set_busy(self, busy):
        for b in self.service_btns:
            b.set_enabled(not busy)
        if busy:
            self.progress.pack(fill="x")
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.pack_forget()

    def on_deploy(self):
        if self.be.status.get("address") and not messagebox.askyesno(
                "Redeploy contract?",
                "A contract is already deployed.\n\nRedeploying creates a NEW contract with an empty device "
                "list. Continue?"):
            return
        self.run_task("Deploy contract", self.be.deploy)

    def on_view_server_log(self):
        self.show_page("activity")
        self.bg(self.be.show_radius_log)

    # ---- status
    def request_poll(self):
        if not self.polling:
            self.bg(self._poll_once)

    def _poll_loop(self):
        self.request_poll()
        self.after(4000, self._poll_loop)

    def _poll_once(self):
        self.polling = True
        try:
            st = self.be.poll()
            self.ui(self.apply_status, st)
        finally:
            self.polling = False

    def apply_status(self, st):
        s = self.be.settings
        c = self.cards
        if st["ganache"]:
            c["ganache"].set(OK, f"Running at {s['rpc_url']}")
        else:
            c["ganache"].set(RED, "Not running")
        if not st["ganache"]:
            c["contract"].set(OFF, "Waiting for blockchain")
        elif st["address"]:
            a = st["address"]
            c["contract"].set(OK, f"Deployed\n{a[:10]}...{a[-6:]}")
        elif st["info_exists"]:
            c["contract"].set(WARN, "Saved contract not found on this chain. Deploy again.")
        else:
            c["contract"].set(WARN, "Not deployed yet")
        if st["docker"] == "missing":
            c["docker"].set(RED, "Not installed")
        elif st["docker"] == "stopped":
            c["docker"].set(RED, "Installed but not running. Open Docker Desktop.")
        else:
            c["docker"].set(OK, "Running")
        cs = st["container"]
        if cs == "running":
            c["radius"].set(OK, f"Running on UDP {s['radius_port']}")
        elif cs is None:
            c["radius"].set(OFF, "Unavailable")
        elif cs == "none":
            c["radius"].set(OFF, "Not started")
        else:
            c["radius"].set(WARN, f"Container state: {cs}")

        up = st["ganache"] and st["address"] and st["docker"] == "ok" and cs == "running"
        any_up = st["ganache"] or cs == "running"
        if up:
            text, color = "\u25cf  All systems running", OK
        elif any_up:
            text, color = "\u25cf  Partly running", WARN
        else:
            text, color = "\u25cf  Stopped", MUTED
        self.home_chip.config(text=text, fg=color)
        self.top_chip.config(text=text.replace("All systems running", "Online"), fg=color)

    # ---- DEVICES
    def _build_devices(self):
        f = self._new_page("devices")
        page_header(f, "Devices", "MAC addresses allowed on the network. Changes are written to the smart contract.")
        card = tk.Frame(f, bg=WHITE, highlightthickness=1, highlightbackground=LINE, padx=16, pady=14)
        card.pack(fill="x", padx=36)
        row = tk.Frame(card, bg=WHITE)
        row.pack(fill="x")
        self.var_mac = tk.StringVar()
        e = make_entry(row, self.var_mac)
        e.pack(side="left", fill="x", expand=True, ipady=6)
        e.bind("<Return>", lambda ev: self.device_action("register"))
        Btn(row, "Register", lambda: self.device_action("register"), "primary").pack(side="left", padx=(12, 4))
        Btn(row, "Revoke", lambda: self.device_action("revoke"), "outline").pack(side="left", padx=4)
        Btn(row, "Check", self.device_check, "outline").pack(side="left", padx=4)
        prow = tk.Frame(card, bg=WHITE)
        prow.pack(fill="x", pady=(10, 0))
        tk.Label(prow, text="Position when registered", font=(FONT, 9, "bold"), fg=INK, bg=WHITE).pack(side="left")
        self.var_px, self.var_py, self.var_pz = tk.StringVar(), tk.StringVar(), tk.StringVar()
        for label, var in (("X", self.var_px), ("Y", self.var_py), ("Z", self.var_pz)):
            tk.Label(prow, text=label, font=(FONT, 9, "bold"), fg=RED, bg=WHITE).pack(side="left", padx=(12, 3))
            make_entry(prow, var, width=6).pack(side="left", ipady=3)
        tk.Label(prow, text=f"metres (X 0-{ed.SPACE[0]:g}, Y 0-{ed.SPACE[1]:g}, Z 0-{ed.SPACE[2]:g}).  Leave blank for a random spot.",
                 font=(FONT, 8), fg=MUTED, bg=WHITE).pack(side="left", padx=10)
        self.dev_msg = tk.Label(card, text="Format: AA-BB-CC-DD-EE-FF (colons or no separators also work). "
                                           "Click a row to select it.", font=(FONT, 9), fg=MUTED, bg=WHITE, anchor="w")
        self.dev_msg.pack(fill="x", pady=(10, 0))

        wrap = tk.Frame(f, bg=WHITE, highlightthickness=1, highlightbackground=LINE)
        wrap.pack(fill="both", expand=True, padx=36, pady=(14, 0))
        self.tree = ttk.Treeview(wrap, columns=("mac", "status", "block", "pos"), show="headings", selectmode="browse")
        for c, t, w in (("mac", "MAC ADDRESS", 260), ("status", "STATUS", 130), ("block", "BLOCK", 80), ("pos", "POSITION (X, Y, Z)", 190)):
            self.tree.heading(c, text=t, anchor="w")
            self.tree.column(c, width=w, anchor="w")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.tag_configure("ok", foreground=OK)
        self.tree.tag_configure("bad", foreground=RED)
        self.tree.tag_configure("hover", background=RED_SOFT)
        self.tree.bind("<Motion>", self._tree_hover)
        self.tree.bind("<Leave>", lambda e: self._tree_hover(None))
        self.tree.bind("<<TreeviewSelect>>", self._pick_row)
        foot = tk.Frame(f, bg=WHITE)
        foot.pack(fill="x", padx=36, pady=12)
        Btn(foot, "Refresh list", self.refresh_devices, "outline", "sm").pack(side="left")

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
        sel = self.tree.selection()
        if sel:
            mac = self.tree.item(sel[0])["values"][0]
            self.var_mac.set(mac)
            self.var_test_mac.set(mac)

    def _dev_msg(self, text, color=MUTED):
        self.ui(lambda: self.dev_msg.config(text=text, fg=color))

    def refresh_devices(self):
        def work():
            if not self.be.chain.connected():
                self._dev_msg("Blockchain is not running. Press Start on the Home page.", RED)
                return
            if not self.be.chain.deployed_address():
                self._dev_msg("The contract is not deployed yet.", RED)
                return
            rows = self.be.chain.devices()
            self.ui(self._fill_tree, rows)
            self._dev_msg(f"{len(rows)} device(s) on the ledger.")
        self.bg(work)

    def _fill_tree(self, rows):
        self.hover_row = None
        self.tree.delete(*self.tree.get_children())
        for mac, ok, block in rows:
            p = self.net.pos(core.normalize_mac(mac))
            self.tree.insert("", "end", values=(mac, "Authorized" if ok else "Revoked", block,
                                                f"{p[0]:g}, {p[1]:g}, {p[2]:g}" if p else "-"),
                             tags=("ok" if ok else "bad",))

    def device_action(self, action):
        raw = self.var_mac.get()
        pos_text = (self.var_px.get().strip(), self.var_py.get().strip(), self.var_pz.get().strip())

        def work():
            try:
                mac = core.normalize_mac(raw)
            except ValueError as e:
                self._dev_msg(str(e), RED)
                return
            if not self.be.chain.deployed_address():
                self._dev_msg("Press Start on the Home page first (blockchain and contract must be running).", RED)
                return
            pos = None
            if action == "register" and any(pos_text):
                try:
                    pos = ed.validate_pos(pos_text) if all(pos_text) else None
                    if pos is None:
                        raise ValueError("Enter all three of X, Y and Z, or leave all three blank for a random position.")
                except ValueError as e:
                    self._dev_msg(str(e), RED)
                    return
            self._dev_msg("Sending transaction...", MUTED)
            try:
                rc = self.be.chain.send(action, mac)
            except Exception as e:
                self._dev_msg(f"Failed: {e}", RED)
                self.log(f"{action} failed: {e}")
                return
            verb = "Registered" if action == "register" else "Revoked"
            where = ""
            if action == "register":
                had = self.net.pos(mac)
                p = self.net.ensure_position(mac, pos)        # given position, else keep, else random
                where = f" at ({p[0]:g}, {p[1]:g}, {p[2]:g})" + (" (random)" if pos is None and not had else "")
            self._dev_msg(f"{verb} {core.pretty_mac(mac)}{where} (block {rc.blockNumber}).", OK)
            self.log(f"{verb} {core.pretty_mac(mac)}{where} in block {rc.blockNumber}")
            self.ui(self.refresh_devices)
            self.ui(self.refresh_registry, self.network_changed)
        self.bg(work)

    def device_check(self):
        raw = self.var_mac.get()

        def work():
            try:
                mac = core.normalize_mac(raw)
                ok = self.be.chain.is_authorized(mac)
            except Exception as e:
                self._dev_msg(str(e), RED)
                return
            self._dev_msg(f"{core.pretty_mac(mac)} is {'AUTHORIZED' if ok else 'NOT authorized'}.", OK if ok else RED)
        self.bg(work)

    # ---- ROUTER / EDUROAM / PACKETS
    def _build_router(self):
        self.router_page = RouterPage(self, self._new_page("router"))

    def _build_eduroam(self):
        self.eduroam_page = EduroamPage(self, self._new_page("eduroam"))

    def _build_packets(self):
        self.packets_page = PacketsPage(self, self._new_page("packets"))

    def refresh_registry(self, then=None):
        """Read the registered devices from the ledger once, for every page that needs them."""
        def work():
            ch = self.be.chain
            rows, problem = None, ""
            try:
                if not ch.connected():
                    problem = "Blockchain is not running. Press Start on the Home page."
                elif not ch.deployed_address():
                    problem = "The contract is not deployed yet."
                else:
                    rows = ch.devices()
            except Exception as e:
                problem = f"Could not read the ledger: {e}"
            self.ui(self._set_registry, rows, problem, then)
        self.bg(work)

    def _set_registry(self, rows, problem, then):
        self.registry_problem = problem
        if rows is not None:
            self.registry = [{"mac": core.normalize_mac(p), "pretty": p, "auth": ok} for p, ok, _ in rows]
            self.net.ensure_positions([r["mac"] for r in self.registry if r["auth"]])   # random spot if none yet
        if then:
            then()

    def network_changed(self, closed=None, note=None):
        """Something changed in the eduroam network: tell every page."""
        if closed and getattr(self, "router_page", None):
            self.router_page._notify_closed(closed, note or "a device left the network.")
        for key in self.LIVE_PAGES[:2]:
            page = getattr(self, key + "_page", None)
            if page:
                page.refresh_views()

    def _net_watch(self):
        """Every few seconds, check every connected device against the blockchain; revoked ones are removed."""
        macs = list(self.net.attached)
        if macs:
            def work():
                if not self.be.chain.connected():
                    return
                kicked, closed = [], []
                for mac in macs:
                    try:
                        allowed = self.be.ledger_allows(mac)
                    except Exception:
                        return
                    if not allowed:
                        closed += self.net.leave(mac, f"{self.net.name(mac)} is no longer authorized on the blockchain")
                        kicked.append(mac)
                if kicked:
                    names = ", ".join(self.net.name(m) for m in kicked)
                    self.log(f"Eduroam: {names} revoked on the blockchain, removed from the network.")
                    self.ui(self._on_kicked, kicked, sorted(set(closed)))
            self.bg(work)
        self.after(3000, self._net_watch)

    def _on_kicked(self, kicked, closed):
        self.router_page.on_kicked(kicked, closed)
        self.eduroam_page.refresh_views()
        self.refresh_registry()

    # ---- TEST LOGIN
    def _build_test(self):
        f = self._new_page("test")
        page_header(f, "Test login", "Sends a real RADIUS login request, like a Wi-Fi access point or switch would, "
                                     "and shows what happens to it.")
        form = tk.Frame(f, bg=WHITE, highlightthickness=1, highlightbackground=LINE, padx=16, pady=14)
        form.pack(fill="x", padx=36)
        tk.Label(form, text="Device MAC", font=(FONT, 10, "bold"), fg=INK, bg=WHITE).pack(side="left")
        self.var_test_mac = tk.StringVar()
        e = make_entry(form, self.var_test_mac, width=26)
        e.pack(side="left", padx=12, ipady=6)
        e.bind("<Return>", lambda ev: self.run_test())
        self.send_btn = Btn(form, "Send test login", self.run_test, "primary")
        self.send_btn.pack(side="left")

        split = tk.Frame(f, bg=WHITE)
        split.pack(fill="both", expand=True, padx=36, pady=(14, 14))
        split.columnconfigure(0, weight=1)
        split.columnconfigure(1, weight=0)
        split.rowconfigure(0, weight=1)

        left = tk.Frame(split, bg=WHITE, highlightthickness=1, highlightbackground=LINE)
        left.grid(row=0, column=0, sticky="nsew")
        self.canvas = tk.Canvas(left, bg=WHITE, highlightthickness=0, height=250)
        self.canvas.pack(fill="both", expand=True, padx=6, pady=(6, 0))
        self.canvas.bind("<Configure>", lambda e: self.draw_scene())
        self.test_result = tk.Label(left, text="Ready", font=(FONT, 20, "bold"), fg=OFF, bg=WHITE)
        self.test_result.pack(pady=(2, 0))
        self.test_detail = tk.Label(left, text="Enter a MAC address and press Send test login.", font=(FONT, 10),
                                    fg=MUTED, bg=WHITE, wraplength=520, justify="center")
        self.test_detail.pack(pady=(2, 12))

        right = tk.Frame(split, bg=WHITE, highlightthickness=1, highlightbackground=LINE, width=320)
        right.grid(row=0, column=1, sticky="nsew", padx=(14, 0))
        right.grid_propagate(False)
        hdr = tk.Frame(right, bg=RED_SOFT)
        hdr.pack(fill="x")
        tk.Label(hdr, text="MESSAGE", font=(FONT, 9, "bold"), fg=RED_DARK, bg=RED_SOFT, padx=14, pady=9).pack(anchor="w")
        self.msgbox = tk.Text(right, bg=PANEL, fg=INK, font=("Consolas", 9), relief="flat", bd=0, wrap="word",
                              padx=14, pady=12, height=14, width=36, highlightthickness=0, cursor="arrow")
        self.msgbox.pack(fill="both", expand=True)
        for tag, kw in (("h", dict(foreground=RED, font=("Consolas", 9, "bold"))), ("k", dict(foreground=MUTED)),
                        ("ok", dict(foreground=OK, font=("Consolas", 9, "bold"))),
                        ("bad", dict(foreground=RED, font=("Consolas", 9, "bold"))),
                        ("warn", dict(foreground=WARN, font=("Consolas", 9, "bold")))):
            self.msgbox.tag_configure(tag, **kw)
        self.msg_write([("No message yet.\n", "k"), ("The login request will appear here when you send it.", "k")])
        self.draw_scene()

    def msg_write(self, parts, append=False):
        self.msgbox.config(state="normal")
        if not append:
            self.msgbox.delete("1.0", "end")
        for text, tag in parts:
            self.msgbox.insert("end", text, tag)
        self.msgbox.config(state="disabled")

    # animation -----------------------------------------------------
    DUR = {"to_server": 0.8, "to_chain": 0.7, "from_chain": 0.7, "to_device": 0.8}

    def run_test(self):
        a = self.anim
        if a and a["phase"] not in ("done", "fail"):
            return
        raw = self.var_test_mac.get().strip()
        if not raw:
            messagebox.showinfo("Enter a MAC", "Type a MAC address first, e.g. AA-BB-CC-DD-EE-FF")
            return
        s = self.be.settings
        self.anim = {"phase": "to_server", "t0": time.time(), "result": None, "kind": None, "mac": raw}
        self.send_btn.set_enabled(False)
        self.test_result.config(text="Sending...", fg=MUTED)
        self.test_detail.config(text="")
        parts = [("REQUEST  >>\n", "h")]
        for k, v in core.describe_request(raw, s["radius_host"], s["radius_port"]):
            parts += [(f"{k}\n", "k"), (f"  {v}\n", "")]
        self.msg_write(parts)
        self._tick()

        def work():
            kind, detail = core.radius_test(s["radius_host"], int(s["radius_port"]), s["radius_secret"], raw)
            chain_says = None
            try:
                chain_says = self.be.chain.is_authorized(core.normalize_mac(raw))
            except Exception:
                pass
            self.ui(self._anim_result, kind, detail, chain_says)
        self.bg(work)

    def _anim_result(self, kind, detail, chain_says):
        a = self.anim
        if not a:
            return
        a["result"], a["kind"], a["detail"], a["chain"] = True, kind, detail, chain_says
        titles = {"accept": ("Access-Accept", "ok"), "reject": ("Access-Reject", "bad"),
                  "timeout": ("No reply", "warn"), "badsecret": ("Bad signature", "warn"),
                  "error": ("Network error", "warn"), "challenge": ("Access-Challenge", "warn"),
                  "other": ("Unexpected reply", "warn")}
        title, tag = titles[kind]
        parts = [("\nREPLY  <<\n", "h"), (f"{title}\n", tag)]
        if kind in ("accept", "reject"):
            parts += [("Blockchain lookup\n", "k"),
                      ("  isDeviceAuthorized -> " + ("true" if kind == "accept" else "false") + "\n", "")]
        else:
            parts += [(detail + "\n", "k")]
        if chain_says is not None:
            parts += [("Ledger check from this app\n", "k"), ("  " + ("authorized" if chain_says else "not authorized") + "\n", "")]
        self.msg_write(parts, append=True)

    @staticmethod
    def _ease(p):
        p = max(0.0, min(1.0, p))
        return p * p * (3 - 2 * p)

    def _tick(self):
        a = self.anim
        if not a or a["phase"] in ("done", "fail"):
            return
        now = time.time()
        el = now - a["t0"]
        ph = a["phase"]
        if ph in self.DUR:
            if el >= self.DUR[ph]:
                nxt = {"to_server": "waiting", "to_chain": "from_chain", "from_chain": "to_device", "to_device": "done"}[ph]
                a["phase"], a["t0"] = nxt, now
        elif ph == "waiting" and a["result"] and el >= 0.35:
            a["phase"] = "to_chain" if a["kind"] in ("accept", "reject") else "fail"
            a["t0"] = now
        if a["phase"] in ("done", "fail"):
            self._finish_anim()
        self.draw_scene()
        if a["phase"] not in ("done", "fail"):
            self.after(30, self._tick)

    def _finish_anim(self):
        a = self.anim
        kind = a["kind"]
        shown = {"accept": ("ACCEPTED", OK, "The device is on the allowlist, so it is let onto the network."),
                 "reject": ("REJECTED", RED, "The device is not on the allowlist (or was revoked)."),
                 "timeout": ("NO REPLY", WARN, a["detail"]), "badsecret": ("SECRET MISMATCH", WARN, a["detail"]),
                 "error": ("ERROR", WARN, a["detail"]), "challenge": ("CHALLENGE", WARN, a["detail"]),
                 "other": ("UNEXPECTED REPLY", WARN, a["detail"])}[kind]
        self.test_result.config(text=shown[0], fg=shown[1])
        extra = ""
        if a.get("chain") is not None and kind in ("accept", "reject"):
            if a["chain"] != (kind == "accept"):
                extra = "\nNote: the ledger and the server disagree. Restart the server."
        self.test_detail.config(text=shown[2] + extra)
        self.send_btn.set_enabled(True)
        self.log(f"Test login for {a['mac']}: {shown[0]}")

    def draw_scene(self):
        c = self.canvas
        c.delete("all")
        W = max(c.winfo_width(), 420)
        H = max(c.winfo_height(), 220)
        nw, nh = 112, 92
        cy = H * 0.50
        xs = {"dev": nw / 2 + 18, "srv": W / 2, "chn": W - nw / 2 - 18}
        a = self.anim or {}
        ph = a.get("phase")
        kind = a.get("kind")

        def edge(node, side):
            return xs[node] + (nw / 2 if side == "r" else -nw / 2)

        segs = {"s1": (edge("dev", "r"), edge("srv", "l")), "s2": (edge("srv", "r"), edge("chn", "l"))}
        active = {"to_server": "s1", "to_device": "s1", "to_chain": "s2", "from_chain": "s2"}.get(ph)
        for name, (x1, x2) in segs.items():
            hot = active == name
            c.create_line(x1 + 6, cy, x2 - 6, cy, fill=RED if hot else LINE, width=3 if hot else 2,
                          dash=() if hot else (5, 4), arrow="last" if name == "s1" else "last")
        # nodes
        def node(key, title, sub, outline, width):
            x = xs[key]
            round_rect(c, x - nw / 2, cy - nh / 2, x + nw / 2, cy + nh / 2, 14, fill=WHITE, outline=outline, width=width)
            c.create_text(x, cy + 20, text=title, font=(FONT, 10, "bold"), fill=INK)
            c.create_text(x, cy + 36, text=sub, font=(FONT, 8), fill=MUTED)
        pulse = 4 if (ph == "waiting" and int(time.time() * 4) % 2 == 0) else 2
        dev_out = {"done": OK if kind == "accept" else RED}.get(ph, RED if ph in ("to_server", "to_device") else LINE)
        node("dev", "Device", (a.get("mac") or "MAC address")[:17], dev_out, 3 if ph == "done" else 2)
        node("srv", "RADIUS server", "UDP 1812", RED if ph in ("waiting", "to_server", "to_chain", "from_chain", "to_device") else (WARN if ph == "fail" else LINE), pulse)
        node("chn", "Blockchain", "Smart contract", RED if ph in ("to_chain", "from_chain") else LINE, 2)
        # pictograms
        x = xs["dev"]
        round_rect(c, x - 16, cy - 32, x + 16, cy - 10, 4, fill=WHITE, outline=RED, width=2)
        c.create_line(x - 8, cy - 4, x + 8, cy - 4, fill=RED, width=2)
        x = xs["srv"]
        for i in range(3):
            y = cy - 34 + i * 9
            c.create_rectangle(x - 16, y, x + 16, y + 7, outline=RED, width=2)
            c.create_oval(x + 9, y + 2, x + 13, y + 6, fill=RED, outline=RED)
        x = xs["chn"]
        for dx in (-16, 0, 16):
            c.create_rectangle(x + dx - 6, cy - 28, x + dx + 6, cy - 14, outline=RED, width=2)
        c.create_line(x - 10, cy - 21, x - 6, cy - 21, fill=RED, width=2)
        c.create_line(x + 6, cy - 21, x + 10, cy - 21, fill=RED, width=2)

        # moving packet
        if ph in self.DUR:
            p = self._ease((time.time() - a["t0"]) / self.DUR[ph])
            acc = kind == "accept"
            spec = {"to_server": ("s1", False, "Access-Request", RED, WHITE),
                    "to_chain": ("s2", False, "isDeviceAuthorized", RED, WHITE),
                    "from_chain": ("s2", True, "true" if acc else "false", OK if acc else INK, WHITE),
                    "to_device": ("s1", True, "Access-Accept" if acc else "Access-Reject", OK if acc else INK, WHITE)}[ph]
            seg, back, label, fill, fg = spec
            x1, x2 = segs[seg]
            px = (x2 - (x2 - x1) * p) if back else (x1 + (x2 - x1) * p)
            w = 8 * len(label) + 22
            round_rect(c, px - w / 2, cy - 15, px + w / 2, cy + 15, 10, fill=fill, outline="")
            c.create_text(px, cy, text=label, font=(FONT, 8, "bold"), fill=fg)
        elif ph == "waiting":
            c.create_text(xs["srv"], cy - nh / 2 - 14, text="Checking the blockchain...", font=(FONT, 9), fill=MUTED)
        # result badges
        def badge(x, y, glyph, color):
            c.create_oval(x - 13, y - 13, x + 13, y + 13, fill=color, outline=WHITE, width=2)
            c.create_text(x, y - 1, text=glyph, font=(FONT, 12, "bold"), fill=WHITE)
        if ph == "done":
            badge(xs["dev"] + nw / 2 - 4, cy - nh / 2 + 4, "\u2713" if kind == "accept" else "\u2717", OK if kind == "accept" else RED)
        elif ph == "fail":
            badge(xs["srv"] + nw / 2 - 4, cy - nh / 2 + 4, "!", WARN)

    # ---- ACTIVITY
    def _build_activity(self):
        f = self._new_page("activity")
        page_header(f, "Activity log", "Everything NewLAN is doing, including output from Ganache, Docker and the server.")
        bar = tk.Frame(f, bg=WHITE)
        bar.pack(fill="x", padx=36)
        Btn(bar, "Copy all", self._copy_log, "outline", "sm").pack(side="left")
        Btn(bar, "Save to file", self._save_log, "outline", "sm").pack(side="left", padx=8)
        Btn(bar, "Clear", self._clear_log, "outline", "sm").pack(side="left")
        wrap = tk.Frame(f, bg=WHITE, highlightthickness=1, highlightbackground=LINE)
        wrap.pack(fill="both", expand=True, padx=36, pady=(12, 24))
        self.logbox = tk.Text(wrap, bg=PANEL, fg=INK, font=("Consolas", 10), relief="flat", bd=0, wrap="word",
                              padx=14, pady=12, state="disabled", highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.logbox.yview)
        self.logbox.configure(yscrollcommand=sb.set)
        self.logbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.logbox.tag_configure("time", foreground=OFF)
        self.logbox.tag_configure("err", foreground=RED)
        self.logbox.tag_configure("good", foreground=OK)

    def _append_log(self, text):
        stamp, _, msg = text.partition("  ")
        low = msg.lower()
        tag = "err" if any(w in low for w in ("error", "failed", "not found", "could not", "stopped right after", "likely cause")) \
            else "good" if any(w in low for w in ("is running", "all services", "deployed.", "is up", "accepted")) else ""
        self.logbox.config(state="normal")
        self.logbox.insert("end", stamp + "  ", "time")
        self.logbox.insert("end", msg, tag)
        self.logbox.see("end")
        self.logbox.config(state="disabled")
        self.latest.set(msg.strip()[:110])

    def _clear_log(self):
        self.logbox.config(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.config(state="disabled")

    def _copy_log(self):
        self.clipboard_clear()
        self.clipboard_append(self.logbox.get("1.0", "end"))
        self.log("Log copied to the clipboard.")

    def _save_log(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="newlan-log.txt",
                                            filetypes=[("Text file", "*.txt")])
        if path:
            Path(path).write_text(self.logbox.get("1.0", "end"), encoding="utf-8")
            self.log(f"Log saved to {path}")

    # ---- SETTINGS
    def _build_settings(self):
        f = self._new_page("settings")
        page_header(f, "Settings", "Where the blockchain lives and the shared secret used by access points.")
        card = tk.Frame(f, bg=WHITE, highlightthickness=1, highlightbackground=LINE, padx=20, pady=18)
        card.pack(fill="x", padx=36)
        card.columnconfigure(1, weight=1)
        s = self.be.settings
        self.var_rpc = tk.StringVar(value=s["rpc_url"])
        self.var_secret = tk.StringVar(value=s["radius_secret"])
        self.var_all = tk.BooleanVar(value=s["listen_all"])
        tk.Label(card, text="Blockchain address", font=(FONT, 10, "bold"), bg=WHITE, fg=INK).grid(row=0, column=0, sticky="w", pady=8)
        make_entry(card, self.var_rpc).grid(row=0, column=1, sticky="we", padx=(16, 0), ipady=6)
        tk.Label(card, text="RADIUS shared secret", font=(FONT, 10, "bold"), bg=WHITE, fg=INK).grid(row=1, column=0, sticky="w", pady=8)
        make_entry(card, self.var_secret).grid(row=1, column=1, sticky="we", padx=(16, 0), ipady=6)
        tk.Checkbutton(card, text="Let Ganache listen on all network interfaces (only if the server container cannot reach it; "
                                  "exposes Ganache to your network)", variable=self.var_all, bg=WHITE, fg=INK,
                       activebackground=WHITE, activeforeground=RED, selectcolor=WHITE, font=(FONT, 9),
                       wraplength=640, justify="left", anchor="w").grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.settings_msg = tk.Label(card, text="", font=(FONT, 9), bg=WHITE, fg=MUTED)
        self.settings_msg.grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))
        Btn(card, "Apply", self.apply_settings, "primary").grid(row=4, column=0, sticky="w", pady=(10, 0))
        tk.Label(f, text="Using the Ganache desktop app? Start it yourself, enter its address above (usually "
                         "http://127.0.0.1:7545), click Apply, then press Start on the Home page.",
                 font=(FONT, 9), fg=MUTED, bg=WHITE, wraplength=820, justify="left").pack(anchor="w", padx=36, pady=14)

    def apply_settings(self):
        try:
            self.be.apply_settings(self.var_rpc.get(), self.var_secret.get(), self.var_all.get())
        except ValueError as e:
            self.settings_msg.config(text=str(e), fg=RED)
            return
        self.settings_msg.config(text="Saved. If the server is running, press Stop then Start to use the new values.", fg=OK)
        self.log("Settings saved.")
        self.request_poll()

    # ---- closing
    def on_close(self):
        st = self.be.status
        running = (self.be.ganache_proc and self.be.ganache_proc.poll() is None) or st.get("container") == "running"
        if not running:
            self.destroy()
            return
        ans = messagebox.askyesnocancel("Close NewLAN", "Stop the services (FreeRADIUS and Ganache) before closing?\n\n"
                                                        "Yes = stop them, No = leave them running.")
        if ans is None:
            return
        if ans is False:
            self.destroy()
            return
        self.title("NewLAN - stopping services...")

        def work():
            self.be.stop_all()
            self.ui(self.destroy)
        self.bg(work)


def main():
    enable_dpi_awareness()
    if not ensure_dependencies():
        return
    App().mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:   # .pyw has no console, so surface crashes
        import traceback
        (HERE / "newlan_error.log").write_text(traceback.format_exc())
        try:
            messagebox.showerror("NewLAN crashed", f"{exc}\n\nDetails saved to newlan_error.log")
        except Exception:
            pass
