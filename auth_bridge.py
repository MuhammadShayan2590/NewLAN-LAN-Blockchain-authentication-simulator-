"""FreeRADIUS python3 module: MAC authentication against the DeviceAuth contract.

Uses only the Python standard library (no web3). Third-party C-extension packages
often fail to load inside FreeRADIUS's embedded Python sub-interpreter, which
makes the whole server exit at start-up, so this talks to the node directly via
JSON-RPC (eth_call) instead.
"""
import json
import os
import urllib.request
from pathlib import Path

import radiusd

GANACHE_URL = os.getenv("GANACHE_URL", "http://host.docker.internal:8545")
INFO_FILE = Path(__file__).with_name("contract_info.json")

# keccak256("isDeviceAuthorized(string)")[:4]
SELECTOR = "17a60199"


def _encode_call(mac):
    """ABI-encode isDeviceAuthorized(string): selector + offset + length + padded data."""
    data = mac.encode()
    padded = data + b"\x00" * (-len(data) % 32)
    return "0x" + SELECTOR + (32).to_bytes(32, "big").hex() + len(data).to_bytes(32, "big").hex() + padded.hex()


def is_device_authorized(mac):
    address = json.loads(INFO_FILE.read_text())["address"]   # re-read: survives redeploys
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "eth_call",
        "params": [{"to": address, "data": _encode_call(mac)}, "latest"],
    }).encode()
    req = urllib.request.Request(GANACHE_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = json.loads(resp.read().decode())
    if "error" in body:
        raise RuntimeError(body["error"])
    result = body["result"]
    return result not in ("0x", None) and int(result, 16) != 0


def authorize(p):
    request = dict(p)
    raw_mac = request.get("Calling-Station-Id", "").replace('"', "")
    mac = raw_mac.replace("-", "").replace(":", "").replace(".", "").strip().upper()

    if len(mac) != 12:
        radiusd.radlog(radiusd.L_INFO, f"BLOCKCHAIN AUTH: bad or missing MAC '{raw_mac}'")
        return radiusd.RLM_MODULE_REJECT

    try:
        allowed = is_device_authorized(mac)
    except Exception as e:
        radiusd.radlog(radiusd.L_ERR, f"Bridge exception: {e}")
        return radiusd.RLM_MODULE_REJECT

    if allowed:
        radiusd.radlog(radiusd.L_INFO, f"BLOCKCHAIN AUTH SUCCESS: {mac}")
        # Auth-Type := Accept is required, otherwise FreeRADIUS still rejects
        # with "No Auth-Type found" even though authorize returned OK.
        return radiusd.RLM_MODULE_OK, (), (("Auth-Type", "Accept"),)

    radiusd.radlog(radiusd.L_INFO, f"BLOCKCHAIN AUTH FAIL: {mac} not on ledger")
    return radiusd.RLM_MODULE_REJECT
