import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';

import '../../data/remote/gateway/gateway_request_client.dart';
import 'character_photo_notifier.dart';
import 'character_photo_sync_logic.dart';

/// Desktop/mobile: persist under app documents + keep [characterPhotoMapProvider] filled.
Future<void> refreshCharacterPhotos(
  Ref ref,
  GatewayRequestClient? client,
) async {
  final docs = await getApplicationDocumentsDirectory();
  final photoDir = Directory('${docs.path}/character_photos');
  if (!photoDir.existsSync()) {
    await photoDir.create(recursive: true);
  }
  final dirPath = photoDir.path;

  await refreshCharacterPhotosWithHooks(
    ref,
    client,
    needsDownload: (id, blobId) async {
      final metaPath = '$dirPath/$id.photo_meta';
      final metaFile = File(metaPath);
      if (!metaFile.existsSync()) return true;
      return metaFile.readAsStringSync().trim() != blobId;
    },
    ensureCachedBytesForSkippedRow: (id) async {
      final reg = ref.read(characterPhotoMapProvider);
      if (reg.containsKey(id)) return;

      for (final ext in ['png', 'jpg', 'jpeg', 'webp', 'gif']) {
        final f = File('$dirPath/$id.$ext');
        if (f.existsSync()) {
          final b = await f.readAsBytes();
          ref.read(characterPhotoMapProvider.notifier).put(id, b);
          return;
        }
      }
    },
    persistDownload: (id, blobId, bytes, mediaType) async {
      final ext = characterPhotoFileExtensionForMediaType(mediaType);
      final imageFile = File('$dirPath/$id.$ext');
      await imageFile.writeAsBytes(bytes, flush: true);
      await File('$dirPath/$id.photo_meta').writeAsString(blobId);
      ref.read(characterPhotoMapProvider.notifier).put(id, bytes);
    },
  );
}
