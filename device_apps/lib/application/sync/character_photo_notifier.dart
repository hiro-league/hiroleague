import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';

/// In-memory character id → photo bytes for UI ([MemoryImage] / avatars).
///
/// Sharded by platform in [character_photo_sync_io] / [character_photo_sync_web];
/// sync writes here after every successful download so list/chat can render.
class CharacterPhotoMap extends Notifier<Map<String, Uint8List>> {
  @override
  Map<String, Uint8List> build() => const {};

  void put(String characterId, Uint8List bytes) {
    state = Map<String, Uint8List>.from(state)..[characterId] = bytes;
  }
}

final characterPhotoMapProvider =
    NotifierProvider<CharacterPhotoMap, Map<String, Uint8List>>(
  CharacterPhotoMap.new,
);
