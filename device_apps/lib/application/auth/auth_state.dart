import 'package:freezed_annotation/freezed_annotation.dart';

import '../../domain/models/identity/device_identity.dart';

part 'auth_state.freezed.dart';

@freezed
class AuthState with _$AuthState {
  /// Device has never paired, or identity was cleared.
  const factory AuthState.unauthenticated() = AuthUnauthenticated;

  /// Pairing handshake is in progress.
  const factory AuthState.pairing() = AuthPairing;

  /// Device has a valid attestation and is ready to connect.
  const factory AuthState.authenticated(DeviceIdentity identity) = AuthAuthenticated;

  /// A pairing attempt failed.
  const factory AuthState.error(String message) = AuthError;
}
