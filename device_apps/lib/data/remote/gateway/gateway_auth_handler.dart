import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';

import '../../../core/constants/app_constants.dart';
import '../../../core/errors/app_exception.dart';
import '../../../core/utils/logger.dart';
import '../../../domain/models/identity/device_identity.dart';
import '../../../domain/services/crypto_service.dart';

/// Result of a successful auth handshake.
class GatewayAuthResult {
  const GatewayAuthResult({required this.deviceId});
  final String deviceId;
}

/// Handles the gateway authentication challenge/response handshake.
///
/// Protocol (see relay.py):
///   Server → Client: auth_challenge with hex nonce
///   Client → Server: auth_response with device attestation and nonce signature
///   Server → Client: auth_ok with device_id
class GatewayAuthHandler {
  GatewayAuthHandler(this._cryptoService);

  final CryptoService _cryptoService;
  final _log = Logger.get('GatewayAuthHandler');

  /// Runs the full auth handshake on the given WebSocket [stream] and [sink].
  /// Returns [GatewayAuthResult] on success.
  /// Throws [AuthException] if auth is rejected.
  /// Throws [GatewayException] on timeout or connection error.
  Future<GatewayAuthResult> authenticate({
    required Stream<dynamic> stream,
    required WebSocketSink sink,
    required DeviceIdentity identity,
  }) async {
    if (identity.attestation == null) {
      throw const AuthException('Cannot authenticate: device has no attestation. Pair first.');
    }

    // 1 — Receive auth_challenge
    final nonce = await _awaitChallenge(stream);
    _log.debug('Received auth challenge');

    // 2 — Sign nonce and send auth_response
    final nonceSignature = await _cryptoService.signNonce(identity.seedBase64, nonce);
    // device_name is included outside the signed attestation blob — it is cosmetic
    // metadata for gateway logs and has no effect on access control decisions.
    sink.add(
      jsonEncode(<String, dynamic>{
        'type': 'auth_response',
        'auth_mode': 'device',
        'attestation': identity.attestation!.toJson(),
        'nonce_signature': nonceSignature,
        if (identity.deviceName != null) 'device_name': identity.deviceName,
      }),
    );
    _log.debug('Sent auth_response');

    // 3 — Wait for auth_ok
    final result = await _awaitAuthOk(stream);
    _log.info('Auth successful', fields: {'deviceId': result.deviceId});
    return result;
  }

  Future<String> _awaitChallenge(Stream<dynamic> stream) async {
    Map<String, dynamic>? msg;
    try {
      msg = await stream
          .map(_toMap)
          .firstWhere((m) => m != null && m['type']?.toString() == 'auth_challenge')
          .timeout(
            AppConstants.authTimeout,
            onTimeout: () =>
                throw const GatewayException('Timed out waiting for auth challenge'),
          );
    } on StateError {
      throw const GatewayException('Gateway closed before auth challenge');
    }

    final nonce = msg?['nonce']?.toString() ?? '';
    if (nonce.isEmpty) throw const GatewayException('Auth challenge missing nonce');
    return nonce;
  }

  Future<GatewayAuthResult> _awaitAuthOk(Stream<dynamic> stream) async {
    Map<String, dynamic>? msg;
    try {
      msg = await stream
          .map(_toMap)
          .firstWhere(
            (m) =>
                m != null &&
                (m['type']?.toString() == 'auth_ok' ||
                    m['type']?.toString() == 'auth_failed'),
          )
          .timeout(
            AppConstants.authTimeout,
            onTimeout: () =>
                throw const GatewayException('Timed out waiting for auth_ok'),
          );
    } on StateError {
      throw const GatewayException('Gateway closed before auth_ok');
    }

    if (msg?['type']?.toString() == 'auth_failed') {
      final reason = msg?['reason']?.toString() ?? 'Auth rejected';
      throw AuthException(reason);
    }

    final deviceId = msg?['device_id']?.toString() ?? '';
    if (deviceId.isEmpty) {
      throw const GatewayException('auth_ok missing device_id');
    }
    return GatewayAuthResult(deviceId: deviceId);
  }

  Map<String, dynamic>? _toMap(dynamic raw) {
    if (raw is! String) return null;
    try {
      return (jsonDecode(raw) as Map).cast<String, dynamic>();
    } catch (_) {
      return null;
    }
  }
}
