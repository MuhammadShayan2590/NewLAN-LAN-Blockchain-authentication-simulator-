"""NewLAN eduroam testbed core: routers in a 3D space, device positions, best-router choice,
roaming, the router mesh, connections between devices, and the packet store.

No tkinter in here. Authorization is always decided by callbacks the caller passes in
(RADIUS server / blockchain), never by this module.
"""
import csv
import json
import math
import random
import threading
import time
from collections import deque
from pathlib import Path

from newlan_core import HERE

STATE_FILE = HERE / "eduroam_state.json"
PACKET_FILE = HERE / "eduroam_packets.jsonl"
OLD_STATE_FILE = HERE / "router_state.json"      # earlier single-router version (names are imported)

SPACE = (100.0, 70.0, 12.0)          # x, y, z in metres (z = height, floors every 4 m)
SUBNET = "10.20.0"
POOL_START, POOL_END = 11, 99

RSSI_1M = -35.0                      # signal strength at 1 m (dBm)
PATH_LOSS = 25.0                     # log-distance path-loss factor (10 * n, n = 2.5)
RSSI_MIN = -78.0                     # weakest usable signal
RANGE_M = 10 ** ((RSSI_1M - RSSI_MIN) / PATH_LOSS)   # about 52 m
W_SIGNAL, W_LOAD = 0.6, 0.4          # weight of signal quality vs. spare capacity in the score
HEADER_BYTES = 42                    # Ethernet + IP + UDP overhead added to every payload

ROUTERS = [
    {"id": "R1", "name": "Library",  "pos": (15.0, 15.0, 2.5), "capacity": 5, "ip": SUBNET + ".1"},
    {"id": "R2", "name": "Lab",      "pos": (85.0, 15.0, 2.5), "capacity": 5, "ip": SUBNET + ".2"},
    {"id": "R3", "name": "Hall",     "pos": (50.0, 35.0, 6.5), "capacity": 5, "ip": SUBNET + ".3"},
    {"id": "R4", "name": "Cafe",     "pos": (15.0, 58.0, 2.5), "capacity": 5, "ip": SUBNET + ".4"},
    {"id": "R5", "name": "Dorm",     "pos": (85.0, 58.0, 6.5), "capacity": 5, "ip": SUBNET + ".5"},
]
ROUTER_BY_ID = {r["id"]: r for r in ROUTERS}


def distance(p, q):
    return math.dist(p, q)


def rssi_at(d):
    return RSSI_1M - PATH_LOSS * math.log10(max(d, 1.0))


def _clamp01(v):
    return max(0.0, min(1.0, v))


def validate_pos(pos):
    """Return (x, y, z) as floats inside the space, or raise ValueError with a friendly message."""
    try:
        x, y, z = (float(v) for v in pos)
    except (TypeError, ValueError):
        raise ValueError("X, Y and Z must be numbers.")
    for v, hi, name in ((x, SPACE[0], "X"), (y, SPACE[1], "Y"), (z, SPACE[2], "Z")):
        if not 0 <= v <= hi:
            raise ValueError(f"{name} must be between 0 and {hi:g} metres.")
    return (round(x, 1), round(y, 1), round(z, 1))


def random_position(rng=random):
    return (round(rng.uniform(3, SPACE[0] - 3), 1), round(rng.uniform(3, SPACE[1] - 3), 1),
            round(rng.uniform(0.5, SPACE[2] - 0.5), 1))


# --------------------------------------------------------------------------- packet store

