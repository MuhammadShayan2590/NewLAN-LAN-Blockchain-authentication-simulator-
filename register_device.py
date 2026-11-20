"""CLI helper: python register_device.py AA-BB-CC-DD-EE-FF [revoke]"""
import json
import os
import re
import sys
from pathlib import Path

from web3 import Web3

GANACHE_URL = os.getenv("GANACHE_URL", "http://127.0.0.1:8545")
info = json.loads((Path(__file__).parent / "contract_info.json").read_text())

w3 = Web3(Web3.HTTPProvider(GANACHE_URL))
if not w3.is_connected():
    sys.exit("Could not connect to Ganache at " + GANACHE_URL)

contract = w3.eth.contract(address=Web3.to_checksum_address(info["address"]), abi=info["abi"])
admin = contract.functions.admin().call()

raw = sys.argv[1] if len(sys.argv) > 1 else "AA-BB-CC-DD-EE-FF"
action = sys.argv[2] if len(sys.argv) > 2 else "register"
mac = re.sub(r"[^0-9A-Fa-f]", "", raw).upper()
if len(mac) != 12:
    sys.exit(f"Invalid MAC address: {raw}")

fn = contract.functions.revokeDevice if action == "revoke" else contract.functions.registerDevice
try:
    receipt = w3.eth.wait_for_transaction_receipt(fn(mac).transact({"from": admin}))
    print(f"{action} OK for {mac} | block {receipt.blockNumber} | tx {receipt.transactionHash.hex()}")
except Exception as e:
    sys.exit(f"Error: {e}")
