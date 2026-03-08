import 'dart:convert';

import '../../../core/utils/logger.dart';
import 'gateway_inbound_frame.dart';

/// Handles frame serialization and deserialization for the gateway relay protocol.
///
/// Inbound envelope (injected by server):
///   { "sender_device_id": "...", "payload": {...} }
///
/// Outbound envelope (sent by client):
///   { "target_device_id": "...", "payload": {...} }   ← target_device_id is optional
class GatewayProtocol {
  const GatewayProtocol();

  static final _log = Logger.get('GatewayProtocol');

  /// Decodes a raw WebSocket frame into a [GatewayInboundFrame].
  /// Returns null for system/auth messages, malformed frames, or frames without a payload.
  GatewayInboundFrame? decode(dynamic raw) {
    if (raw is! String) return null;
    Map<String, dynamic> map;
    try {
      map = (jsonDecode(raw) as Map).cast<String, dynamic>();
    } catch (e) {
      _log.warning('Malformed frame', fields: {'error': '$e'});
      return null;
    }

    // Skip system messages (auth_challenge, auth_ok, pairing_*, etc.)
    if (map.containsKey('type')) return null;

    final senderDeviceId = map['sender_device_id']?.toString();
    if (senderDeviceId == null || senderDeviceId.isEmpty) return null;

    final payload = (map['payload'] as Map?)?.cast<String, dynamic>();
    if (payload == null || payload.isEmpty) return null;

    return GatewayInboundFrame(
      senderDeviceId: senderDeviceId,
      payload: payload,
    );
  }

  /// Encodes a payload map into a raw WebSocket frame string.
  String encode({
    required Map<String, dynamic> payload,
    String? targetDeviceId,
  }) {
    final envelope = <String, dynamic>{'payload': payload};
    if (targetDeviceId != null && targetDeviceId.isNotEmpty) {
      envelope['target_device_id'] = targetDeviceId;
    }
    return jsonEncode(envelope);
  }
}
