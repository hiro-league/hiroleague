/// Helpers for the ``sha256:<hex>`` blob id format and the
/// ``message_attachment:<message_external_id>:<slot_index>`` ref format.
///
/// Single source of truth for both shapes on the device, so
/// ``MessageRepositoryImpl``, ``AttachmentFetchService``, ``MessageHistorySync``
/// and any future consumer compute them the same way and never drift apart.
library;

import 'dart:typed_data';

import 'package:crypto/crypto.dart';

const String sha256BlobPrefix = 'sha256:';

/// Default raw chunk size — must match server ``DEFAULT_CHUNK_SIZE``
/// in ``hirocli/domain/blob_store.py``.
const int defaultBlobChunkSize = 49152;

/// Compute the canonical ``sha256:<hex>`` id for an in-memory byte buffer.
String blobIdForBytes(Uint8List bytes) =>
    '$sha256BlobPrefix${sha256.convert(bytes)}';

/// Number of chunks needed for ``size`` bytes at ``chunkSize`` (>= 0; 0 → 0).
int blobChunkCountForSize(int size, [int chunkSize = defaultBlobChunkSize]) =>
    size <= 0 ? 0 : ((size + chunkSize - 1) ~/ chunkSize);

/// Filesystem-safe identifier for a single attachment row. Each row owns its
/// own bytes (no cross-row blob sharing — see
/// `docs/channel-messages-clear-design.md`), so the cache filename is keyed
/// by ``<messageId>_<slotIndex>``. Non-alphanumeric chars in [messageId]
/// (e.g. UUID dashes) are kept; the platform storage layer handles them.
String attachmentStorageId(String messageId, int slotIndex) {
  final safe = messageId.replaceAll(RegExp(r'[^A-Za-z0-9_.-]'), '_');
  return '${safe}_$slotIndex';
}

/// Verify that ``bytes`` hash to ``blobId``. Returns false for non-sha256
/// ids or malformed (non-64-hex) digests.
bool blobIdMatchesBytes(Uint8List bytes, String blobId) {
  if (!blobId.startsWith(sha256BlobPrefix)) return false;
  final expected = blobId.substring(sha256BlobPrefix.length).toLowerCase();
  if (expected.length != 64) return false;
  return sha256.convert(bytes).toString() == expected;
}

/// Build a ``message_attachment:<messageId>:<slotIndex>`` logical ref.
String messageAttachmentRef(String messageId, int slotIndex) =>
    'message_attachment:$messageId:$slotIndex';

/// Parse the trailing slot index from a ``message_attachment:`` ref. Returns
/// null when the ref doesn't end with a colon-prefixed integer.
int? slotIndexFromAttachmentRef(String ref) {
  final idx = ref.lastIndexOf(':');
  if (idx < 0 || idx == ref.length - 1) return null;
  return int.tryParse(ref.substring(idx + 1));
}
