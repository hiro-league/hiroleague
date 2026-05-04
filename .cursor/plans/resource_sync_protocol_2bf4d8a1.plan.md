# Resource Sync Protocol — server↔device communication redesign

> Status: Draft · Owner: TBD · Mode: no-backward-compatibility (per workspace rule)

## Why

Today every new server-driven feature (channels, characters, voices, …) bolts
onto `server.info` events or grows a bespoke event type, and the Flutter
`GatewayNotifier` accumulates one `if (frame is X)` branch per feature. The
result is unprincipled coupling between transport and domain code.

This plan replaces that with a small generic substrate where:

- **Events are best-effort hints** (`resource.changed`).
- **Requests are the source of truth** (`<resource>.list` / `.get`).
- **Reliability** is achieved by *convergence*, not by acks: connect-time full
  sync, per-resource versioning to detect missed events, retry-on-reconnect for
  in-flight requests, and stale-while-revalidate on screen entry.

## Architecture summary

### Wire protocol additions

```
EVENT_TYPE_RESOURCE_CHANGED = "resource.changed"
```

`resource.changed` event payload:

```json
{
  "resource": "channels",
  "ids": ["server-3"],            // optional, selective invalidation
  "version": 47,                  // monotonic per resource
  "scope": { "user_id": 1 },      // forward-compat for multi-user
  "reason": "preferences_saved"   // diagnostic only
}
```

Every `<resource>.list` response carries `version` so clients can:
- ignore stale events whose `version <= last_known_version[resource]`,
- detect a gap (missed event) and refetch when convenient.

### Server components

```
ResourceRegistry
    register("channels", fetcher=ConversationChannelListTool, on=["channel_changes","preferences_saved","character_changes"])
    register("policy",   fetcher=ServerInfoGetTool,            on=["preferences_saved"])

ResourceVersioning   (in-memory map[str,int] with monotonic increment)
ResourceChangeBroadcaster
    - subscribes to all in-process domain emitters once
    - per change → bumps version → enqueues coalesced resource.changed event
    - debounces 100 ms per resource (configurable)
    - targets: all devices for the user-scope (today: all connected)

DeviceTargeting
    - get_device_ids_for_scope(scope) -> list[str]
    - today: returns all approved devices; tomorrow: filter by user_id
```

`request_methods.py` keeps registering each `<resource>.list` via existing
Tools (per `consider-creating-tools-first.mdc`). New tools added: any future
`characters.list`, `voices.list`, etc., authored once and reused by CLI/HTTP.

### Device components

```
GatewayEventBus               // routes inbound events by type
ResourceSyncRegistry          // maps resource -> fetcher
    register('channels', (client) async => fetch + repo.syncFromServer)
    register('policy',   (client) async => fetch + applySnapshot)
ResourceVersionStore          // last-seen version per resource (persistent)
ResourceFreshnessPolicy       // stale-while-revalidate per resource
GatewayRequestClient
    - retry-on-reconnect for in-flight idempotent requests
    - bounded exponential backoff
```

`GatewayNotifier` is reduced to: route response frames, hand events to
`GatewayEventBus`, and trigger `ResourceSyncRegistry.syncAll(...)` on connect.
**No domain knowledge inside it.**

## Reliability model (recap)

| Failure mode | Mitigation |
|---|---|
| Event dropped in flight | `version` gap detected on next event or screen visit → refetch |
| Server emits while device offline | Connect-time `syncAll` |
| Request response lost | Existing 15 s timeout + retry-on-reconnect |
| Device DB out of date after long sleep | Stale-while-revalidate when screen reopens |
| Coalesce burst (e.g. preferences saved touches many resources) | 100 ms debounce per resource server-side |

No durable queues, no client-side ack windows. The cost of the worst case is one extra round trip.

---

## Step-by-step plan

> Each step lists the exact files to create / modify / delete. Steps are
> ordered so the tree compiles and tests pass after each.

### Step 1 — SDK constants and schema

**Modify**
- `hiroserver/hiro-channel-sdk/src/hiro_channel_sdk/constants.py`
  - Add `EVENT_TYPE_RESOURCE_CHANGED = "resource.changed"`.
  - **Remove** `EVENT_TYPE_SERVER_INFO` (no backward compat).
