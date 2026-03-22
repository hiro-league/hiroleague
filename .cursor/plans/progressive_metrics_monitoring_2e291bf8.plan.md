---
name: Progressive Metrics Monitoring
overview: Add system resource monitoring to the hiro server in incremental phases, each delivering a standalone usable outcome. Starts with CPU + memory on the admin UI dashboard, with a disabled-by-default flag and runtime-tunable collection interval.
todos:
  - id: phase-1-foundation
    content: "Phase 1: Add psutil, Config fields, MetricsCollector service, Pydantic models, REST endpoints, wire into server_process"
    status: completed
  - id: phase-2-cli-flags
    content: "Phase 2: Wire --metrics and --metrics-interval into hirocli setup and hirocli start"
    status: completed
  - id: phase-3-admin-ui
    content: "Phase 3: Live CPU + memory gauges on NiceGUI dashboard with enable/disable toggle and interval slider"
    status: completed
  - id: phase-4-process
    content: "Phase 4: Add process-level metrics (server CPU, RSS, threads) + channel plugin subprocess metrics to collector and UI"
    status: completed
  - id: phase-5-disk-network
    content: "Phase 5: Add disk and network metrics with rate calculations"
    status: completed
  - id: phase-6-app-metrics
    content: "Phase 6: Instrument CommunicationManager, AgentManager, ChannelManager for app-level metrics"
    status: pending
  - id: phase-7-cli-command
    content: "Phase 7: hirocli metrics command with rich terminal dashboard and --live mode"
    status: completed
  - id: phase-8-persistence
    content: "Phase 8: SQLite persistence with downsampling for long-term history"
    status: pending
isProject: false
---

# Progressive System Metrics Monitoring

## Safety and Threat Assessment

**Performance impact:** `psutil` calls are lightweight but `cpu_percent()` blocks for a short interval. All collection runs in `asyncio.to_thread` so it never blocks the event loop. With a minimum interval of 1 second, overhead is negligible (under 0.1% CPU).

**Memory footprint:** A ring buffer of 1800 snapshots (small Pydantic models, ~500 bytes each) costs under 1 MB.

**Threats:** None significant. `psutil` is read-only (no system mutation). The only risk is a very tight polling interval starving the machine -- mitigated by enforcing a floor (1 second minimum) and shipping disabled by default.

**Cross-platform:** `psutil` has a single API for Windows, macOS, and Linux. No platform branching needed for CPU, memory, disk, and network. Only exotic metrics (CPU temperature, GPU) would need platform-specific code, but those are out of scope.

---

## Phase 1 -- Foundation: Collector + Config + REST Endpoint (DONE)

**Outcome:** Metrics collection runs inside the server process, controllable via config and a REST endpoint. Verifiable with `curl /metrics`.

- `psutil>=7.0` added to [pyproject.toml](hiroserver/hirocli/pyproject.toml)
- Config fields in [domain/config.py](hiroserver/hirocli/src/hirocli/domain/config.py): `metrics_enabled`, `metrics_interval`, `metrics_history_size`
- Pydantic models in [services/metrics/models.py](hiroserver/hirocli/src/hirocli/services/metrics/models.py): `MetricsSnapshot`, `CpuMetrics`, `MemoryMetrics`
- `MetricsCollector` async service in [services/metrics/collector.py](hiroserver/hirocli/src/hirocli/services/metrics/collector.py)
- Wired into [server_process.py](hiroserver/hirocli/src/hirocli/runtime/server_process.py) `asyncio.gather`
- REST endpoints in [http_server.py](hiroserver/hirocli/src/hirocli/runtime/http_server.py): `GET /metrics`, `GET /metrics/history`, `GET /metrics/status`, `POST /metrics/configure`

---

## Phase 2 -- CLI Flags: `setup --metrics` and `start --metrics`

**Outcome:** Users can enable metrics through the natural CLI workflow -- during setup (persisted) or at start time (ephemeral, like `--admin`).

User workflows after this phase:

```bash
# Persist during setup (written to config.json)
hirocli setup --gateway-url ws://... --metrics
hirocli setup --gateway-url ws://... --metrics --metrics-interval 3.0

# Ephemeral override at start (not persisted, like --admin)
hirocli start --admin --metrics

# Live toggle while running (already works from Phase 1)
curl -X POST .../metrics/configure -d '{"enabled": true}'
```

### 2a. Add env var constant

Add `ENV_METRICS = "HIRO_METRICS"` to [constants.py](hiroserver/hirocli/src/hirocli/constants.py), following the `ENV_ADMIN_UI` pattern.

### 2b. `SetupTool` changes in [tools/server.py](hiroserver/hirocli/src/hirocli/tools/server.py)

