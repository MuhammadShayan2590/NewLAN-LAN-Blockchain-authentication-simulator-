"""NewLAN Packet store page: every packet sent across the eduroam network, live, searchable and exportable."""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from newlan_widgets import (INK, LINE, MUTED, OFF, OK, PANEL, RED, RED_DARK, RED_SOFT, WHITE, FONT,
                            Btn, make_entry)

MAX_ROWS = 500          # rows drawn in the table (the store itself keeps up to 5000 and all of them in the file)


class PacketsPage:
    def __init__(self, app, parent):
        self.app = app
        self.store = app.net.packets
        self.visible = False
        self.records = {}                    # iid -> record, for the rows currently shown
        self.hover_row = None
        self.var_search = tk.StringVar()
        self.cb_kind = None
        self.cb_status = None
        self._build(parent)
        self.store.on_add = lambda rec: self.app.ui(self.on_new_packet, rec)

    # ================================================================== layout
    def _build(self, parent):
        head = tk.Frame(parent, bg=WHITE)
        head.pack(fill="x", padx=36, pady=(22, 0))
        tk.Label(head, text="Packet store", font=(FONT, 22, "bold"), fg=INK, bg=WHITE).pack(side="left")
        self.count = tk.Label(head, text="", font=(FONT, 9), fg=MUTED, bg=WHITE)
        self.count.pack(side="left", padx=14, pady=(10, 0))
        tk.Frame(parent, bg=RED, height=3, width=46).pack(anchor="w", padx=36, pady=(8, 0))
        tk.Label(parent, text="Every packet sent over the eduroam network (messages, pings and replies, delivered or dropped), "
                              "saved to eduroam_packets.jsonl.", font=(FONT, 9), fg=MUTED, bg=WHITE, anchor="w"
                 ).pack(fill="x", padx=36, pady=(6, 0))

        bar = tk.Frame(parent, bg=WHITE)
        bar.pack(fill="x", padx=36, pady=(10, 0))
        e = make_entry(bar, self.var_search, width=26)
        e.pack(side="left", ipady=5)
        e.bind("<KeyRelease>", lambda ev: self.reload())
        tk.Label(bar, text="search device, IP, router or text", font=(FONT, 8), fg=OFF, bg=WHITE).pack(side="left", padx=(8, 14))
        self.cb_kind = ttk.Combobox(bar, state="readonly", width=13, font=(FONT, 10), values=("All kinds", "message", "icmp-echo", "icmp-reply"))
        self.cb_kind.set("All kinds")
        self.cb_kind.pack(side="left", ipady=2)
        self.cb_kind.bind("<<ComboboxSelected>>", lambda ev: self.reload())
        self.cb_status = ttk.Combobox(bar, state="readonly", width=12, font=(FONT, 10), values=("All status", "delivered", "dropped"))
        self.cb_status.set("All status")
        self.cb_status.pack(side="left", padx=8, ipady=2)
        self.cb_status.bind("<<ComboboxSelected>>", lambda ev: self.reload())
        Btn(bar, "Clear store", self.clear_store, "outline", "sm").pack(side="right")
        Btn(bar, "Export CSV", self.export_csv, "outline", "sm").pack(side="right", padx=6)

        wrap = tk.Frame(parent, bg=WHITE, highlightthickness=1, highlightbackground=LINE)
        wrap.pack(fill="both", expand=True, padx=36, pady=(10, 0))
        cols = (("id", "#", 52), ("time", "TIME", 92), ("kind", "KIND", 86), ("src", "FROM", 118), ("dst", "TO", 118),
                ("path", "ROUTE", 150), ("size", "BYTES", 58), ("ms", "MS", 56), ("status", "STATUS", 84))
        self.tree = ttk.Treeview(wrap, style="Compact.Treeview", columns=[c[0] for c in cols], show="headings", selectmode="browse")
        for c, t, w in cols:
            self.tree.heading(c, text=t, anchor="w")
            self.tree.column(c, width=w, anchor="w")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.tag_configure("ok", foreground=INK)
        self.tree.tag_configure("bad", foreground=RED)
        self.tree.tag_configure("hover", background=RED_SOFT)
        self.tree.bind("<<TreeviewSelect>>", self._show_detail)
        self.tree.bind("<Motion>", self._hover)
        self.tree.bind("<Leave>", lambda e: self._hover(None))

        box = tk.Frame(parent, bg=WHITE, highlightthickness=1, highlightbackground=LINE)
        box.pack(fill="x", padx=36, pady=(10, 16))
        hdr = tk.Frame(box, bg=RED_SOFT)
        hdr.pack(fill="x")
        tk.Label(hdr, text="PACKET DETAILS", font=(FONT, 8, "bold"), fg=RED_DARK, bg=RED_SOFT, padx=12, pady=6).pack(side="left")
        self.detail = tk.Text(box, bg=PANEL, fg=INK, font=("Consolas", 9), relief="flat", bd=0, wrap="word", padx=12, pady=8,
                              height=6, state="disabled", cursor="arrow", highlightthickness=0)
        self.detail.pack(fill="x")
        self.detail.tag_configure("k", foreground=MUTED)
        self.detail.tag_configure("bad", foreground=RED, font=("Consolas", 9, "bold"))
        self.detail.tag_configure("ok", foreground=OK, font=("Consolas", 9, "bold"))
        self._write_detail([("Select a packet above to see everything about it.", "k")])

    # ================================================================== data
    def on_show(self):
        self.visible = True
        self.reload()

    def on_hide(self):
        self.visible = False

    def _matches(self, r):
        kind, status = self.cb_kind.get(), self.cb_status.get()
        if kind != "All kinds" and r["kind"] != kind:
            return False
        if status != "All status" and r["status"] != status:
            return False
        q = self.var_search.get().strip().lower()
        if q:
            hay = " ".join(str(r.get(k, "")) for k in ("src_name", "src_ip", "src_mac", "dst_name", "dst_ip", "dst_mac",
                                                       "payload", "kind", "status", "reason")) + " " + " ".join(r.get("path", [])) + " " + " ".join(r.get("path_ids", []))
            if q not in hay.lower():
                return False
        return True

    @staticmethod
    def _values(r):
        return (r["id"], r["time"][11:], r["kind"], r["src_name"], r["dst_name"], " > ".join(r.get("path_ids") or r.get("path", [])) or "-",
                r["size"], r["latency_ms"], r["status"])

    def reload(self):
        self.hover_row = None
        self.tree.delete(*self.tree.get_children())
        self.records.clear()
        rows = [r for r in self.store.snapshot() if self._matches(r)]
        for r in reversed(rows[-MAX_ROWS:]):            # newest first
            self._insert(r, "end")
        self._update_count()

    def _insert(self, r, where):
        iid = str(r["id"])
        self.records[iid] = r
        self.tree.insert("", where, iid=iid, values=self._values(r), tags=("ok" if r["status"] == "delivered" else "bad",))

    def on_new_packet(self, rec):
        """Called for every packet as it is stored (any page may be showing)."""
        if self.visible and self._matches(rec):
            self._insert(rec, 0)
            kids = self.tree.get_children()
            if len(kids) > MAX_ROWS:
                for old in kids[MAX_ROWS:]:
                    self.records.pop(old, None)
                    self.tree.delete(old)
        self._update_count()

    def _update_count(self):
        total = len(self.store.snapshot())
        shown = len(self.tree.get_children())
        self.count.config(text=f"{total} stored  \u00b7  showing {shown}")

    def _hover(self, event):
        row = self.tree.identify_row(event.y) if event else ""
        if row == self.hover_row:
            return
        if self.hover_row and self.tree.exists(self.hover_row):
            self.tree.item(self.hover_row, tags=tuple(t for t in self.tree.item(self.hover_row, "tags") if t != "hover"))
        self.hover_row = row or None
        if row:
            self.tree.item(row, tags=tuple(self.tree.item(row, "tags")) + ("hover",))

    def _write_detail(self, parts):
        self.detail.config(state="normal")
        self.detail.delete("1.0", "end")
        for text, tag in parts:
            self.detail.insert("end", text, tag)
        self.detail.config(state="disabled")

    def _show_detail(self, _):
        sel = self.tree.selection()
        r = self.records.get(sel[0]) if sel else None
        if not r:
            return
        ok = r["status"] == "delivered"
        route = "  >  ".join(f"{pid} {n}" for pid, n in zip(r.get("path_ids", []), r.get("path", []))) or "-"
        self._write_detail([
            (f"Packet #{r['id']}   ", ""), (r["status"].upper(), "ok" if ok else "bad"),
            (f"   {r['time']}   connection {r['conn']}  seq {r['seq']}   {r['kind']}\n", "k"),
            ("From   ", "k"), (f"{r['src_name']}  {r['src_ip']}  {r['src_mac']}  (router {r['src_router'] or '-'})\n", ""),
            ("To     ", "k"), (f"{r['dst_name']}  {r['dst_ip']}  {r['dst_mac']}  (router {r['dst_router'] or '-'})\n", ""),
            ("Route  ", "k"), (route + "\n", ""),
            ("Size   ", "k"), (f"{r['size']} bytes   ", ""), ("Latency ", "k"), (f"{r['latency_ms']} ms\n", ""),
            ("Data   ", "k"), (f"{r['payload'] or '(empty)'}\n", ""),
        ] + ([("Reason ", "k"), (r["reason"] + "\n", "bad")] if r.get("reason") else []))

    # ================================================================== actions
    def export_csv(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="eduroam-packets.csv",
                                            filetypes=[("CSV file", "*.csv")])
        if path:
            self.store.export_csv(path)
            self.app.log(f"Packet store exported to {path}")

    def clear_store(self):
        if messagebox.askyesno("Clear packet store?", "Delete every stored packet, including the saved file?"):
            self.store.clear()
            self.reload()
            self._write_detail([("Store cleared.", "k")])
            self.app.log("Packet store cleared.")
