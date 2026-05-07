import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/utils/logger.dart';
import '../../data/remote/gateway/gateway_request_client.dart';
import 'resource_sync_version_store.dart';

final _log = Logger.get('CharacterPhotoSync');

String characterPhotoFileExtensionForMediaType(String? mediaType) {
  final m = (mediaType ?? 'image/png').toLowerCase();
  if (m.contains('jpeg') || m.contains('jpg')) return 'jpg';
  if (m.contains('webp')) return 'webp';
  if (m.contains('gif')) return 'gif';
  return 'png';
}

/// Shared ``characters.list`` → conditional ``files.get`` flow (platform storage via callbacks).
Future<void> refreshCharacterPhotosWithHooks(
  Ref ref,
  GatewayRequestClient? client, {
  required Future<bool> Function(String characterId, String blobId) needsDownload,
  required Future<void> Function(String characterId) ensureCachedBytesForSkippedRow,
  required Future<void> Function(
    String characterId,
    String blobId,
    Uint8List bytes,
    String? mediaType,
  ) persistDownload,
}) async {
  if (client == null) return;
  try {
    final response = await client.request('characters.list');
    final data = response['data'];
    if (data is! Map) return;
    final payload = Map<String, dynamic>.from(data);
    final syncVer = payload['resource_sync_version'];
    final syncVerInt = syncVer is int
        ? syncVer
        : syncVer is num
            ? syncVer.toInt()
            : null;

    final rawList = payload['characters'];
    if (rawList is! List) return;

    var downloaded = 0;
    for (final raw in rawList) {
      if (raw is! Map) continue;
      final row = Map<String, dynamic>.from(raw);
      final id = row['id'] as String?;
      final blobId = row['photo_blob_id'] as String?;
      final mediaType = row['photo_media_type'] as String?;
      if (id == null || id.isEmpty || blobId == null || blobId.isEmpty) {
        continue;
      }
      if (!await needsDownload(id, blobId)) {
        await ensureCachedBytesForSkippedRow(id);
        continue;
      }
      final bytes = await client.filesGet(blobId);
      await persistDownload(id, blobId, bytes, mediaType);
      downloaded++;
    }

    if (syncVerInt != null) {
      await ref
          .read(resourceSyncVersionStoreProvider.notifier)
          .recordAuthoritative('characters', syncVerInt);
    }
    await ref
        .read(resourceSyncVersionStoreProvider.notifier)
        .markPullSucceeded('characters');

    _log.info(
      'Character photos synced',
      fields: {'downloaded': downloaded},
    );
  } catch (e, st) {
    _log.warning(
      'Failed to refresh character photos',
      fields: {'error': e.toString(), 'stack': st.toString()},
    );
  }
}