- Add `metrics_enabled` and `metrics_interval` params
- Thread them into the `Config(...)` constructor on line 373 (currently metrics fields default to `False`/`2.0` because they're not explicitly set)
- When `metrics_enabled=True` is passed, set `metrics_enabled=True` in the Config before `save_config`

### 2c. `setup` CLI command in [commands/root.py](hiroserver/hirocli/src/hirocli/commands/root.py)

- Add `--metrics / --no-metrics` (Typer boolean flag pair)
- Add `--metrics-interval` (float option)
- Pass through to `SetupTool().execute(...)`
- Show metrics config in the output summary

### 2d. `StartTool` changes in [tools/server.py](hiroserver/hirocli/src/hirocli/tools/server.py)

- Add `metrics` param (bool)
- When `metrics=True`, set env var `HIRO_METRICS=1` before spawning the subprocess (same pattern as `ENV_ADMIN_UI`)
- In foreground mode, pass it directly to `_main()`

### 2e. `_do_start` and `_spawn_server` in [tools/server.py](hiroserver/hirocli/src/hirocli/tools/server.py)

- Accept `metrics` kwarg
- Set `env[ENV_METRICS] = "1"` when true (same as `env[ENV_ADMIN_UI] = "1"`)

### 2f. `server_process.py` changes

- Read `ENV_METRICS` env var
- When set, override `config.metrics_enabled = True` before creating the collector (so env var wins over config, same as `--admin` overriding config)

### 2g. `start` and `restart` CLI commands in [commands/root.py](hiroserver/hirocli/src/hirocli/commands/root.py)

- Add `--metrics` flag (Typer boolean)
- Pass through to `StartTool` / `RestartTool`
- Show "Metrics: enabled" in the output when active

---

## Phase 3 -- Admin UI: Live Dashboard Gauges

**Outcome:** The NiceGUI dashboard shows real-time CPU and memory gauges with a sparkline history, and a toggle to enable/disable metrics.

### 3a. New UI page or dashboard section

Extend [ui/pages/dashboard.py](hiroserver/hirocli/src/hirocli/ui/pages/dashboard.py) (or create a dedicated `ui/pages/metrics.py` with a sidebar entry) with:

- An enable/disable toggle (calls `collector.configure()` directly -- same process)
- An interval slider (1s--10s range)
- CPU gauge (circular progress or bar) + small sparkline chart (last 2 minutes)
- Memory gauge + sparkline
- Uses `ui.timer(interval, update_fn)` to poll `collector.latest` directly (same process, no HTTP roundtrip needed since NiceGUI shares the event loop)

### 3b. Register in app.py

Add the metrics page to `register_pages()` in [ui/app.py](hiroserver/hirocli/src/hirocli/ui/app.py) and add a sidebar nav entry.

---

## Phase 4 -- Process-Level Metrics (DONE)

**Outcome:** Dashboard shows process-scoped metrics as primary view. Channel plugin subprocess metrics are tracked per-plugin.

- Added `ProcessMetrics` model (`pid`, `cpu_percent`, `rss_bytes`, `vms_bytes`, `num_threads`) to [models.py](hiroserver/hirocli/src/hirocli/services/metrics/models.py)
- Added `ChildProcessMetrics` model (`name`, `pid`, `alive`, `cpu_percent`, `rss_bytes`, `num_threads`) for channel plugins
- `ChannelManager._subprocesses` changed from `list[Popen]` to `dict[str, Popen]` (name → process)
- Added `ChannelManager.get_child_processes()` public method returning `list[tuple[str, Popen]]`
- `MetricsCollector` accepts a `set_child_pid_provider(callback)` injection — avoids circular imports
- Wired in [server_process.py](hiroserver/hirocli/src/hirocli/runtime/server_process.py): `metrics_collector.set_child_pid_provider(channel_manager.get_child_processes)`
- Admin UI redesigned: process metrics primary (3-column grid), channel plugins table with totals row, system-wide collapsed by default

---

## Phase 5 -- Disk + Network Metrics (DONE)

**Outcome:** Full resource visibility in dashboard and CLI: CPU, memory, disk (usage + I/O rates), network (send/recv rates).

- Added `DiskMetrics` (`total_bytes`, `used_bytes`, `free_bytes`, `percent`, `read_bytes_per_sec`, `write_bytes_per_sec`)
- Added `NetworkMetrics` (`bytes_sent_per_sec`, `bytes_recv_per_sec`, `packets_sent_per_sec`, `packets_recv_per_sec`)
- Both added to `MetricsSnapshot`
- Collector tracks `_prev_disk`, `_prev_net`, `_prev_time` — rates computed as `(current - prev) / elapsed`
- Disk root is platform-aware: `C:\\` on Windows, `/` elsewhere
- Admin UI: Disk card (usage % + I/O rate chart) and Network card (throughput + dual-line send/recv chart)

---

## Phase 6 -- Application-Level Metrics

**Outcome:** Track message throughput, agent latency, queue depths -- correlate system load with app behavior.

- Instrument [CommunicationManager](hiroserver/hirocli/src/hirocli/runtime/communication_manager.py), [AgentManager](hiroserver/hirocli/src/hirocli/runtime/agent_manager.py), [ChannelManager](hiroserver/hirocli/src/hirocli/runtime/channel_manager.py) with lightweight counters
- Collector aggregates these into the snapshot alongside system metrics

---

## Phase 7 -- CLI Command (DONE)

**Outcome:** `hirocli metrics` command group exposes status, snapshot, and live modes from the terminal.

- `rich>=13` added to [pyproject.toml](hiroserver/hirocli/pyproject.toml)
- New command module: [commands/metrics.py](hiroserver/hirocli/src/hirocli/commands/metrics.py)
  - `hirocli metrics status` — collector config, enabled state, history size, uptime
  - `hirocli metrics snapshot` — formatted table of the latest `MetricsSnapshot`
  - `hirocli metrics live [--interval N]` — polls `GET /metrics` and refreshes display via `rich.Live`
- Registered in [commands/app.py](hiroserver/hirocli/src/hirocli/commands/app.py) as `metrics_app` Typer group
- CLI talks to the server via `urllib.request` (no new dependencies) using the workspace HTTP base URL

---

## Phase 8 -- History Persistence (Optional)

**Outcome:** Metrics survive restarts; dashboard can show last 24 hours / 7 days.

- Store snapshots in SQLite (already have `aiosqlite` + `sqlmodel`)
- Downsample: 2s granularity for 1h, 1min for 24h, 5min for 7d
- Prune old rows on each write cycle

---

Note: We are abiding by the no-backward-compatibility rule -- no migration needed for the new config fields (they have defaults).