- `protocol/unified-message.schema.json`
  - Add `resource.changed` to the documented event types.

**Modify**
- `device_apps/lib/data/remote/gateway/gateway_contract.dart`
  - In `EventWire`: replace `serverInfo` with `resourceChanged`.

### Step 2 — Server: `ResourceVersionStore`

**Create**
- `hiroserver/hirocli/src/hirocli/runtime/resource_versioning.py`
  - Thread-safe in-memory `dict[str, int]`.
  - `bump(resource: str) -> int` returns new version (monotonic, +1).
  - `get(resource: str) -> int` (default 0).
  - Persist nothing — versions reset on server restart, that's fine because
    devices treat any unknown/lower version as "definitely refetch".

### Step 3 — Server: `ResourceRegistry` and `ResourceChangeBroadcaster`

**Create**
- `hiroserver/hirocli/src/hirocli/runtime/resource_registry.py`
  - `ResourceSpec(name, on_signals: list[str], description: str)`.
  - `ResourceRegistry` with `register(spec)` and `iter()`.
- `hiroserver/hirocli/src/hirocli/runtime/resource_change_broadcaster.py`
  - Replaces `ServerInfoBroadcaster` end-to-end.
  - Subscribes once to: `preferences_saved`, `channel_changes`,
    `character_changes` (and any future signal listed by a registered spec).
  - On signal → for each spec listening to that signal:
    - bump `ResourceVersionStore[resource]`.
    - schedule a coalesced flush per resource (`asyncio` task with 100 ms
      debounce window keyed by resource name).
  - Flush builds one `resource.changed` envelope per resource and emits via
    `EnvelopeFactory.resource_changed_event(...)` to every device returned by
    `DeviceTargeting.get_device_ids_for_scope(scope)`.
  - Tracks `connected_device_ids` (replacing the old broadcaster's set).
  - Hooks: `handle_device_connected/disconnected`, `clear_connected_devices`.

**Create**
- `hiroserver/hirocli/src/hirocli/runtime/device_targeting.py`
  - `DeviceTargeting(workspace_path)`.
  - `get_device_ids_for_scope(scope: dict | None) -> list[str]`.
  - Today: returns all connected device ids regardless of scope.
  - Designed so adding `user_id` filtering is a pure addition.

**Modify**
- `hiroserver/hirocli/src/hirocli/runtime/envelope_factory.py`
  - Replace `server_info_event(...)` with:
    ```python
    @staticmethod
    def resource_changed_event(*, channel, recipient_id, resource,
                               version, ids=None, scope=None, reason=None,
                               metadata=None) -> UnifiedMessage
    ```
  - Drop the `EVENT_TYPE_SERVER_INFO` import.

**Delete**
- `hiroserver/hirocli/src/hirocli/runtime/server_info_broadcaster.py`

### Step 4 — Server: register the two initial resources

**Modify**
- `hiroserver/hirocli/src/hirocli/runtime/server_process.py`
  - Replace `ServerInfoBroadcaster` wiring with:
    - build `ResourceVersionStore`,
    - build `ResourceRegistry` and register `channels`, `policy`,
    - build `ResourceChangeBroadcaster(ctx, registry, versions, targeting,
      emit_outbound)` and `start()` it,
    - update `infra_handlers.set_server_info_broadcaster(...)` →
      `set_resource_broadcaster(...)`.

**Modify**
- `hiroserver/hirocli/src/hirocli/runtime/infra_event_handlers.py`
  - Rename `_server_info_broadcaster` → `_resource_broadcaster`.
  - Same connected/disconnected hooks; just delegate to the new class.

### Step 5 — Server: request methods carry `version`

**Modify**
- `hiroserver/hirocli/src/hirocli/runtime/request_methods.py`
  - `handle_channels_list`: include `"version": versions.get("channels")` in
    the response payload.
  - Replace `handle_server_info_get` with `handle_policy_get` (method name
    `policy.get` — keep `server.info.get` removed per no-backward-compat).
    Returns `{ "policy": ..., "version": versions.get("policy") }`.

**Modify**
- `hiroserver/hirocli/src/hirocli/tools/server_info.py`
  - Rename to `tools/policy.py`; rename `ServerInfoGetTool` → `PolicyGetTool`
    with `name = "policy_get"`.
  - Returns just the policy section (no channels) — channels live on
    `channels.list` only now (matches the agent's earlier change).
- `hiroserver/hirocli/src/hirocli/domain/server_info.py`
  - Split: keep `build_server_info_snapshot` for internal use only OR replace
    with `build_policy_snapshot(workspace_path)`. Channels enrichment stays in
    `build_channel_list_entries` (already exists).

**Modify**
- `hiroserver/hirocli/src/hirocli/tools/__init__.py`
  - Update `all_tools()` to import the renamed `PolicyGetTool`.

### Step 6 — Device: `GatewayEventBus`

**Create**
- `device_apps/lib/data/remote/gateway/gateway_event_bus.dart`
  - `typedef EventHandlerFn = Future<void> Function(Map<String, dynamic> data);`
  - `register(String type, EventHandlerFn fn)`.
  - `dispatch(UnifiedMessage msg)` reads `msg.event.type` and routes.
  - Unknown types → debug-log and drop.

### Step 7 — Device: `ResourceVersionStore`

**Create**
- `device_apps/lib/application/sync/resource_version_store.dart`
  - Persistent `Map<String, int>` backed by `SecureStorageService` key
    `resource_versions.v1`.
  - `int? get(String resource)` / `set(String, int)`.
  - In-memory cache loaded on startup.

### Step 8 — Device: `ResourceSyncRegistry` + freshness policy

**Create**
- `device_apps/lib/application/sync/resource_sync_registry.dart`
  - `register(String resource, Future<int?> Function(GatewayRequestClient client) fetcher)`.
  - `Future<void> sync(String resource, GatewayRequestClient client)` — calls
    fetcher, persists returned version, updates a `lastFetchedAt` timestamp.
  - `Future<void> syncAll(GatewayRequestClient client)`.
  - `Future<void> ensureFresh(String resource, {Duration maxAge})` — refetch
    only if `lastFetchedAt < now - maxAge` (stale-while-revalidate hook).

**Create**
- `device_apps/lib/application/sync/resource_sync_bootstrap.dart`
  - One place per feature where its sync entry is registered, e.g.:
    ```dart
    registry.register('channels', (client) async {
      final resp = await client.request('channels.list');
      final data = resp['data'] as Map<String, dynamic>;
      await ref.read(channelRepositoryProvider).syncFromServer(
        (data['channels'] as List).cast<Map<String, dynamic>>(),
      );
      return data['version'] as int?;
    });
    registry.register('policy', (client) async {
      final resp = await client.request('policy.get');
      final data = resp['data'] as Map<String, dynamic>;
      await ref.read(serverInfoProvider.notifier).applyPolicyJson(
        data['policy'] as Map<String, dynamic>,
      );
      return data['version'] as int?;
    });
    ```

### Step 9 — Device: shrink `GatewayNotifier`

**Modify**
- `device_apps/lib/application/gateway/gateway_notifier.dart`
  - Remove `_isServerInfoEvent`, `_applyServerInfoPayload`, `_refreshChannels`,
    `_refreshServerInfo`.
  - On every inbound frame:
    - if `message_type == response` → `_routeResponse` (unchanged).
    - else if `message_type == event` → `_eventBus.dispatch(msg)`.
  - Register one event handler at construction:
    ```dart
    _eventBus.register('resource.changed', (data) async {
      final res = data['resource'] as String?;
      final ver = data['version'] as int?;
      if (res == null) return;
      if (ver != null && ver <= _versions.get(res) ?? 0) return; // stale
      await _registry.sync(res, _requestClient!);
    });
    ```
  - On `GatewayClientConnected`: `await _registry.syncAll(_requestClient!)`.
  - File ends up ~70–90 lines.

### Step 10 — Device: rename `ServerInfoNotifier` → `PolicyNotifier`

**Modify**
- `device_apps/lib/application/server_info/server_info_notifier.dart` →
  rename file/class to `application/policy/policy_notifier.dart` /
  `PolicyNotifier`. Storage key `policy.snapshot.v1`. Same shape, narrower
  contract (no channels).
- `device_apps/lib/domain/models/server_info/server_info.dart` → split into
  `domain/models/policy/policy.dart` and the existing
  `domain/models/channel/channel.dart` already holds capabilities.

**Update all imports.** No backward compat for the old name.

### Step 11 — Device: request retry-on-reconnect

**Modify**
- `device_apps/lib/data/remote/gateway/gateway_request_client.dart`
  - Add `bool idempotent` flag to `request(...)` (default true for `*.list`,
    `*.get`).
  - Replace `cancelAll()` semantics with `pauseAll()` that re-issues idempotent
    requests when `GatewayNotifier` reports reconnect; non-idempotent ones
    still error with `StateError`.
  - Add bounded exponential backoff (100 ms → 1.6 s) capped at 3 retries
    inside the timeout window.

### Step 12 — Stale-while-revalidate hooks

**Modify**
- `device_apps/lib/features/chat/chat_screen.dart` and
  `device_apps/lib/features/channels/channel_list_screen.dart`
  - On screen entry, call `registry.ensureFresh('channels', maxAge: 30s)`.
  - This is opt-in per screen; document the convention in
    `mintdocs/build/design-decisions/flutter-app.mdx`.

### Step 13 — Tests

**Create**
- `hiroserver/hirocli/src/hirocli/runtime/tests/test_resource_change_broadcaster.py`
  - 100 ms debounce: 5 rapid `channel_changes` → exactly 1 outbound event.
  - Multi-resource: `preferences_saved` triggers `channels` AND `policy`
    bumps and emits two events.
  - `version` is monotonic across emissions.
  - Disconnected device receives nothing; reconnect sets state to fetch on
    connect (separate from broadcast).
- `hiroserver/hirocli/src/hirocli/runtime/tests/test_resource_versioning.py`
- `device_apps/test/application/sync/resource_sync_registry_test.dart`
- `device_apps/test/data/remote/gateway/gateway_event_bus_test.dart`
- `device_apps/test/data/remote/gateway/gateway_request_client_retry_test.dart`

### Step 14 — Docs

**Create / Modify** in `hiro-docs/mintdocs`:
- `architecture/concepts/resource-sync.mdx` (new) — diagrams + the table above.
- `architecture/concepts/communication-manager.mdx` — add a "Resource sync"
  section pointing to the new doc.
- `architecture/concepts/unified-message.mdx` — replace the `server.info`
  example with `resource.changed`.
- `build/design-decisions/flutter-app.mdx` — document
  `ResourceSyncRegistry` and the stale-while-revalidate convention.

Per `Document-Executed-Plans.mdc`, do this in the same PR as the
implementation.

---

## Acceptance criteria

1. There is no `server.info` event on the wire. Search confirms zero hits.
2. `GatewayNotifier` contains zero domain-resource names.
3. Adding a new resource (e.g. `characters`) requires touching exactly:
   - one new tool + one `register("characters.list", ...)` line,
   - one `ResourceRegistry.register(ResourceSpec("characters", on=["character_changes"]))` line,
   - one `registry.register('characters', ...)` line on Flutter,
   - one repository's `syncFromServer`.
4. Burst test: saving preferences 10× in 1 s emits ≤ 2 events per affected
   resource (debounce works).
5. Disconnect + 5 server-side changes + reconnect → device ends up consistent
   via the connect-time `syncAll` (no events were delivered, but state matches).
6. Killing the server mid-flight `channels.list` request → on reconnect the
   request is retried and resolves successfully (idempotent path).

---

## Reflecting build updates (per `reflecting-build-updates.mdc`)

Breaking-change notes for "get me up to speed":

- Wire constant rename: `EVENT_TYPE_SERVER_INFO` → `EVENT_TYPE_RESOURCE_CHANGED`
  in `hiro_channel_sdk`. **Reinstall the SDK** in dev environments
  (`uv sync` in `hiroserver/`).
- Request method rename: `server.info.get` → `policy.get`. Any local scripts /
  curl examples that hit it must be updated.
- Flutter device storage: a new key `resource_versions.v1` is written;
  `server_info.snapshot.v1` is **deleted** by the new `PolicyNotifier` on
  first run. After installing the new build on a paired device, expect one
  full re-sync on first launch.
- `ServerInfoNotifier` import path moved to
  `application/policy/policy_notifier.dart`. Update any in-progress branches.
- No DB migration required (Drift schema unchanged).
- No DB migration required server-side either; resource versions are in
  memory only.

