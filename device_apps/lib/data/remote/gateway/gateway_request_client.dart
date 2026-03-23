import 'dart:async';
import 'dart:convert';

import 'unified_message.dart';

/// Sends request-type [UnifiedMessage]s and correlates responses by request_id.
///
/// Usage:
///   final client = GatewayRequestClient(sendFn: gateway.send);
///   final result = await client.request('channels.list');
///   // result is {"status": "ok", "data": {...}}
class GatewayRequestClient {
  GatewayRequestClient({required void Function(Map<String, dynamic>) sendFn})
      : _sendFn = sendFn;

  final void Function(Map<String, dynamic>) _sendFn;
  final _pending = <String, Completer<Map<String, dynamic>>>{};

  static const _defaultTimeout = Duration(seconds: 15);

  int _counter = 0;

  /// Sends a JSON-RPC-style request and returns the parsed response data.
  ///
  /// Throws [TimeoutException] if the server doesn't reply within [timeout].
  Future<Map<String, dynamic>> request(
    String method, {
    Map<String, dynamic> params = const {},
    Duration timeout = _defaultTimeout,
  }) {
    final requestId = 'req_${++_counter}_${DateTime.now().millisecondsSinceEpoch}';
    final completer = Completer<Map<String, dynamic>>();
    _pending[requestId] = completer;

    final msg = UnifiedMessage(
      messageType: 'request',
      requestId: requestId,
      routing: MessageRouting(
        id: requestId,
        channel: 'devices',
        direction: 'inbound',
        senderId: 'flutter',
      ),
      content: [
        ContentItem(
          contentType: 'json',
          body: jsonEncode({'method': method, 'params': params}),
        ),
      ],
    );

    _sendFn(msg.toJson());

    return completer.future.timeout(timeout, onTimeout: () {
      _pending.remove(requestId);
      throw TimeoutException('Request $method timed out', timeout);
    });
  }

  /// Complete a pending request by request ID and raw JSON body string.
  ///
  /// Called by [GatewayNotifier] from the frame listener — this runs before
  /// the frame reaches any broadcast-stream subscribers, so the completer
  /// resolves even if [MessageRepositoryImpl] isn't constructed yet.
  bool completeRequest(String requestId, String jsonBody) {
    final completer = _pending.remove(requestId);
    if (completer == null) return false;

    try {
      final body = jsonDecode(jsonBody) as Map<String, dynamic>;
      completer.complete(body);
      return true;
    } catch (e) {
      completer.completeError(FormatException('Invalid response JSON: $e'));
      return true;
    }
  }

  /// Called when a response frame arrives from the gateway.
  /// Returns true if the frame was consumed (matched a pending request).
  bool handleResponse(UnifiedMessage msg) {
    final rid = msg.requestId;
    if (rid == null) return false;

    // Already completed by completeRequest from the frame listener
    if (!_pending.containsKey(rid)) return false;

    for (final item in msg.content) {
      if (item.contentType == 'json') {
        return completeRequest(rid, item.body);
      }
    }

    final completer = _pending.remove(rid);
    completer?.completeError(const FormatException('Response has no JSON content'));
    return true;
  }

  /// Cancel all pending requests (e.g. on disconnect).
  void cancelAll() {
    for (final entry in _pending.entries) {
      entry.value.completeError(
        StateError('Gateway disconnected — request ${entry.key} cancelled'),
      );
    }
    _pending.clear();
  }
}
