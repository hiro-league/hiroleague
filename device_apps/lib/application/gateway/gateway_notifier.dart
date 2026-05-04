import 'dart:async';

import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../core/utils/logger.dart';
import '../sync/resource_sync_bootstrap.dart';
import '../sync/resource_sync_registry.dart';
import '../sync/resource_sync_version_store.dart';
import '../../data/remote/gateway/gateway_auth_handler.dart';
import '../../data/remote/gateway/gateway_client.dart';
import '../../data/remote/gateway/gateway_contract.dart';
import '../../data/remote/gateway/gateway_event_bus.dart';
import '../../data/remote/gateway/gateway_inbound_frame.dart';
import '../../data/remote/gateway/gateway_protocol.dart';
import '../../data/remote/gateway/gateway_request_client.dart';
import '../../data/remote/gateway/reconnect_policy.dart';
import '../../domain/models/identity/device_identity.dart';
import '../../domain/services/crypto_service.dart';
import '../auth/auth_notifier.dart';
import '../auth/auth_state.dart';
import 'gateway_state.dart';

part 'gateway_notifier.g.dart';

final _log = Logger.get('GatewayNotifier');

@Riverpod(keepAlive: true)
class GatewayNotifier extends _$GatewayNotifier {
  GatewayClient? _client;
  StreamSubscription<GatewayClientUpdate>? _stateSub;
  StreamSubscription<GatewayInboundFrame>? _frameSub;

  // Stable frame stream — survives reconnects.
  final _frameController = StreamController<GatewayInboundFrame>.broadcast();

  Stream<GatewayInboundFrame> get frameStream => _frameController.stream;

  GatewayRequestClient? _requestClient;
  GatewayRequestClient? get requestClient => _requestClient;

  final GatewayEventBus _eventBus = GatewayEventBus();
  final ResourceSyncRegistry _resourceSync = ResourceSyncRegistry();
  final List<FrozenRetryRequest> _frozenRetryBacklog = [];
  bool _gatewayHandlersWired = false;

  @override
  GatewayState build() {
    ref.onDispose(_dispose);

    // fireImmediately triggers once with the current auth state so the gateway
    // connects immediately if the user is already authenticated on startup.
    ref.listen<AsyncValue<AuthState>>(
      authProvider,
      _onAuthChanged,
      fireImmediately: true,
    );

    return const GatewayState.disconnected();
  }

  void _onAuthChanged(AsyncValue<AuthState>? prev, AsyncValue<AuthState> next) {
    final auth = next.value;
    final prevAuth = prev?.value;

    if (auth is AuthAuthenticated && prevAuth is! AuthAuthenticated) {
      // Dart promotes auth to AuthAuthenticated here — no cast needed.
      final identity = auth.identity;
      // Defer to avoid mutating state during a provider build/listen cycle.
      Future.microtask(() => _connect(identity));
    } else if (prevAuth is AuthAuthenticated && auth is! AuthAuthenticated) {
      Future.microtask(_disconnect);
    }
  }

  void _connect(DeviceIdentity identity) {
    final previousRc = _requestClient;
    if (previousRc != null) {
      _frozenRetryBacklog.addAll(previousRc.takeFrozenIdempotentPending());
      previousRc.cancelAll();
    }
    _requestClient = null;
    _disposeTransport();

    final client = GatewayClient(
      authHandler: GatewayAuthHandler(CryptoService()),
      protocol: const GatewayProtocol(),
      reconnectPolicy: const ReconnectPolicy(),
    );

    _requestClient = GatewayRequestClient(
      sendFn: client.send,
    );

    _stateSub = client.updates.listen(_onClientUpdate);
    _frameSub = client.frames.listen((frame) {
      // Intercept response frames and route to the request client before
      // broadcasting — the broadcast stream may have no subscribers yet.
      if (frame.payload['message_type'] == UnifiedMessageWire.typeResponse) {
        _routeResponse(frame.payload);
      } else if (frame.payload['message_type'] ==
          UnifiedMessageWire.typeEvent) {
        unawaited(_eventBus.dispatch(frame.payload));
      }
      _frameController.add(frame);
    });

    client.start(gatewayUrl: identity.gatewayUrl, identity: identity);
    _client = client;

    _wireGatewayAppHandlersOnce();
    _wireResourceSync();
  }

