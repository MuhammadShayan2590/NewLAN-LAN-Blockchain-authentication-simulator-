"""NewLAN simulated router: which registered devices have joined, and the connections between them.

No tkinter in here. Authorization is always decided by the callbacks the caller passes in
(RADIUS server / blockchain), never by this module.
"""
import json
import threading
import time
from pathlib import Path

from newlan_core import HERE, pretty_mac

STATE_FILE = HERE / "router_state.json"
SUBNET = "192.168.10"
ROUTER_IP = SUBNET + ".1"
POOL_START, POOL_END = 11, 99


class RouterSim:
    def __init__(self, state_file=STATE_FILE):
        self.state_file = Path(state_file)
        self.lock = threading.RLock()
        self.leases = {}        # raw MAC -> {"name": str, "ip": str}   (saved to disk)
        self.connected = {}     # raw MAC -> time joined               (this session only)
        self.connections = {}   # id -> connection dict                (this session only)
        self.next_cid = 1
        self._load()

    # ---- persistence
    def _load(self):
        try:
            self.leases = json.loads(self.state_file.read_text()).get("devices", {})
        except Exception:
            self.leases = {}

    def _save(self):
        try:
            self.state_file.write_text(json.dumps({"devices": self.leases}, indent=2))
        except OSError:
            pass

    # ---- device info
    def name(self, mac):
        n = self.leases.get(mac, {}).get("name")
        return n or f"Device-{mac[-4:]}"

    def set_name(self, mac, name):
        with self.lock:
            lease = self.leases.setdefault(mac, {})
            name = (name or "").strip()[:24]
            if name:
                lease["name"] = name
            else:
                lease.pop("name", None)
            self._save()

    def ip(self, mac):
        return self.leases.get(mac, {}).get("ip", "")

    def is_connected(self, mac):
        return mac in self.connected

    def _assign_ip(self, mac):
        lease = self.leases.setdefault(mac, {})
        if lease.get("ip"):
            return lease["ip"]
        used = {v.get("ip") for v in self.leases.values()}
        for n in range(POOL_START, POOL_END + 1):
            ip = f"{SUBNET}.{n}"
            if ip not in used:
                lease["ip"] = ip
                return ip
        raise RuntimeError("The router has no free addresses left")

    # ---- joining and leaving
    def join(self, mac, auth_fn):
        """auth_fn(mac) -> (allowed, how). Returns (allowed, how, ip)."""
        allowed, how = auth_fn(mac)           # slow (network), so outside the lock
        if not allowed:
            return False, how, None
        with self.lock:
            ip = self._assign_ip(mac)
            self.connected[mac] = time.time()
            self._save()
        return True, how, ip

    def leave(self, mac, reason=None):
        """Remove a device from the router. Returns the ids of connections that were closed."""
        with self.lock:
            self.connected.pop(mac, None)
            closed = []
            for cid, c in self.connections.items():
                if c["state"] == "open" and mac in (c["a"], c["b"]):
                    c["state"], c["reason"] = "closed", reason or f"{self.name(mac)} left the router"
                    closed.append(cid)
            return closed

    # ---- connections between two end devices
    def open_connection(self, a, b):
        with self.lock:
            if a == b:
                raise ValueError("Pick two different devices.")
            for m in (a, b):
                if m not in self.connected:
                    raise ValueError(f"{self.name(m)} is not connected to the router.")
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
    def forward(self, cid, src, check_fn):
        """The router checks BOTH ends against the ledger before passing a packet on.

        check_fn(mac) -> bool. A device that is no longer authorized is removed from the router
        and its connections are closed. Returns a result dict.
        """
        t0 = time.perf_counter()
        with self.lock:
            conn = self.connections.get(cid)
            if not conn or conn["state"] != "open":
                return {"ok": False, "reason": "The connection is closed.", "kicked": [], "closed": []}
            dst = conn["b"] if src == conn["a"] else conn["a"]
            conn["seq"] += 1
            conn["sent"] += 1
            seq = conn["seq"]
        kicked = []
        for mac in (src, dst):
            try:
                allowed = check_fn(mac)
            except Exception:
                with self.lock:
                    conn["dropped"] += 1
                return {"ok": False, "reason": "The router cannot reach the blockchain to verify the devices.",
                        "kicked": [], "closed": []}
            if not allowed:
                kicked.append(mac)
        ms = round((time.perf_counter() - t0) * 1000 + 1.2, 1)
        if kicked:
            closed = []
            for mac in kicked:
                closed += self.leave(mac, f"{self.name(mac)} is no longer authorized on the blockchain")
            with self.lock:
                conn["dropped"] += 1
            names = " and ".join(self.name(m) for m in kicked)
            return {"ok": False, "reason": f"{names} not authorized on the blockchain, removed from the router",
                    "kicked": kicked, "closed": sorted(set(closed)), "seq": seq, "ms": ms}
        with self.lock:
            conn["delivered"] += 1
        return {"ok": True, "reason": "", "kicked": [], "closed": [], "seq": seq, "ms": ms,
                "src_ip": self.ip(src), "dst_ip": self.ip(dst), "src": src, "dst": dst}


def describe(mac):
    return pretty_mac(mac)
