import 'dart:async';

import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../data/remote/gateway/gateway_auth_handler.dart';
import '../../data/remote/gateway/gateway_client.dart';
import '../../data/remote/gateway/gateway_inbound_frame.dart';
import '../../data/remote/gateway/gateway_protocol.dart';
import '../../data/remote/gateway/reconnect_policy.dart';
import '../../domain/models/identity/device_identity.dart';
import '../../domain/services/crypto_service.dart';
import '../auth/auth_notifier.dart';
import '../auth/auth_state.dart';
import 'gateway_state.dart';

part 'gateway_notifier.g.dart';

@Riverpod(keepAlive: true)
class GatewayNotifier extends _$GatewayNotifier {
  GatewayClient? _client;
  StreamSubscription<GatewayClientUpdate>? _stateSub;
  StreamSubscription<GatewayInboundFrame>? _frameSub;

  // Stable frame stream — survives reconnects.
  final _frameController = StreamController<GatewayInboundFrame>.broadcast();

  Stream<GatewayInboundFrame> get frameStream => _frameController.stream;

  @override
  GatewayState build() {
    ref.onDispose(_dispose);

    // fireImmediately triggers once with the current auth state so the gateway
    // connects immediately if the user is already authenticated on startup.
    ref.listen<AsyncValue<AuthState>>(
      authNotifierProvider,
      _onAuthChanged,
      fireImmediately: true,
    );

    return const GatewayState.disconnected();
  }

  void _onAuthChanged(
    AsyncValue<AuthState>? prev,
    AsyncValue<AuthState> next,
  ) {
    final auth = next.valueOrNull;
    final prevAuth = prev?.valueOrNull;

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

    _stateSub = client.updates.listen(_onClientUpdate);
    _frameSub = client.frames.listen(_frameController.add);

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
    _client?.stop();
    _client?.dispose();
    _client = null;
  }

  void _onClientUpdate(GatewayClientUpdate update) {
    state = switch (update) {
      GatewayClientConnecting() => const GatewayState.connecting(),
      GatewayClientConnected(:final deviceId) => GatewayState.connected(deviceId: deviceId),
      GatewayClientDisconnected() => const GatewayState.disconnected(),
      GatewayClientError(:final message) => GatewayState.error(message),
    };
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
