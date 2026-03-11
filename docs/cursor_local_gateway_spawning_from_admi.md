# Local gateway spawning from admin UI
_Exported on 3/11/2026 at 19:03:58 GMT+2 from Cursor (2.6.13)_

---

**User**

if a gateway is local on the same server as the server, is it possible to spawn it from admin ui? ideas?

---

**Cursor**

Let me explore the relevant code to understand the current architecture before answering.

Now I have enough context. Let me look at the tools pattern to understand the Tool base class too.

Yes, it is absolutely possible. Here's the picture and the ideas:

---

## What makes it feasible

Both `phbcli` and `phbgateway` are Python packages that would live in the same venv. The gateway already has all the plumbing in place:

- `phbgateway.instance` — reads/writes the gateway registry (`GatewayRegistry`, `GatewayInstanceEntry`) stored in the OS user-data dir
- `phbgateway.config` — `GatewayConfig` only needs the `desktop_public_key` (already available from the phbcli workspace's master key)
- `phbgateway.main._spawn_background()` — already encapsulates the detached `Popen` to start the gateway process
- `phb_commons.process` — shared `is_running / read_pid / stop_process` utilities both sides already use

The gateway URL in the phbcli config (`config.gateway_url`) tells you exactly which local instance to manage.

---

## Design ideas

### Idea 1 — Gateway tool module in `phbcli/tools/` (cleanest)

Follow the exact same pattern as `tools/server.py`. Create a `tools/gateway.py` with:

- **`GatewayStatusTool`** — reads the gateway registry, resolves the instance that matches `config.gateway_url`, checks PID liveness
- **`GatewayStartTool`** — if `phbgateway` is importable and an instance exists for the current workspace's key, call `_spawn_background()` (or replicate it inline)
- **`GatewayStopTool`** — reads gateway PID file and calls `stop_process`
- **`GatewaySetupTool`** — creates the instance (calls `create_instance`) and writes `GatewayConfig` with the workspace's desktop public key
- **`GatewayTeardownTool`** — calls `remove_instance(..., purge=True)`

These integrate naturally into `all_tools()` and become available to agents and the UI alike.

### Idea 2 — Admin UI page "Gateway"

A new sidebar entry under the **Server** group, path `/gateway`. The page would:
- Show gateway instance name, host:port, running/stopped status
- "Start / Stop" buttons wired to `GatewayStartTool` / `GatewayStopTool`
- "Setup local gateway" form (only when no instance found) — one field for port, derives the key automatically from the current workspace
- Optionally tail the gateway log file (same pattern as `logs.py`)

### Idea 3 — Detect "local" automatically

Add a flag or heuristic to `GatewayStatusTool`: if `config.gateway_url` resolves to `localhost` / `127.0.0.1`, treat the gateway as locally managed and surface the Start/Stop controls; otherwise show it as an external gateway (read-only status).

### Idea 4 — Workspace config: `local_gateway_instance`

Add an optional field to `Config`:

```python
local_gateway_instance: str | None = None  # name of the phbgateway instance on this host
```

Set it during `phbcli setup` (or via an admin UI form). When present, the admin UI and tools know which gateway instance to manage. When absent, gateway is treated as external/unmanaged.

---

## Key concern: `phbgateway` availability

Before calling `import phbgateway`, the tool should check it's installed:

```python
import importlib.util
_GATEWAY_AVAILABLE = importlib.util.find_spec("phbgateway") is not None
```

If not available, the UI can show a disabled card with an install hint instead of failing.

---

**My recommendation**: Idea 1 + Idea 2 + Idea 3 combined — the tool layer does the work, the UI just calls the tools and shows local-gateway controls only when the URL is localhost. Idea 4 is optional but useful if you ever want multiple workspaces pointing to different local gateways.