class PacketStore:
    """Every packet that crosses the eduroam network, kept in memory and in eduroam_packets.jsonl."""

    def __init__(self, path=PACKET_FILE, keep=5000):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.rows = deque(maxlen=keep)
        self.next_id = 1
        self.on_add = None                      # callback(record), may be called from any thread
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines()[-keep:]:
                rec = json.loads(line)
                self.rows.append(rec)
                self.next_id = max(self.next_id, rec["id"] + 1)
        except (OSError, ValueError, KeyError):
            pass

    def add(self, rec):
        with self.lock:
            rec["id"] = self.next_id
            self.next_id += 1
            self.rows.append(rec)
            try:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec) + "\n")
            except OSError:
                pass
        if self.on_add:
            self.on_add(rec)
        return rec

    def snapshot(self):
        with self.lock:
            return list(self.rows)

    def clear(self):
        with self.lock:
            self.rows.clear()
            try:
                self.path.write_text("", encoding="utf-8")
            except OSError:
                pass

    COLUMNS = ["id", "time", "kind", "status", "reason", "src_name", "src_mac", "src_ip", "src_router", "dst_name",
               "dst_mac", "dst_ip", "dst_router", "path", "size", "latency_ms", "conn", "seq", "payload"]

    def export_csv(self, path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(self.COLUMNS)
            for r in self.snapshot():
                w.writerow([r.get(c, "") if c != "path" else " > ".join(r.get("path", [])) for c in self.COLUMNS])


# --------------------------------------------------------------------------- the network

class EduroamNet:
    def __init__(self, state_file=STATE_FILE, packet_file=PACKET_FILE, old_state=OLD_STATE_FILE):
        self.state_file = Path(state_file)
        self.lock = threading.RLock()
        self.devices = {}        # raw MAC -> {"name", "pos": [x, y, z], "ip"}   (saved to disk)
        self.attached = {}       # raw MAC -> router id                         (this session)
        self.connections = {}    # id -> connection dict                         (this session)
        self.next_cid = 1
        self.packets = PacketStore(packet_file)
        self._load(Path(old_state))

    # ---- persistence
    def _load(self, old_state):
        try:
            self.devices = json.loads(self.state_file.read_text()).get("devices", {})
            return
        except Exception:
            self.devices = {}
        try:                                        # first run: keep the names from the old single-router page
            for mac, lease in json.loads(old_state.read_text()).get("devices", {}).items():
                if lease.get("name"):
                    self.devices[mac] = {"name": lease["name"]}
        except Exception:
            pass

    def _save(self):
        try:
            self.state_file.write_text(json.dumps({"devices": self.devices}, indent=2))
        except OSError:
            pass

    # ---- device info
    def name(self, mac):
        return self.devices.get(mac, {}).get("name") or f"Device-{mac[-4:]}"

    def set_name(self, mac, name):
        with self.lock:
            d = self.devices.setdefault(mac, {})
            name = (name or "").strip()[:24]
            if name:
                d["name"] = name
            else:
                d.pop("name", None)
            self._save()

    def ip(self, mac):
        return self.devices.get(mac, {}).get("ip", "")

    def pos(self, mac):
        p = self.devices.get(mac, {}).get("pos")
        return tuple(p) if p else None

    def set_pos(self, mac, pos):
        pos = validate_pos(pos)
        with self.lock:
            self.devices.setdefault(mac, {})["pos"] = list(pos)
            self._save()
        return pos

    def ensure_position(self, mac, pos=None):
        """Use the given position, else keep the current one, else place the device at random."""
        if pos is not None:
            return self.set_pos(mac, pos)
        return self.pos(mac) or self.set_pos(mac, random_position())

    def ensure_positions(self, macs):
        for m in macs:
            self.ensure_position(m)

    def router_of(self, mac):
        return self.attached.get(mac)

    def is_connected(self, mac):
        return mac in self.attached

    def load(self, rid, exclude=None):
        with self.lock:
            return sum(1 for m, r in self.attached.items() if r == rid and m != exclude)

    def _assign_ip(self, mac):
        d = self.devices.setdefault(mac, {})
        if d.get("ip"):
            return d["ip"]
        used = {v.get("ip") for v in self.devices.values()}
        for n in range(POOL_START, POOL_END + 1):
            ip = f"{SUBNET}.{n}"
            if ip not in used:
                d["ip"] = ip
                return ip
        raise RuntimeError("The network has no free addresses left")

    # ---- choosing the best router
    def evaluate_pos(self, pos, exclude_mac=None):
        """Score every router for a device at `pos`. The device's own slot is not counted against
        its current router. Returns a list of dicts; the best usable router has best=True."""
        rows = []
        for r in ROUTERS:
            d = distance(pos, r["pos"])
            rs = rssi_at(d)
            load = self.load(r["id"], exclude_mac)
            in_range = rs >= RSSI_MIN
            full = load >= r["capacity"]
            sig = _clamp01((rs - RSSI_MIN) / (RSSI_1M - RSSI_MIN))
            lsc = _clamp01(1 - load / r["capacity"])
            rows.append({"id": r["id"], "name": r["name"], "dist": round(d, 1), "rssi": round(rs, 1), "signal": sig,
                         "load": load, "capacity": r["capacity"], "load_score": lsc,
                         "total": W_SIGNAL * sig + W_LOAD * lsc, "in_range": in_range, "full": full,
                         "usable": in_range and not full, "best": False})
        usable = [x for x in rows if x["usable"]]
        if usable:
            max(usable, key=lambda x: (round(x["total"], 6), -x["dist"]))["best"] = True
        return rows

    def evaluate(self, mac):
        pos = self.pos(mac)
        return self.evaluate_pos(pos, mac) if pos else []

    @staticmethod
    def best_id(rows):
        return next((r["id"] for r in rows if r["best"]), None)

    # ---- joining, roaming, leaving
    def join(self, mac, auth_fn):
        """Admit a device and attach it to its best router. One registration works at every router.
        auth_fn(mac) -> (allowed, how)."""
        if mac in self.attached:
            return {"ok": True, "how": "already connected", "router": self.attached[mac], "ip": self.ip(mac),
                    "reason": "", "eval": self.evaluate(mac)}
        allowed, how = auth_fn(mac)           # slow (network), so outside the lock
        if not allowed:
            return {"ok": False, "how": how, "router": None, "reason": "not authorized", "eval": []}
        with self.lock:
            pos = self.ensure_position(mac)
            ev = self.evaluate_pos(pos, mac)
            rid = self.best_id(ev)
            if rid is None:
                return {"ok": False, "how": how, "router": None, "eval": ev,
                        "reason": "no router in range with free capacity"}
            self.attached[mac] = rid
            ip = self._assign_ip(mac)
            self._save()
        return {"ok": True, "how": how, "router": rid, "ip": ip, "reason": "", "eval": ev}

    def reconnect(self, mac, auth_fn=None):
        """Re-evaluate after the device moved and switch to the best router if it changed."""
        cur = self.attached.get(mac)
        if cur is None:
            res = self.join(mac, auth_fn or (lambda m: (True, "no check")))
            res.update(changed=res["ok"], **{"from": None, "to": res["router"]})
            return res
        ev = self.evaluate(mac)
        best = self.best_id(ev)
        if best is None:
            closed = self.leave(mac, f"{self.name(mac)} moved out of range of every router")
            return {"ok": False, "changed": True, "from": cur, "to": None, "closed": closed, "eval": ev,
                    "reason": "out of range of every router, disconnected"}
        if best == cur:
            return {"ok": True, "changed": False, "from": cur, "to": cur, "eval": ev,
                    "reason": "already on the best router"}
        how = "no check"
        if auth_fn:
            allowed, how = auth_fn(mac)
            if not allowed:
                closed = self.leave(mac, f"{self.name(mac)} is not authorized")
                return {"ok": False, "changed": True, "from": cur, "to": None, "closed": closed, "eval": ev,
                        "reason": "not authorized"}
        with self.lock:
            self.attached[mac] = best
        return {"ok": True, "changed": True, "from": cur, "to": best, "how": how, "eval": ev, "reason": ""}

    def leave(self, mac, reason=None):
        """Detach a device. Returns the ids of the connections that were closed."""
        with self.lock:
            self.attached.pop(mac, None)
            closed = []
            for cid, c in self.connections.items():
                if c["state"] == "open" and mac in (c["a"], c["b"]):
                    c["state"], c["reason"] = "closed", reason or f"{self.name(mac)} left the network"
                    closed.append(cid)
            return closed

    # ---- connections between two end devices (any routers: the routers are fully meshed)
    def path(self, a, b):
        ra, rb = self.attached.get(a), self.attached.get(b)
        if ra is None or rb is None:
            return []
        return [ra] if ra == rb else [ra, rb]

    def open_connection(self, a, b):
        with self.lock:
            if a == b:
                raise ValueError("Pick two different devices.")
            for m in (a, b):
                if m not in self.attached:
                    raise ValueError(f"{self.name(m)} is not connected to the network.")
            for c in self.connections.values():
                if c["state"] == "open" and {c["a"], c["b"]} == {a, b}:
                    return c
            cid = self.next_cid
            self.next_cid += 1
            conn = {"id": cid, "a": a, "b": b, "state": "open", "reason": "", "opened": time.time(),
                    "seq": 0, "sent": 0, "delivered": 0, "dropped": 0}
            self.connections[cid] = conn
            return conn

    def close_connection(self, cid, reason="closed by user"):
        with self.lock:
            c = self.connections.get(cid)
            if c and c["state"] == "open":
                c["state"], c["reason"] = "closed", reason
                return True
            return False

    def open_connections(self):
        with self.lock:
            return [c for c in self.connections.values() if c["state"] == "open"]

    # ---- forwarding one packet
    def _latency(self, src, dst, measured_ms):
        """Measured ledger-check time + simulated radio hops (grows with distance) + the mesh hop."""
        total = measured_ms
        for mac in (src, dst):
            rid, pos = self.attached.get(mac), self.pos(mac)
            if rid and pos:
                total += 0.5 + 0.02 * distance(pos, ROUTER_BY_ID[rid]["pos"])
        if self.attached.get(src) != self.attached.get(dst):
            total += 0.8
        return round(total, 1)

    def forward(self, cid, src, check_fn, kind="message", payload="", size=None):
        """Send one packet over the connection. Both ends are checked against the ledger first
        (check_fn(mac) -> bool; None skips the check, used for replies). Every packet is stored."""
        t0 = time.perf_counter()
        with self.lock:
            conn = self.connections.get(cid)
            if not conn or conn["state"] != "open":
                return {"ok": False, "reason": "The connection is closed.", "kicked": [], "closed": [], "path": []}
            dst = conn["b"] if src == conn["a"] else conn["a"]
            conn["seq"] += 1
            conn["sent"] += 1
            seq = conn["seq"]
            path = self.path(src, dst)
        size = size or len(payload.encode()) + HEADER_BYTES
        kicked, error = [], None
        if check_fn is not None:
            for mac in (src, dst):
                try:
                    if not check_fn(mac):
                        kicked.append(mac)
                except Exception:
                    error = "The network cannot reach the blockchain to verify the devices."
                    break
        closed = []
        if error:
            res = {"ok": False, "reason": error, "kicked": [], "closed": []}
        elif not path:
            res = {"ok": False, "reason": "A device is not connected to any router.", "kicked": [], "closed": []}
        elif kicked:
            for mac in kicked:
                closed += self.leave(mac, f"{self.name(mac)} is no longer authorized on the blockchain")
            names = " and ".join(self.name(m) for m in kicked)
            res = {"ok": False, "reason": f"{names} not authorized on the blockchain, removed from the network",
                   "kicked": kicked, "closed": sorted(set(closed))}
        else:
            res = {"ok": True, "reason": "", "kicked": [], "closed": []}
        ms = self._latency(src, dst, (time.perf_counter() - t0) * 1000)
        with self.lock:
            conn["delivered" if res["ok"] else "dropped"] += 1
        res.update(seq=seq, ms=ms, path=path, src=src, dst=dst, src_ip=self.ip(src), dst_ip=self.ip(dst))
        self.packets.add({
            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + f".{int((time.time() % 1) * 1000):03d}",
            "ts": time.time(), "conn": cid, "seq": seq, "kind": kind,
            "status": "delivered" if res["ok"] else "dropped", "reason": res["reason"],
            "src_name": self.name(src), "src_mac": src, "src_ip": self.ip(src),
            "dst_name": self.name(dst), "dst_mac": dst, "dst_ip": self.ip(dst),
            "src_router": path[0] if path else "", "dst_router": path[-1] if path else "",
            "path": [ROUTER_BY_ID[p]["name"] for p in path], "path_ids": path,
            "size": size, "latency_ms": ms, "payload": payload})
        return res
