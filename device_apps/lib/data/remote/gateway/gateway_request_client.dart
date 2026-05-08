import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

import 'gateway_contract.dart';
import 'unified_message.dart';

/// Idempotent request interrupted by socket teardown — replayed with a new [requestId].
final class FrozenRetryRequest {
  FrozenRetryRequest({
    required this.method,
    required this.params,
    required this.timeout,
    required this.completer,
    this.isFileGet = false,
  });

  final String method;
  final Map<String, dynamic> params;
  final Duration timeout;
  final Completer<dynamic> completer;
  final bool isFileGet;
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

class _FileGetSession {
  _FileGetSession({
    required this.requestId,
    required this.blobId,
    required this.completer,
    required this.timeout,
  });

  final String requestId;
  final String blobId;
  final Completer<Uint8List> completer;
  final Duration timeout;
  Timer? timeoutTimer;
  bool ackSeen = false;
  final BytesBuilder buffer = BytesBuilder();
}

/// Sends request-type [UnifiedMessage]s and correlates responses by request_id.
class GatewayRequestClient {
  GatewayRequestClient({required void Function(Map<String, dynamic>) sendFn})
    : _sendFn = sendFn;

  final void Function(Map<String, dynamic>) _sendFn;

  final Map<String, _PendingEntry> _pending = {};
  final Map<String, _FileGetSession> _fileGetSessions = {};

  static const _defaultTimeout = Duration(seconds: 15);
  static const _fileGetTimeout = Duration(seconds: 120);

