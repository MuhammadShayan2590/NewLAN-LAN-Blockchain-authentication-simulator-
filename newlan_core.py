"""NewLAN backend: everything the UI uses that is not drawing.

No tkinter in here. The UI passes in `log(text)` and `notify(title, message)` callbacks.
"""
import hashlib
import hmac
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SETTINGS_FILE = HERE / "gui_settings.json"
INFO_FILE = HERE / "contract_info.json"
CONTAINER = "freeradius_bridge"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
IS_WINDOWS = sys.platform.startswith("win")

DEFAULTS = {
    "rpc_url": "http://127.0.0.1:8545",
    "radius_secret": "testing123",
    "radius_host": "127.0.0.1",
    "radius_port": 1812,
    "listen_all": sys.platform.startswith("linux"),
}


def python_exe():
    """python.exe rather than pythonw.exe, so child scripts can print output."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        return str(exe.with_name("python.exe"))
    return str(exe)


def load_settings():
    data = dict(DEFAULTS)
    try:
        data.update(json.loads(SETTINGS_FILE.read_text()))
    except Exception:
        pass
    return data


def save_settings(data):
    SETTINGS_FILE.write_text(json.dumps(data, indent=2))


def normalize_mac(raw):
    mac = re.sub(r"[-:.\s]", "", raw or "").upper()
    if not re.fullmatch(r"[0-9A-F]{12}", mac):
        raise ValueError("Enter a valid MAC address, e.g. AA-BB-CC-DD-EE-FF")
    return mac


def pretty_mac(mac):
    return "-".join(mac[i:i + 2] for i in range(0, 12, 2))


def kill_tree(proc):
    """Stop a process and its children (ganache.cmd spawns node)."""
    try:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, creationflags=NO_WINDOW)
        else:
            proc.terminate()
    except Exception:
        pass


# --------------------------------------------------------------------------- RADIUS test client

def radius_test(host, port, secret, mac_text, timeout=5.0):
    """Send one Access-Request like an access point would. Returns (kind, detail)."""
    secret_b = secret.encode()
    ident = os.urandom(1)[0]
    req_auth = os.urandom(16)

    def attr(t, v):
        return bytes([t, len(v) + 2]) + v

    attrs = (attr(1, b"mac-auth-test") + attr(4, socket.inet_aton("127.0.0.1"))
             + attr(31, mac_text.encode()) + attr(80, b"\x00" * 16))
    pkt = struct.pack("!BBH", 1, ident, 20 + len(attrs)) + req_auth + attrs
    ma = hmac.new(secret_b, pkt, hashlib.md5).digest()   # Message-Authenticator
    pkt = pkt[:-16] + ma

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(pkt, (host, port))
        data, _ = sock.recvfrom(4096)
    except socket.timeout:
        return "timeout", ("No reply. Is the FreeRADIUS server running? A wrong shared secret "
                           "or a blocked port also causes this.")
    except OSError as e:
        return "error", str(e)
    finally:
        sock.close()

    expected = hashlib.md5(data[:4] + req_auth + data[20:] + secret_b).digest()
    if data[4:20] != expected:
        return "badsecret", "A reply arrived but its signature is wrong: the shared secret does not match."
    return {2: "accept", 3: "reject", 11: "challenge"}.get(data[0], "other"), f"RADIUS code {data[0]}"


def describe_request(mac_text, host, port):
    """The fields radius_test sends, for display in the UI."""
    return [("To", f"{host}:{port} (UDP)"), ("Code", "Access-Request"), ("User-Name", "mac-auth-test"),
            ("NAS-IP-Address", "127.0.0.1"), ("Calling-Station-Id", mac_text),
            ("Message-Authenticator", "signed with shared secret")]


# --------------------------------------------------------------------------- blockchain

class Chain:
    def __init__(self, url):
        from web3 import Web3
        self.Web3 = Web3
        self.url = url
        self.w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 5}))

    def connected(self):
        try:
            return bool(self.w3.is_connected())
        except Exception:
            return False

    def info(self):
        return json.loads(INFO_FILE.read_text())

    def contract(self):
        info = self.info()
        return self.w3.eth.contract(address=self.Web3.to_checksum_address(info["address"]), abi=info["abi"])

    def deployed_address(self):
        """Address if the saved contract really exists on this chain, else None."""
        try:
            addr = self.Web3.to_checksum_address(self.info()["address"])
            return addr if len(self.w3.eth.get_code(addr)) > 0 else None
        except Exception:
            return None

    @staticmethod
    def _logs(event):
        try:
            return event.get_logs(from_block=0)      # web3 v7
        except TypeError:
            return event.get_logs(fromBlock=0)       # web3 v6

    def devices(self):
        c = self.contract()
        events = []
        for name, state in (("DeviceRegistered", True), ("DeviceRevoked", False)):
            for lg in self._logs(getattr(c.events, name)):
                events.append((lg["blockNumber"], lg["logIndex"], lg["args"]["macAddress"], state))
        events.sort()
        latest = {}
        for block, _, mac, state in events:
            latest[mac] = (pretty_mac(mac), state, block)
        return sorted(latest.values(), key=lambda r: -r[2])

    def is_authorized(self, mac):
        return self.contract().functions.isDeviceAuthorized(mac).call()

    def send(self, action, mac):
        c = self.contract()
        admin = c.functions.admin().call()
        fn = c.functions.registerDevice if action == "register" else c.functions.revokeDevice
        return self.w3.eth.wait_for_transaction_receipt(fn(mac).transact({"from": admin}))


# --------------------------------------------------------------------------- services

class Backend:
    """Starts/stops Ganache, deploys the contract and controls the FreeRADIUS container."""

    def __init__(self, log, notify):
        self.log = log
        self.notify = notify
        self.settings = load_settings()
        self.chain = Chain(self.settings["rpc_url"])
        self.ganache_proc = None
        self.status = {}

    # ---- settings
    def apply_settings(self, rpc_url, secret, listen_all):
        rpc_url = rpc_url.strip()
        if not re.match(r"^https?://[^/\s]+", rpc_url):
            raise ValueError("Use an address like http://127.0.0.1:8545")
        self.settings.update(rpc_url=rpc_url, radius_secret=secret.strip() or "testing123",
                             listen_all=bool(listen_all))
        save_settings(self.settings)
        self.chain = Chain(rpc_url)

    def rpc_port(self):
        m = re.search(r":(\d+)", self.settings["rpc_url"].split("//", 1)[-1])
        return int(m.group(1)) if m else 8545

    def compose_env(self):
        env = dict(os.environ)
        env["CONTAINER_GANACHE_URL"] = f"http://host.docker.internal:{self.rpc_port()}"
        env["RADIUS_SECRET"] = self.settings["radius_secret"]
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    # ---- status
    def poll(self):
        st = {"ganache": self.chain.connected()}
        st["address"] = self.chain.deployed_address() if st["ganache"] else None
        st["info_exists"] = INFO_FILE.exists()
        if not shutil.which("docker"):
            st["docker"], st["container"] = "missing", None
        else:
            try:
                r = subprocess.run(["docker", "ps", "-a", "--filter", f"name=^{CONTAINER}$", "--format", "{{.State}}"],
                                   capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW)
                if r.returncode != 0:
                    st["docker"], st["container"] = "stopped", None
                else:
                    st["docker"], st["container"] = "ok", (r.stdout.strip() or "none")
            except Exception:
                st["docker"], st["container"] = "stopped", None
        self.status = st
        return st

    # ---- streaming subprocess
    def stream(self, cmd, env=None, prefix=""):
        try:
            p = subprocess.Popen(cmd, cwd=HERE, env=env or self.compose_env(), stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                 creationflags=NO_WINDOW)
        except FileNotFoundError:
            self.log(f"Program not found: {cmd[0]}")
            return 127
        for line in p.stdout:
            line = line.rstrip()
            if line:
                self.log(prefix + line)
        return p.wait()

    # ---- Ganache
    def find_ganache(self):
        return shutil.which("ganache") or shutil.which("ganache-cli")

    def start_ganache(self):
        if self.chain.connected():
            self.log("Blockchain is already running.")
            return True
        exe = self.find_ganache()
        if not exe:
            self.notify("Ganache not found",
                        "The command-line Ganache is not installed.\n\n"
                        "Option A: use 'Install Ganache' on the Home page (needs Node.js from nodejs.org).\n"
                        "Option B: open the Ganache desktop app yourself, enter its address under Settings "
                        "(usually http://127.0.0.1:7545) and click Apply.")
            self.log("Ganache not found. Use 'Install Ganache' or start the Ganache app manually.")
            return False
        host = "0.0.0.0" if self.settings["listen_all"] else "127.0.0.1"
        cmd = [exe, "--server.host", host, "--server.port", str(self.rpc_port()),
               "--wallet.deterministic", "--database.dbPath", str(HERE / "ganache_data")]
        self.log("Starting Ganache (data is kept in the ganache_data folder, so the contract survives restarts)...")
        self.ganache_proc = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                             text=True, encoding="utf-8", errors="replace",
                                             creationflags=NO_WINDOW)

        def pump(proc):
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    self.log("[ganache] " + line)
        threading.Thread(target=pump, args=(self.ganache_proc,), daemon=True).start()
        for _ in range(60):
            if self.chain.connected():
                self.log("Ganache is up.")
                return True
            if self.ganache_proc.poll() is not None:
                self.log("Ganache exited unexpectedly. See messages above (is the port already in use?).")
                return False
            time.sleep(0.5)
        self.log("Ganache did not respond in 30 seconds.")
        return False

    def stop_ganache(self):
        if self.ganache_proc and self.ganache_proc.poll() is None:
            kill_tree(self.ganache_proc)
            self.log("Ganache stopped.")
        elif self.chain.connected():
            self.log("This Ganache was not started by NewLAN. Close it yourself.")
        self.ganache_proc = None

    def install_ganache(self):
        npm = shutil.which("npm")
        if not npm:
            self.log("npm not found. Install Node.js from https://nodejs.org, then try again.")
            self.notify("Node.js needed", "Install Node.js from https://nodejs.org (LTS), then click 'Install Ganache' again.")
            return
        self.log("Installing Ganache (npm install -g ganache)...")
        rc = self.stream([npm, "install", "-g", "ganache"])
        self.log("Ganache installed." if rc == 0 else "Ganache install failed (see messages above).")

    # ---- contract
    def deploy(self):
        if not self.chain.connected():
            self.log("Blockchain is not running. Start it first.")
            return False
        env = self.compose_env()
        env["GANACHE_URL"] = self.settings["rpc_url"]
        self.log("Compiling and deploying (the first run downloads the Solidity compiler, needs internet)...")
        rc = self.stream([python_exe(), "-u", str(HERE / "deploy.py")], env=env)
        if rc != 0:
            self.log("Deployment failed (see messages above).")
            return False
        self.log("Contract deployed.")
        if self.status.get("container") == "running":
            self.log("Restarting FreeRADIUS so it picks up the new contract...")
            self.stream(["docker", "compose", "restart"])
        return True

    # ---- Docker
    def docker_ready(self):
        if not shutil.which("docker"):
            self.log("Docker is not installed. Install Docker Desktop and try again.")
            return False
        r = subprocess.run(["docker", "info"], capture_output=True, text=True, creationflags=NO_WINDOW)
        if r.returncode != 0:
            self.log("Docker is not running. Open Docker Desktop, wait until it says it is running, then try again.")
            return False
        return True

    def docker_up(self):
        if not self.docker_ready():
            return False
        if not INFO_FILE.exists():
            self.log("No contract_info.json yet. Deploy the contract first (or use Start).")
            return False
        self.log("Building and starting FreeRADIUS (the first build takes a few minutes)...")
        rc = self.stream(["docker", "compose", "up", "-d", "--build"])
        if rc != 0:
            self.log("FreeRADIUS failed to start (see messages above).")
            return False
        # A container can start and then quit a second later, so wait and re-check
        self.log("Checking that the server stays up...")
        for _ in range(8):
            time.sleep(1)
            if self.container_state() != "running":
                break
        if self.container_state() == "running":
            self.log("FreeRADIUS is running.")
            return True
        self.log("FreeRADIUS stopped right after starting. Reading its log to find out why:")
        self.diagnose_container()
        return False

    def docker_down(self):
        if not self.docker_ready():
            return False
        rc = self.stream(["docker", "compose", "down"])
        self.log("FreeRADIUS stopped." if rc == 0 else "Could not stop FreeRADIUS.")
        return rc == 0

    def container_state(self):
        r = subprocess.run(["docker", "inspect", "-f", "{{.State.Status}}", CONTAINER],
                           capture_output=True, text=True, creationflags=NO_WINDOW)
        return r.stdout.strip() if r.returncode == 0 else "missing"

    def diagnose_container(self):
        """Print the server log and a plain-language guess at the cause."""
        ex = subprocess.run(["docker", "inspect", "-f", "{{.State.ExitCode}}", CONTAINER],
                            capture_output=True, text=True, creationflags=NO_WINDOW).stdout.strip()
        r = subprocess.run(["docker", "logs", "--tail", "80", CONTAINER], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        text = (r.stdout or "") + (r.stderr or "")
        lines = [l for l in text.splitlines() if l.strip()]
        self.log(f"Container exit code: {ex or '?'}. Last lines of the server log:")
        for line in lines[-25:]:
            self.log("[radius] " + line)
        hints = [
            (("Address already in use", "Failed binding"), "Another program is already using UDP port 1812/1813. Close it (or an old FreeRADIUS) and try again."),
            (("ModuleNotFoundError", "No module named"), "The Python bridge could not import a package. Press Start again so the image is rebuilt with the latest files."),
            (("rlm_python3", "Failed to link", "Failed loading", "Unable to open module"), "The FreeRADIUS Python module did not load. Rebuild the image (Stop, then Start). If it repeats, send the log lines above."),
            (("Failed reading", "Unknown", "Parse error", "Failed to parse"), "A FreeRADIUS config file has a syntax error. Send the log lines above so it can be fixed."),
            (("$ENV{", "RADIUS_SECRET"), "The RADIUS secret was not passed to the container. Set it in Settings, click Apply, then Start again."),
            (("Permission denied",), "A file could not be read inside the container. Make sure Docker Desktop has access to this folder (Settings > Resources > File sharing)."),
        ]
        for needles, advice in hints:
            if any(n in text for n in needles):
                self.log("LIKELY CAUSE: " + advice)
                return
        self.log("No known cause matched. Please copy the log lines above and send them to get a precise fix.")

    def show_radius_log(self):
        if not shutil.which("docker"):
            self.log("Docker is not installed.")
            return
        if self.container_state() == "missing":
            self.log("The FreeRADIUS container has not been created yet. Press Start.")
            return
        self.log("--- FreeRADIUS server log ---")
        self.diagnose_container()

    # ---- everything
    def start_all(self):
        if not self.chain.connected() and not self.start_ganache():
            return
        if not self.chain.deployed_address() and not self.deploy():
            return
        self.status["container"] = None   # avoid a pointless restart inside deploy()
        if self.docker_up():
            self.log("All services are running. Use Devices and Test login from the menu.")

    def stop_all(self):
        if shutil.which("docker"):
            self.docker_down()
        self.stop_ganache()

    # ---- router simulation helpers
    def ledger_allows(self, mac):
        """Live check against the smart contract (raises if the chain is unreachable)."""
        return bool(self.chain.is_authorized(mac))

    def router_authenticate(self, mac):
        """How the network admits a device: ask the real RADIUS server first; if it is not running,
        fall back to the blockchain directly. Returns (allowed, how).
        A RADIUS timeout is remembered for 20 s so connecting many devices stays fast."""
        s = self.settings
        if time.time() >= getattr(self, "_radius_down_until", 0):
            kind, _ = radius_test(s["radius_host"], int(s["radius_port"]), s["radius_secret"], mac, timeout=1.5)
            if kind == "accept":
                return True, "the RADIUS server"
            if kind == "reject":
                return False, "the RADIUS server"
            self._radius_down_until = time.time() + 20
        try:
            return self.ledger_allows(mac), "the blockchain (RADIUS server not running)"
        except Exception:
            return False, "nobody: the blockchain is not reachable"
