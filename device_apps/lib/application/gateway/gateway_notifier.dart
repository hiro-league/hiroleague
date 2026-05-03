import 'dart:async';

import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../core/utils/logger.dart';
import '../../data/repositories/channel_repository_impl.dart';
import '../../data/remote/gateway/gateway_auth_handler.dart';
import '../../data/remote/gateway/gateway_client.dart';
import '../../data/remote/gateway/gateway_contract.dart';
import '../../data/remote/gateway/gateway_inbound_frame.dart';
import '../../data/remote/gateway/gateway_protocol.dart';
import '../../data/remote/gateway/gateway_request_client.dart';
import '../../data/remote/gateway/reconnect_policy.dart';
import '../../domain/models/server_info/server_info.dart';
import '../../domain/models/identity/device_identity.dart';
import '../../domain/services/crypto_service.dart';
import '../auth/auth_notifier.dart';
import '../auth/auth_state.dart';
import '../server_info/server_info_notifier.dart';
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
    _teardownClient();

    final client = GatewayClient(
      authHandler: GatewayAuthHandler(CryptoService()),
      protocol: const GatewayProtocol(),
      reconnectPolicy: const ReconnectPolicy(),
    );

    _requestClient = GatewayRequestClient(
      sendFn: (payload) => client.send(payload),
    );

    _stateSub = client.updates.listen(_onClientUpdate);
    _frameSub = client.frames.listen((frame) {
      // Intercept response frames and route to the request client before
      // broadcasting — the broadcast stream may have no subscribers yet.
      if (frame.payload['message_type'] == UnifiedMessageWire.typeResponse) {
        _routeResponse(frame.payload);
      }
      if (_isServerInfoEvent(frame.payload)) {
        final data = (frame.payload['event'] as Map?)?['data'];
        if (data is Map) {
          unawaited(_applyServerInfoPayload(Map<String, dynamic>.from(data)));
        }
      }
      _frameController.add(frame);
    });

    client.start(gatewayUrl: identity.gatewayUrl, identity: identity);
    _client = client;
  }

  Future<void> _disconnect() async {
    _teardownClient();
    state = const GatewayState.disconnected();
  }

  void _teardownClient() {
    _stateSub?.cancel();
    _frameSub?.cancel();
    _stateSub = null;
    _frameSub = null;
    _requestClient?.cancelAll();
    _requestClient = null;
    _client?.stop();
    _client?.dispose();
    _client = null;
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
      unawaited(_refreshServerInfo());
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

  bool _isServerInfoEvent(Map<String, dynamic> payload) {
    if (payload['message_type'] != UnifiedMessageWire.typeEvent) return false;
    final event = payload['event'];
    return event is Map && event['type'] == EventWire.serverInfo;
  }

  Future<void> _refreshServerInfo() async {
    final client = _requestClient;
    if (client == null) return;
    try {
      final response = await client.request('server.info.get');
      final data = response['data'];
      if (data is! Map) return;
      await _applyServerInfoPayload(Map<String, dynamic>.from(data));
    } catch (e) {
      _log.warning('Failed to refresh server info', fields: {'error': e.toString()});
    }
  }

  Future<void> _applyServerInfoPayload(Map<String, dynamic> payload) async {
    try {
      final snapshot = ServerInfoSnapshot.fromJson(payload);
      await ref.read(serverInfoProvider.notifier).applySnapshot(snapshot);
      await ref.read(channelRepositoryProvider).syncFromServer(
        snapshot.channels
            .map(
              (channel) => <String, dynamic>{
                'id': channel.id,
                'name': channel.name,
              },
            )
            .toList(),
      );
      _log.info(
        'Applied server info snapshot',
        fields: {'channels': snapshot.channels.length},
      );
    } catch (e) {
      _log.warning('Failed to apply server info snapshot', fields: {'error': e.toString()});
    }
  }
}
