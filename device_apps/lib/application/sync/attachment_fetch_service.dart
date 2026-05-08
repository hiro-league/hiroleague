import 'dart:async';
import 'dart:typed_data';

import '../../core/utils/blob_id.dart';
import '../../core/utils/logger.dart';
import '../../data/local/database/app_database.dart';
import '../../data/local/database/daos/message_attachments_dao.dart';

final _log = Logger.get('AttachmentFetch');

typedef AttachmentBytesFetcher = Future<Uint8List> Function(String blobId);
typedef AttachmentBytesSaver =
    Future<String> Function({
      required String messageId,
      required Uint8List bytes,
      required String mimeType,
    });

/// Sentinel error subclasses so the failure-reason mapping doesn't depend on
/// scraping the textual error message — substring matching like
/// ``error.toString().contains('sha')`` would also match unrelated phrases
/// such as "shadowed connection".
sealed class _AttachmentFetchError implements Exception {
  const _AttachmentFetchError(this.message);
  final String message;
  String get reason;
  @override
  String toString() => '$runtimeType: $message';
}

class _ShaMismatchError extends _AttachmentFetchError {
  const _ShaMismatchError(super.message);
  @override
  String get reason => 'sha_mismatch';
}

class _GatewayDisconnectError extends _AttachmentFetchError {
  const _GatewayDisconnectError(super.message);
  @override
  String get reason => 'gateway_disconnect';
}

final class AttachmentFetchService {
  AttachmentFetchService({
    required MessageAttachmentsDao attachmentsDao,
    required AttachmentBytesFetcher fetchBytes,
    required AttachmentBytesSaver saveBytes,
    this.failedRetryDelay = const Duration(seconds: 30),
    this.fetchingTimeout = const Duration(minutes: 2),
    this.maxConcurrentFetches = 2,
    int Function()? nowMs,
  }) : _attachmentsDao = attachmentsDao,
       _fetchBytes = fetchBytes,
       _saveBytes = saveBytes,
       _nowMs = nowMs ?? (() => DateTime.now().millisecondsSinceEpoch);

  final MessageAttachmentsDao _attachmentsDao;
  final AttachmentBytesFetcher _fetchBytes;
  final AttachmentBytesSaver _saveBytes;
  final Duration failedRetryDelay;
  final Duration fetchingTimeout;
  final int maxConcurrentFetches;
  final int Function() _nowMs;

  Future<int> tick() async {
    final pending = await _attachmentsDao.getFetchCandidates(
      nowMs: _nowMs(),
      failedRetryDelay: failedRetryDelay,
      fetchingTimeout: fetchingTimeout,
    );
    // Group by blobId so cross-message duplicates only trigger one fetch and
    // we know up front how many rows will share each result — avoids the
    // race-prone ``listByBlobId`` call we used to make after marking rows
    // ``fetching``.
    final unique = <String, MessageAttachmentRecord>{};
    final dedupCount = <String, int>{};
    for (final row in pending) {
      unique.putIfAbsent(row.blobId, () => row);
      dedupCount[row.blobId] = (dedupCount[row.blobId] ?? 0) + 1;
    }

    var ready = 0;
    final rows = unique.values.toList();
    final concurrency = maxConcurrentFetches < 1 ? 1 : maxConcurrentFetches;
    for (var i = 0; i < rows.length; i += concurrency) {
      final end = i + concurrency > rows.length ? rows.length : i + concurrency;
      final results = await Future.wait(
        rows.sublist(i, end).map(
              (row) => _fetchOne(row, dedupCount[row.blobId] ?? 1),
            ),
      );
      ready += results.where((fetched) => fetched).length;
    }
    return ready;
  }

  Future<bool> _fetchOne(MessageAttachmentRecord row, int dedupCount) async {
    final started = _nowMs();
    final attemptedAtMs = started;
    final blobId = row.blobId;
    try {
      _log.info(
        '⬇️ Attachment fetch — queued · audio',
        fields: {
          'size': row.size,
          'chunk_count': row.chunkCount,
          'dedup_count': dedupCount,
          'blob_id': blobId,
        },
      );
      await _attachmentsDao.markFetching(blobId, attemptedAtMs);
      Uint8List bytes;
      try {
        bytes = await _fetchBytes(blobId);
      } on TimeoutException {
        rethrow;
      } on StateError catch (e) {
        // GatewayRequestClient surfaces socket teardown as StateError("…cancelled").
        final lower = e.message.toLowerCase();
        if (lower.contains('disconnect') || lower.contains('cancelled')) {
          throw _GatewayDisconnectError(e.message);
        }
        rethrow;
      }
      if (!blobIdMatchesBytes(bytes, blobId)) {
        throw _ShaMismatchError('sha mismatch for $blobId');
      }
      final localPath = await _saveBytes(
        messageId: storageIdForBlob(blobId),
        bytes: bytes,
        mimeType: row.mediaType,
      );
      await _attachmentsDao.markReady(blobId, localPath);
      _log.info(
        '✅ Attachment fetch — ready · audio',
        fields: {
          'elapsed_ms': _nowMs() - started,
          'local_path_kind': localPath.startsWith('data:')
              ? 'data_url'
              : 'file',
          'blob_id': blobId,
        },
      );
      return true;
    } catch (e) {
      await _attachmentsDao.markFailed(blobId, _nowMs());
      _log.warning(
        '❌ Attachment fetch — failed · audio',
        fields: {
          'reason': _failureReason(e),
          'attempt': 1,
          'error': e.toString(),
          'blob_id': blobId,
        },
      );
      return false;
    }
  }

  static String _failureReason(Object error) {
    if (error is _AttachmentFetchError) return error.reason;
    if (error is TimeoutException) return 'timeout';
    return 'resolver_error';
  }
}
