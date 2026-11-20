# NewLAN

Blockchain-secured network access control. A device is allowed onto the network only if its MAC address is on
a smart-contract allowlist (Ganache). FreeRADIUS, running in Docker, checks that list for every login.
Everything is operated from one desktop app: **NewLAN**.

## What you need (one-time install)

| Program | Why | Where |
|---|---|---|
| **Python 3.10+** | runs the app | python.org/downloads. In the installer tick **"Add python.exe to PATH"** and keep **tcl/tk and IDLE** ticked |
| **Docker Desktop** | runs the FreeRADIUS server | docker.com/products/docker-desktop |
| **Node.js (LTS)** | only to install Ganache from inside the app | nodejs.org. Not needed if you use the Ganache desktop app |
| Internet | first run only: Python packages, Solidity compiler, Docker image | |

## How to run it

1. Keep every file from this folder together in one folder.
2. Start **Docker Desktop** and wait until it says it is running.
3. Double-click **`Start NewLAN.bat`** (or `NewLAN.pyw` directly).
   The first launch installs the Python packages by itself (about a minute).
4. On the **Home** page press **Start**. NewLAN starts Ganache, deploys the contract (`deploy.py`) and builds and
   starts FreeRADIUS (`docker-compose.yml`). The first Docker build takes a few minutes.
   If Ganache is missing, press **Install Ganache** under *Advanced* first (needs Node.js).
5. When the four status cards are green and the badge says **All systems running**, you are ready.
6. Press **Stop** when you are done (or close the window and choose *Yes* to stop the services).

Next time you only need steps 2, 3 and **Start**. Ganache keeps its data in `ganache_data`, so the contract and
the device list survive restarts.

## Using the app

Click the **☰** button (top left) to slide out the menu. Press **Esc** or click outside it to close it.

| Page | What it does |
|---|---|
| **Home** | Start and Stop, live status of the four services, and *Advanced* actions (redeploy contract, install Ganache, view server log) |
| **Devices** | Type a MAC (e.g. `AA-BB-CC-DD-EE-FF`) and press **Register**. Optionally type X, Y and Z to place it; leave them blank for a random position. **Revoke** removes access, **Check** shows the current status. The table lists every device on the ledger |
| **Router** | The eduroam mesh network: all five routers and their devices, and live communication between any two connected devices |
| **Eduroam testbed** | Routers placed in a 3D space; place devices at (x, y, z) and watch them pick the best router and roam |
| **Packet store** | Every packet sent across the eduroam network, saved, searchable and exportable |
| **Test login** | Enter a MAC and press **Send test login**. A packet animates from the device to the RADIUS server and on to the blockchain and back, while the **Message** box shows the request that was sent and the reply. The result is **ACCEPTED** for a registered device and **REJECTED** for any other |
| **Activity log** | Everything the app, Ganache, Docker and the server are doing. Copy, save or clear it |
| **Settings** | Blockchain address and the RADIUS shared secret |


### The Eduroam testbed

Five routers (**R1 Library, R2 Lab, R3 Hall, R4 Cafe, R5 Dorm**) are placed in a 100 x 70 x 12 m space. They are
joined in a full mesh and share one network (`10.20.0.0/24`), like eduroam: **a single registration on the blockchain
lets a device connect through any router.**

- **Placing devices.** Every registered device has a position (x, y, z in metres). Type it when you register the device
  (Devices page) or leave it blank for a random spot. On the testbed page, pick a device and press **Move here**,
  **Random position**, or simply **click on the map** (the top view sets X and Y, the Z box sets the height).
  The small *side view* shows the height of each device and router.
- **Choosing the best router.** Each router is scored for the device:
  `score = 60% signal quality + 40% spare capacity`. Signal depends on the distance (log-distance path loss, usable
  down to -78 dBm, about 52 m); spare capacity falls as devices connect (each router holds 5). A router that is
  full or out of range is skipped. The **Router choice** table at the bottom shows the distance, signal, load and
  score of all five routers and marks the best one, so you can see exactly why it was chosen.
- **Connecting.** **Connect (best router)** admits the device (the real RADIUS server if it is running, otherwise the
  blockchain) and attaches it to its best router. **Connect all** does this for every registered device.
- **Roaming.** After you move a device, **Reconnect to best** re-scores the routers and switches if another is now
  better. Tick **Reconnect automatically after moving** to do it on every move. **Reconnect all devices** re-evaluates
  everyone. Sessions that are already open keep working while a device roams.
- **Display options.** *Show coverage range* draws each router's range; *Show other routers in range* draws faint
  lines to the routers a device could have used.

### The Router page

The routers as a mesh, and live communication between the devices connected to them.

**Network** shows the five routers joined in a full mesh with a dot for every attached device, and a table of all
devices (router, IP, status). You can connect, disconnect and rename devices here too.

**Connections**
1. Pick **Device A** and **Device B** from the connected devices. They can be on the same router or on different
   routers; traffic crosses the mesh between routers. Press **Establish connection**.
2. A live session opens with one **interface box per device**: name, IP, MAC, the router it is using, its own message
   log and a message line.
