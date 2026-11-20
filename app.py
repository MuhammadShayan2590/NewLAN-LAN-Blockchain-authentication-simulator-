"""Admin dashboard for the blockchain MAC-authentication project.

Run:  python app.py      then open http://127.0.0.1:5000
Needs: contract_info.json (created by deploy.py) and Ganache running.
"""
import json
import os
import re
from pathlib import Path

from flask import Flask, jsonify, request
from web3 import Web3

GANACHE_URL = os.getenv("GANACHE_URL", "http://127.0.0.1:8545")
INFO_FILE = Path(__file__).with_name("contract_info.json")

app = Flask(__name__)
w3 = Web3(Web3.HTTPProvider(GANACHE_URL, request_kwargs={"timeout": 10}))


def load_contract():
    info = json.loads(INFO_FILE.read_text())
    return w3.eth.contract(address=Web3.to_checksum_address(info["address"]), abi=info["abi"])


def normalize_mac(raw):
    mac = re.sub(r"[-:.\s]", "", raw or "").upper()
    if not re.fullmatch(r"[0-9A-F]{12}", mac):
        raise ValueError("Enter a valid MAC address, e.g. AA-BB-CC-DD-EE-FF")
    return mac


def pretty(mac):
    return "-".join(mac[i:i + 2] for i in range(0, 12, 2))


def get_logs(event):
    try:
        return event.get_logs(from_block=0)      # web3 v7
    except TypeError:
        return event.get_logs(fromBlock=0)       # web3 v6


def fail(msg, code=400):
    return jsonify(ok=False, error=str(msg)), code


@app.get("/api/status")
def status():
    if not w3.is_connected():
        return jsonify(connected=False, error="Cannot reach Ganache at " + GANACHE_URL)
    try:
        c = load_contract()
        return jsonify(connected=True, contract=c.address, admin=c.functions.admin().call(),
                       block=w3.eth.block_number, chain_id=w3.eth.chain_id, rpc=GANACHE_URL)
    except FileNotFoundError:
        return jsonify(connected=True, error="contract_info.json not found. Run deploy.py first.")
    except Exception as e:
        return jsonify(connected=True, error="Contract not found on this chain (was Ganache restarted? "
                                              "Re-run deploy.py). " + str(e))


@app.get("/api/devices")
def devices():
    try:
        c = load_contract()
        events = []
        for name, state in (("DeviceRegistered", True), ("DeviceRevoked", False)):
            for log in get_logs(getattr(c.events, name)):
                events.append((log["blockNumber"], log["logIndex"], log["args"]["macAddress"], state))
        events.sort()
        latest = {}
        for block, _, mac, state in events:
            latest[mac] = {"mac": pretty(mac), "raw": mac, "authorized": state, "block": block}
        rows = sorted(latest.values(), key=lambda r: -r["block"])
        return jsonify(ok=True, devices=rows)
    except Exception as e:
        return fail(e, 500)


@app.get("/api/check")
def check():
    try:
        mac = normalize_mac(request.args.get("mac"))
        allowed = load_contract().functions.isDeviceAuthorized(mac).call()
        return jsonify(ok=True, mac=pretty(mac), authorized=allowed)
    except Exception as e:
        return fail(e)


def send(action):
    try:
        mac = normalize_mac((request.get_json(silent=True) or {}).get("mac"))
        c = load_contract()
        admin = c.functions.admin().call()
        fn = c.functions.registerDevice if action == "register" else c.functions.revokeDevice
        receipt = w3.eth.wait_for_transaction_receipt(fn(mac).transact({"from": admin}))
        return jsonify(ok=True, mac=pretty(mac), block=receipt.blockNumber,
                       tx=receipt.transactionHash.hex())
    except Exception as e:
        return fail(e)


@app.post("/api/register")
def register():
    return send("register")


