import 'dart:async';
import 'dart:convert';

import 'gateway_contract.dart';
import 'unified_message.dart';

/// Request interrupted by a socket teardown — same completer is resumed after reconnect.
final class FrozenRetryRequest {
  FrozenRetryRequest({
    required this.method,
    required this.params,
    required this.timeout,
    required this.completer,
  });

  final String method;
  final Map<String, dynamic> params;
  final Duration timeout;
  final Completer<Map<String, dynamic>> completer;
}

class _PendingEntry {
  _PendingEntry({
    required this.requestId,
    required this.method,
    required this.params,
    required this.completer,
    required this.timeout,
    required this.idempotent,
  });

  final String requestId;
  final String method;
  final Map<String, dynamic> params;
  final Completer<Map<String, dynamic>> completer;
  final Duration timeout;
  final bool idempotent;
  Timer? timeoutTimer;
}

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

  final Map<String, _PendingEntry> _pending = {};

  static const _defaultTimeout = Duration(seconds: 15);

  /// Read-only queries safe to replay after a transient disconnect.
  static bool defaultIdempotentFor(String method) =>
      method == 'channels.list' || method == 'policy.get';

  int _counter = 0;

  String _nextRequestId() =>
      'req_${++_counter}_${DateTime.now().millisecondsSinceEpoch}';

  UnifiedMessage _buildMessage(
    String requestId,
    String method,
    Map<String, dynamic> params,
  ) {
    return UnifiedMessage(
      messageType: UnifiedMessageWire.typeRequest,
      requestId: requestId,
      routing: MessageRouting(
        id: requestId,
        channel: 'devices',
        direction: UnifiedMessageWire.directionInbound,
        senderId: 'flutter',
      ),
      content: [
        ContentItem(
          contentType: ContentWire.json,
          body: jsonEncode({'method': method, 'params': params}),
        ),
      ],
    );
  }

  void _armTimeout(_PendingEntry entry) {
    entry.timeoutTimer?.cancel();
    entry.timeoutTimer = Timer(entry.timeout, () {
      final removed = _pending.remove(entry.requestId);
      if (removed != null && !entry.completer.isCompleted) {
        entry.completer.completeError(
          TimeoutException(
            'Request ${entry.method} timed out',
            entry.timeout,
          ),
        );
      }
    });
  }

  void _dispatch(String requestId, String method, Map<String, dynamic> params) {
    _sendFn(_buildMessage(requestId, method, params).toJson());
  }

  /// Sends a JSON-RPC-style request and returns the parsed response data.
  ///
  /// Throws [TimeoutException] if the server doesn't reply within [timeout].
  Future<Map<String, dynamic>> request(
    String method, {
    Map<String, dynamic> params = const {},
    Duration timeout = _defaultTimeout,
    bool? idempotent,
  }) {
    final effIdempotent = idempotent ?? defaultIdempotentFor(method);
    final requestId = _nextRequestId();
    final completer = Completer<Map<String, dynamic>>();
    final entry = _PendingEntry(
      requestId: requestId,
      method: method,
      params: params,
      completer: completer,
      timeout: timeout,
      idempotent: effIdempotent,
    );
    _pending[requestId] = entry;
    _armTimeout(entry);
    _dispatch(requestId, method, params);
    return completer.future;
  }

  /// Complete a pending request by request ID and raw JSON body string.
  ///
  /// Called by [GatewayNotifier] from the frame listener — this runs before
  /// the broadcast stream may have subscribers yet.
  bool completeRequest(String requestId, String jsonBody) {
    final entry = _pending.remove(requestId);
    if (entry == null) return false;
    entry.timeoutTimer?.cancel();

    try {
      final body = jsonDecode(jsonBody) as Map<String, dynamic>;
      if (!entry.completer.isCompleted) {
        entry.completer.complete(body);
      }
      return true;
    } catch (e) {
      if (!entry.completer.isCompleted) {
        entry.completer.completeError(FormatException('Invalid response JSON: $e'));
      }
      return true;
    }
  }

  /// Called when a response frame arrives from the gateway.
  bool handleResponse(UnifiedMessage msg) {
    final rid = msg.requestId;
    if (rid == null || !_pending.containsKey(rid)) return false;

    for (final item in msg.content) {
      if (item.contentType == ContentWire.json) {
        return completeRequest(rid, item.body);
      }
    }

    final entry = _pending.remove(rid);
    entry?.timeoutTimer?.cancel();
    if (entry != null && !entry.completer.isCompleted) {
      entry.completer.completeError(
        const FormatException('Response has no JSON content'),
      );
    }
    return true;
  }

  /// Freeze in-flight idempotent reads for replay; fail everything else.
  List<FrozenRetryRequest> takeFrozenIdempotentPending() {
    final out = <FrozenRetryRequest>[];
    for (final entry in _pending.values) {
      entry.timeoutTimer?.cancel();
      if (entry.idempotent) {
        out.add(
          FrozenRetryRequest(
            method: entry.method,
            params: entry.params,
            timeout: entry.timeout,
            completer: entry.completer,
          ),
        );
      } else if (!entry.completer.isCompleted) {
        entry.completer.completeError(
          StateError(
            'Gateway disconnected — request ${entry.method} cancelled',
          ),
        );
      }
    }
    _pending.clear();
    return out;
  }

  /// Re-send [items] from [takeFrozenIdempotentPending] on a live socket.
  void replayFrozen(List<FrozenRetryRequest> items) {
    for (final item in items) {
      if (item.completer.isCompleted) continue;
      final requestId = _nextRequestId();
      final entry = _PendingEntry(
        requestId: requestId,
        method: item.method,
        params: item.params,
        completer: item.completer,
        timeout: item.timeout,
        idempotent: true,
      );
      _pending[requestId] = entry;
      _armTimeout(entry);
      _dispatch(requestId, item.method, item.params);
    }
  }

  /// Cancel every pending and frozen request (logout / disposal).
  void cancelAll() {
    for (final entry in _pending.values) {
      entry.timeoutTimer?.cancel();
      if (!entry.completer.isCompleted) {
        entry.completer.completeError(
          StateError(
            'Gateway disconnected — request ${entry.method} cancelled',
          ),
        );
      }
    }
    _pending.clear();
  }
}