3. Type in either box and press Send. The diagram shows the packet's whole route, for example
   *Device A -> R1 -> R5 -> Device B*. The first router checks **both** devices against the blockchain before the
   packet continues. The sender sees "delivered" with the time and route, and the receiver sees the message.
4. **Ping A -> B** / **Ping B -> A** send four echo requests with replies and statistics. **Run demo** plays a
   scripted conversation.
5. If a device **roams** during a session, both boxes announce it and the route in the diagram changes.
6. If a device is **revoked** on the Devices page, the network removes it within about 3 seconds (or at its next
   packet), closes its sessions and both boxes show why.

### The Packet store

Every packet sent across the eduroam network is recorded: messages, ping requests and replies, delivered or
dropped. Each record holds the time, kind, sender and receiver (name, IP, MAC), both routers, the route, size,
latency, the data, and the reason if it was dropped. New packets appear at the top as they are sent. You can search
(device, IP, router or text), filter by kind and status, click a row for full details, **Export CSV**, or
**Clear store**. Packets are also saved in `eduroam_packets.jsonl`, so they are still there after a restart.

### Using the Ganache desktop app instead
Open it yourself, copy its address (usually `http://127.0.0.1:7545`) into **Settings > Blockchain address**,
press **Apply**, then press **Start** on Home. NewLAN will not start its own Ganache.

## Pointing a real access point or switch at it
Set the RADIUS server to this PC's IP address, port **1812/udp**, with the shared secret from **Settings**
(default `testing123`). Allow UDP 1812 and 1813 through Windows Firewall. The device's MAC must arrive in the
`Calling-Station-Id` attribute, which is normal for MAC authentication.

## Files

| File | Role |
|---|---|
| `Start NewLAN.bat` | Double-click launcher. Checks Python and tkinter, then opens the app with no console window |
| `NewLAN.pyw` | **The interface** (Home, sidebar, Devices, Test login, Activity log, Settings) |
| `newlan_core.py` | App logic: Ganache, Docker, deployment, devices, RADIUS test client |
| `newlan_eduroam.py` | The eduroam model: routers in 3D, best-router scoring, roaming, mesh paths, connections, packet store |
| `newlan_router_ui.py` | The Router page: mesh network view, connections, interface boxes, live animation |
| `newlan_eduroam_ui.py` | The Eduroam testbed page: map, side view, controls, router-choice table |
| `newlan_packets_ui.py` | The Packet store page |
| `newlan_widgets.py` | Shared red-and-white theme and buttons used by every page |
| `DeviceAuth.sol` | The smart contract |
| `deploy.py` | Compiles and deploys the contract and writes `contract_info.json` (run by the app) |
| `auth_bridge.py` | Runs inside FreeRADIUS; asks the blockchain whether a MAC is allowed (standard library only) |
| `docker-compose.yml`, `Dockerfile`, `python3.conf`, `default_site.conf`, `clients.conf` | FreeRADIUS container setup |
| `requirements.txt` | Python packages (installed automatically) |
| `register_device.py`, `app.py` | Optional extras: command-line register/revoke, and a browser dashboard (`pip install flask`). Not needed |
| `gui_settings.json`, `contract_info.json`, `eduroam_state.json`, `eduroam_packets.jsonl`, `ganache_data/` | Created automatically (device names, IPs and positions; stored packets) |

## Troubleshooting

- **Nothing opens:** the `.bat` window tells you if Python or tkinter is missing. If the app starts and then
  crashes, details are written to `newlan_error.log` next to the files.
- **Docker card is red:** start Docker Desktop and wait for it to finish starting.
- **RADIUS card says "Container state: exited":** open **Activity log** (or press *View server log* on Home).
  NewLAN prints the server's last log lines and a likely cause. Press **Stop**, then **Start** to rebuild.
- **Test login says NO REPLY:** the server is not running, Windows Firewall blocks UDP 1812, or the secret differs.
- **Test login says REJECTED for a registered device:** check the Activity log. A common cause is the container not
  reaching Ganache; try ticking *Let Ganache listen on all network interfaces* in Settings, restart Ganache and
  the server.
- **"Saved contract not found on this chain":** Ganache was restarted without its data folder. Use
  *Deploy / redeploy contract* under Advanced and register your devices again.
- **Router / Eduroam pages say the blockchain is not running:** press Start on Home first. The network needs the
  blockchain to admit devices and to check every packet.
- **A device will not connect ("no router in range with free capacity"):** its position is out of range of all routers
  (about 52 m) or every router in range already holds 5 devices. Move it or disconnect another device.
- **Deploy fails on first run:** it downloads the Solidity compiler, so check your internet connection.

## Security notes (lab setup)
- `clients.conf` accepts RADIUS requests from any IP that knows the shared secret. Restrict `ipaddr` to your
  access-point network and change the secret before real use.
- Ganache accounts are unlocked and deterministic: anyone who can reach its port controls the allowlist.
  Keep it on `127.0.0.1` unless you must change that. Ganache is also deprecated; for production use a real
  chain with a properly protected admin key.