  /// Registers `resource.changed` with [GatewayEventBus] — sync logic lives in [resource_sync_bootstrap].
  void _wireGatewayAppHandlersOnce() {
    if (_gatewayHandlersWired) return;
    _gatewayHandlersWired = true;
    _eventBus.register(EventWire.resourceChanged, _handleResourceChangedEvent);
  }

  /// Re-bind sync lambdas on every connect so they use the fresh request client.
  void _wireResourceSync() {
    wireResourceSync(
      ref: ref,
      registry: _resourceSync,
      getClient: () => _requestClient,
    );
  }

  Future<void> _handleResourceChangedEvent(Map<String, dynamic> data) async {
    final resource = data['resource'] as String?;
    if (resource == null) return;

    final hintVer = readResourceSyncVersion(data);
    if (hintVer != null) {
      final last = ref
          .read(resourceSyncVersionStoreProvider.notifier)
          .lastSeen(resource);
      // Skip exact duplicate emissions only. Do not use hintVer <= last: after a host
      // restart the new counter can replay lower numbers while lastSeen still holds
      // the pre-restart value until connect-time syncAll finishes.
      if (last != null && hintVer == last) {
        _log.debug(
          'Skipping duplicate resource.changed',
          fields: {'resource': resource, 'sync_version': hintVer},
        );
        return;
      }
    }

    await _resourceSync.sync(resource);
  }

  Future<void> _disconnect() async {
    _teardownClient();
    state = const GatewayState.disconnected();
  }

  void _disposeTransport() {
    _stateSub?.cancel();
    _frameSub?.cancel();
    _stateSub = null;
    _frameSub = null;
    _client?.stop();
    _client?.dispose();
    _client = null;
  }

  /// Logout / disposal — abandon queued idempotent retries.
  void _teardownClient() {
    _requestClient?.cancelAll();
    _requestClient = null;
    _frozenRetryBacklog.clear();
    _disposeTransport();
  }

  /// Complete a pending request/response completer from the raw frame payload.
  void _routeResponse(Map<String, dynamic> payload) {
    final rid = payload['request_id'] as String?;
    if (rid == null || _requestClient == null) return;

    // Find the JSON content item that carries the response body
    final contentRaw = payload['content'];
    if (contentRaw is! List || contentRaw.isEmpty) return;

    for (final item in contentRaw) {
      if (item is Map && item['content_type'] == ContentWire.json) {
        _requestClient!.completeRequest(rid, item['body'] as String);
        return;
      }
    }
  }

  void _onClientUpdate(GatewayClientUpdate update) {
    state = switch (update) {
      GatewayClientConnecting() => const GatewayState.connecting(),
      GatewayClientConnected(:final deviceId) => GatewayState.connected(
        deviceId: deviceId,
      ),
      GatewayClientDisconnected() => const GatewayState.disconnected(),
      GatewayClientError(:final message) => GatewayState.error(message),
    };
    if (update is GatewayClientConnected) {
      // Re-issue reads that were in-flight during socket teardown — after listeners
      // attach so responses route to [GatewayRequestClient].
      if (_frozenRetryBacklog.isNotEmpty && _requestClient != null) {
        final backlog = [..._frozenRetryBacklog];
        _frozenRetryBacklog.clear();
        _requestClient!.replayFrozen(backlog);
      }
      unawaited(_resourceSync.syncAll());
    }
  }

  /// Pull [resources] again when the last successful fetch is older than [maxStale]
  /// (stale-while-revalidate; complements `resource.changed` + connect-time syncAll).
  Future<void> revalidateResourcesIfStale(
    List<String> resources, {
    Duration maxStale = const Duration(seconds: 30),
  }) async {
    if (_requestClient == null) return;
    if (state is! GatewayConnected) return;
    final syncStore = ref.read(resourceSyncVersionStoreProvider.notifier);
    for (final resource in resources) {
      if (syncStore.shouldRevalidate(resource, maxStale)) {
        await _resourceSync.sync(resource);
      }
    }
  }

  /// Sends a message payload to all connected devices (broadcast),
  /// or to a specific [targetDeviceId] (unicast).
  void send(Map<String, dynamic> payload, {String? targetDeviceId}) {
    _client?.send(payload, targetDeviceId: targetDeviceId);
  }

  void _dispose() {
    _teardownClient();
    _frameController.close();
  }
}
