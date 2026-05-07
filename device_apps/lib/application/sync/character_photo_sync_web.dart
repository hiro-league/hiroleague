import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/remote/gateway/gateway_request_client.dart';
import 'character_photo_notifier.dart';
import 'character_photo_sync_logic.dart';

/// Web: no ``dart:io``; keep blob etag + bytes in memory only (tab lifetime).
final Map<String, String> _photoBlobMeta = {};
final Map<String, Uint8List> _photoBytes = {};

Future<void> refreshCharacterPhotos(
  Ref ref,
  GatewayRequestClient? client,
) async {
  await refreshCharacterPhotosWithHooks(
    ref,
    client,
    needsDownload: (id, blobId) async =>
        _photoBlobMeta[id]?.trim() != blobId,
    ensureCachedBytesForSkippedRow: (id) async {
      final b = _photoBytes[id];
      if (b != null) {
        ref.read(characterPhotoMapProvider.notifier).put(id, b);
      }
    },
    persistDownload: (id, blobId, bytes, mediaType) async {
      _photoBlobMeta[id] = blobId;
      _photoBytes[id] = bytes;
      ref.read(characterPhotoMapProvider.notifier).put(id, bytes);
    },
  );
}