  /// Read-only queries safe to replay after a transient disconnect.
  static bool defaultIdempotentFor(String method) =>
      method == 'channels.list' ||
      method == 'characters.list' ||
      method == 'messages.history' ||
      method == 'policy.get' ||
      method == 'files.head' ||
      method == 'files.get';

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
          TimeoutException('Request ${entry.method} timed out', entry.timeout),
        );
      }
    });
  }

  void _armFileGetTimeout(_FileGetSession s) {
    s.timeoutTimer?.cancel();
    s.timeoutTimer = Timer(s.timeout, () {
      final removed = _fileGetSessions.remove(s.requestId);
      if (removed != null && !s.completer.isCompleted) {
        s.completer.completeError(
          TimeoutException('files.get timed out', s.timeout),
        );
      }
    });
  }

  void _dispatch(String requestId, String method, Map<String, dynamic> params) {
    _sendFn(_buildMessage(requestId, method, params).toJson());
  }

  /// JSON-RPC-style request → parsed `{"status": "ok", "data": {...}}` body.
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

  /// ``files.get`` stream download: ack JSON → N ``stream`` frames → terminal JSON.
  Future<Uint8List> filesGet(
    String blobId, {
    Duration timeout = _fileGetTimeout,
  }) {
    final requestId = _nextRequestId();
    final c = Completer<Uint8List>();
    final sess = _FileGetSession(
      requestId: requestId,
      blobId: blobId,
      completer: c,
      timeout: timeout,
    );
    _fileGetSessions[requestId] = sess;
    _armFileGetTimeout(sess);
    _dispatch(requestId, 'files.get', {'blob_id': blobId});
    return c.future;
  }

  /// Terminal or ack JSON for an active ``files.get`` session.
  bool handleFileGetJsonResponse(String requestId, String jsonBody) {
    final sess = _fileGetSessions[requestId];
    if (sess == null) return false;
    final Map<String, dynamic> body;
    try {
      body = jsonDecode(jsonBody) as Map<String, dynamic>;
    } catch (_) {
      _failFileGet(sess, FormatException('Invalid files.get response JSON'));
      return true;
    }
    final status = body['status'];
    if (status == 'error') {
      final err = body['error'];
      _fileGetSessions.remove(requestId);
      sess.timeoutTimer?.cancel();
      if (!sess.completer.isCompleted) {
        sess.completer.completeError(Exception('$err'));
      }
      return true;
    }
    if (status != 'ok') {
      _failFileGet(sess, StateError('Unexpected files.get status: $status'));
      return true;
    }
    final data = body['data'];
    if (data is! Map) {
      _failFileGet(sess, const FormatException('files.get missing data'));
      return true;
    }
    final map = Map<String, dynamic>.from(data);
    if (!sess.ackSeen) {
      sess.ackSeen = true;
      return true;
    }
    // Terminal
    final terminalBlob = map['blob_id'] as String?;
    final size = map['size'];
    if (terminalBlob == null || size is! int) {
      _failFileGet(
        sess,
        const FormatException('files.get terminal missing fields'),
      );
      return true;
    }
    final got = sess.buffer.toBytes();
    if (got.length != size) {
      _failFileGet(
        sess,
        StateError('files.get size mismatch: expected $size got ${got.length}'),
      );
      return true;
    }
    // Spec §5.2: receiver verifies sha of assembled bytes equals the sha
    // portion of blob_id before accepting the file.
    final expectedSha = _shaFromBlobId(sess.blobId);
    if (expectedSha != null) {
      final actualSha = sha256.convert(got).toString();
      if (actualSha != expectedSha) {
        _failFileGet(
          sess,
          StateError(
            'files.get sha mismatch: expected $expectedSha got $actualSha',
          ),
        );
        return true;
      }
    }
    _fileGetSessions.remove(requestId);
    sess.timeoutTimer?.cancel();
    if (!sess.completer.isCompleted) {
      sess.completer.complete(Uint8List.fromList(got));
    }
    return true;
  }

  static String? _shaFromBlobId(String blobId) {
    const prefix = 'sha256:';
    if (!blobId.startsWith(prefix)) return null;
    final hex = blobId.substring(prefix.length).trim().toLowerCase();
    return hex.length == 64 ? hex : null;
  }

  void _failFileGet(_FileGetSession sess, Object error) {
    _fileGetSessions.remove(sess.requestId);
    sess.timeoutTimer?.cancel();
    if (!sess.completer.isCompleted) {
      sess.completer.completeError(error);
    }
  }

  /// One base64 chunk for the active ``files.get`` session.
  void ingestStreamFrame(UnifiedMessage msg) {
    final rid = msg.requestId;
    if (rid == null) return;
    final sess = _fileGetSessions[rid];
    if (sess == null) return;
    if (msg.content.isEmpty) return;
    final item = msg.content.first;
    if (item.contentType != ContentWire.file) return;
    try {
      sess.buffer.add(base64Decode(item.body));
    } catch (e) {
      _failFileGet(sess, FormatException('Invalid stream chunk base64: $e'));
    }
  }

  /// Complete a normal (non-stream) pending request.
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
        entry.completer.completeError(
          FormatException('Invalid response JSON: $e'),
        );
      }
      return true;
    }
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

    for (final sess in _fileGetSessions.values) {
      sess.timeoutTimer?.cancel();
      out.add(
        FrozenRetryRequest(
          method: 'files.get',
          params: {'blob_id': sess.blobId},
          timeout: sess.timeout,
          completer: sess.completer,
          isFileGet: true,
        ),
      );
    }
    _fileGetSessions.clear();
    return out;
  }

  void replayFrozen(List<FrozenRetryRequest> items) {
    for (final item in items) {
      if (item.completer.isCompleted) continue;
      final requestId = _nextRequestId();
      if (item.isFileGet) {
        final blob = item.params['blob_id'];
        if (blob is! String) continue;
        final sess = _FileGetSession(
          requestId: requestId,
          blobId: blob,
          completer: item.completer as Completer<Uint8List>,
          timeout: item.timeout,
        );
        _fileGetSessions[requestId] = sess;
        _armFileGetTimeout(sess);
        _dispatch(requestId, 'files.get', {'blob_id': blob});
      } else {
        final entry = _PendingEntry(
          requestId: requestId,
          method: item.method,
          params: item.params,
          completer: item.completer as Completer<Map<String, dynamic>>,
          timeout: item.timeout,
          idempotent: true,
        );
        _pending[requestId] = entry;
        _armTimeout(entry);
        _dispatch(requestId, item.method, item.params);
      }
    }
  }

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
    for (final sess in _fileGetSessions.values) {
      sess.timeoutTimer?.cancel();
      if (!sess.completer.isCompleted) {
        sess.completer.completeError(
          StateError('Gateway disconnected — files.get cancelled'),
        );
      }
    }
    _fileGetSessions.clear();
  }
}
