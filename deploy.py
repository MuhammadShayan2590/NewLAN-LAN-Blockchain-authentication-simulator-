"""Compile DeviceAuth.sol, deploy it to Ganache, and write contract_info.json
(address + ABI) which every other script and the Docker container read."""
import json
import os
import sys
from pathlib import Path

from solcx import compile_standard, install_solc
from web3 import Web3

GANACHE_URL = os.getenv("GANACHE_URL", "http://127.0.0.1:8545")
SOLC_VERSION = "0.8.19"   # 0.8.20+ emits PUSH0, which Ganache does not support
HERE = Path(__file__).parent

w3 = Web3(Web3.HTTPProvider(GANACHE_URL))
if not w3.is_connected():
    sys.exit("Could not connect to Ganache. Is it running at " + GANACHE_URL + "?")

source = (HERE / "DeviceAuth.sol").read_text()
install_solc(SOLC_VERSION)  # needs internet the first time only
compiled = compile_standard(
    {
        "language": "Solidity",
        "sources": {"DeviceAuth.sol": {"content": source}},
        "settings": {
            "evmVersion": "paris",
            "outputSelection": {"*": {"*": ["abi", "evm.bytecode.object"]}},
        },
    },
    solc_version=SOLC_VERSION,
)
c = compiled["contracts"]["DeviceAuth.sol"]["DeviceAuth"]
abi, bytecode = c["abi"], c["evm"]["bytecode"]["object"]

admin = w3.eth.accounts[0]
print(f"Deploying from Ganache account 0: {admin}")
Contract = w3.eth.contract(abi=abi, bytecode=bytecode)
tx_hash = Contract.constructor().transact({"from": admin})
receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

info = {"address": receipt.contractAddress, "admin": admin, "abi": abi}
(HERE / "contract_info.json").write_text(json.dumps(info, indent=2))

print("=" * 40)
print("Contract deployed:", receipt.contractAddress)
print("Saved to contract_info.json (no need to copy the address anywhere)")
print("=" * 40)