@app.post("/api/revoke")
def revoke():
    return send("revoke")


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blockchain MAC Authentication</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--text:#1b1f24;--muted:#667085;--line:#e4e7ec;--accent:#2457d6;--ok:#157f3b;--bad:#b42318}
@media (prefers-color-scheme:dark){:root{--bg:#0f1216;--card:#181c22;--text:#e8eaed;--muted:#98a2b3;--line:#2a3039;--accent:#6b93ff;--ok:#4ade80;--bad:#f87171}}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--text)}
main{max-width:860px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:22px;margin:0 0 4px}.sub{color:var(--muted);margin:0 0 20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:16px}
h2{font-size:15px;margin:0 0 12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.k{color:var(--muted);font-size:12px}.v{font-family:ui-monospace,monospace;font-size:13px;word-break:break-all}
.row{display:flex;gap:8px;flex-wrap:wrap}
input{flex:1;min-width:200px;padding:9px 11px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--text);font:inherit;font-family:ui-monospace,monospace}
button{padding:9px 14px;border:0;border-radius:8px;background:var(--accent);color:#fff;font:inherit;cursor:pointer}
button.sec{background:transparent;color:var(--text);border:1px solid var(--line)}
button.danger{background:var(--bad)}button:disabled{opacity:.5;cursor:wait}
.pill{display:inline-block;padding:1px 9px;border-radius:99px;font-size:12px;border:1px solid currentColor}
.ok{color:var(--ok)}.bad{color:var(--bad)}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px 6px;border-bottom:1px solid var(--line)}
th{font-size:12px;color:var(--muted);font-weight:500}td.m{font-family:ui-monospace,monospace}
#msg{min-height:22px;margin-top:10px}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;background:var(--muted)}
</style></head><body><main>
<h1>Blockchain MAC Authentication</h1>
<p class="sub">Manage which devices FreeRADIUS accepts. The allowlist lives in the DeviceAuth smart contract.</p>

<div class="card"><h2><span class="dot" id="dot"></span><span id="conn">Connecting...</span></h2>
<div class="grid" id="info"></div></div>

<div class="card"><h2>Register, revoke or check a device</h2>
<div class="row"><input id="mac" placeholder="AA-BB-CC-DD-EE-FF" autocomplete="off" spellcheck="false">
<button onclick="act('register')">Register</button>
<button class="danger" onclick="act('revoke')">Revoke</button>
<button class="sec" onclick="check()">Check status</button></div>
<div id="msg"></div></div>

<div class="card"><h2>Devices on the ledger <button class="sec" style="float:right;padding:3px 10px" onclick="load()">Refresh</button></h2>
<table><thead><tr><th>MAC address</th><th>Status</th><th>Block</th><th></th></tr></thead>
<tbody id="rows"><tr><td colspan="4" class="k">Loading...</td></tr></tbody></table></div>
</main>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function say(t,cls){$('msg').innerHTML='<span class="'+(cls||'')+'">'+esc(t)+'</span>'}
async function api(url,opt){const r=await fetch(url,opt);return r.json()}

async function load(){
  const s=await api('/api/status');
  $('dot').style.background=s.connected&&!s.error?'var(--ok)':'var(--bad)';
  $('conn').textContent=s.error?s.error:'Connected to Ganache';
  $('info').innerHTML=s.contract?[['Contract',s.contract],['Admin',s.admin],['Block',s.block],['Chain ID',s.chain_id]]
    .map(([k,v])=>'<div><div class="k">'+k+'</div><div class="v">'+esc(v)+'</div></div>').join(''):'';
  const d=await api('/api/devices');
  if(!d.ok){$('rows').innerHTML='<tr><td colspan="4" class="bad">'+esc(d.error)+'</td></tr>';return}
  $('rows').innerHTML=d.devices.length?d.devices.map(x=>
    '<tr><td class="m">'+esc(x.mac)+'</td><td><span class="pill '+(x.authorized?'ok':'bad')+'">'+
    (x.authorized?'Authorized':'Revoked')+'</span></td><td>'+x.block+'</td><td>'+
    '<button class="sec" style="padding:3px 10px" onclick="quick(\''+x.raw+'\','+(x.authorized?"'revoke'":"'register'")+')">'+
    (x.authorized?'Revoke':'Re-register')+'</button></td></tr>').join('')
    :'<tr><td colspan="4" class="k">No devices registered yet.</td></tr>';
}
function quick(mac,a){$('mac').value=mac;act(a)}
async function act(a){
  const mac=$('mac').value;say('Sending transaction...');
  document.querySelectorAll('button').forEach(b=>b.disabled=true);
  const r=await api('/api/'+a,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mac})});
  document.querySelectorAll('button').forEach(b=>b.disabled=false);
  r.ok?say((a==='register'?'Registered ':'Revoked ')+r.mac+' in block '+r.block,'ok'):say(r.error,'bad');
  load();
}
async function check(){
  const r=await api('/api/check?mac='+encodeURIComponent($('mac').value));
  r.ok?say(r.mac+' is '+(r.authorized?'AUTHORIZED':'NOT authorized'),r.authorized?'ok':'bad'):say(r.error,'bad');
}
$('mac').addEventListener('keydown',e=>{if(e.key==='Enter')act('register')});
load();setInterval(load,10000);
</script></body></html>"""


@app.get("/")
def index():
    return PAGE


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
