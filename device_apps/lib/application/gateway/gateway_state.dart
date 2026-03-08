import 'package:freezed_annotation/freezed_annotation.dart';

part 'gateway_state.freezed.dart';

@freezed
class GatewayState with _$GatewayState {
  /// Not connected; no connection attempt in progress.
  const factory GatewayState.disconnected() = GatewayDisconnected;

  /// WebSocket is being established or auth handshake is in progress.
  const factory GatewayState.connecting() = GatewayConnecting;

  /// Authenticated and ready to send/receive messages.
  const factory GatewayState.connected({required String deviceId}) = GatewayConnected;

  /// A permanent error (e.g. auth rejected). Manual intervention required.
  const factory GatewayState.error(String message) = GatewayError;
}
