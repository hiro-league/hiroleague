import 'dart:async';
import 'dart:convert';

import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../domain/models/server_info/server_info.dart';
import '../../platform/storage/secure_storage_service.dart';

part 'server_info_notifier.g.dart';

const _serverInfoStorageKey = 'server_info.snapshot.v1';
const _voiceReplyPrefsStorageKey = 'server_info.voice_reply_prefs.v1';

@Riverpod(keepAlive: true)
class ServerInfoNotifier extends _$ServerInfoNotifier {
  @override
  ServerInfoSnapshot? build() {
    unawaited(_load());
    return null;
  }

  Future<void> _load() async {
    final storage = ref.read(secureStorageServiceProvider);
    final raw = await storage.read(_serverInfoStorageKey);
    if (raw == null || raw.isEmpty) return;
    try {
      final decoded = jsonDecode(raw) as Map<String, dynamic>;
      state = ServerInfoSnapshot.fromJson(decoded);
    } catch (_) {
      state = null;
    }
  }

  Future<void> applySnapshot(ServerInfoSnapshot snapshot) async {
    state = snapshot;
    await ref
        .read(secureStorageServiceProvider)
        .write(_serverInfoStorageKey, jsonEncode(snapshot.toJson()));
  }

  Future<void> applyJson(Map<String, dynamic> json) async {
    await applySnapshot(ServerInfoSnapshot.fromJson(json));
  }

  Future<void> clear() async {
    state = null;
    await ref.read(secureStorageServiceProvider).delete(_serverInfoStorageKey);
  }
}

@riverpod
MediaCapabilities? channelCapabilities(Ref ref, String channelId) {
  return ref.watch(serverInfoProvider)?.channelForLocalId(channelId)?.capabilities;
}

@riverpod
String? channelCharacterName(Ref ref, String channelId) {
  return ref.watch(serverInfoProvider)?.channelForLocalId(channelId)?.character.name;
}

@Riverpod(keepAlive: true)
class VoiceReplyPreferenceNotifier extends _$VoiceReplyPreferenceNotifier {
  @override
  Map<String, bool> build() {
    unawaited(_load());
    return const {};
  }

  Future<void> _load() async {
    final storage = ref.read(secureStorageServiceProvider);
    final raw = await storage.read(_voiceReplyPrefsStorageKey);
    if (raw == null || raw.isEmpty) return;
    try {
      final decoded = jsonDecode(raw) as Map<String, dynamic>;
      state = decoded.map(
        (key, value) => MapEntry(key, value == true),
      );
    } catch (_) {
      state = const {};
    }
  }

  Future<void> setVoiceReplyEnabled(String channelId, bool enabled) async {
    state = {
      ...state,
      channelId: enabled,
    };
    await ref.read(secureStorageServiceProvider).write(
      _voiceReplyPrefsStorageKey,
      jsonEncode(state),
    );
  }

  Future<void> clear() async {
    state = const {};
    await ref.read(secureStorageServiceProvider).delete(_voiceReplyPrefsStorageKey);
  }
}

@riverpod
bool channelVoiceReplyEnabled(Ref ref, String channelId) {
  return ref.watch(voiceReplyPreferenceProvider)[channelId] ?? false;
}
