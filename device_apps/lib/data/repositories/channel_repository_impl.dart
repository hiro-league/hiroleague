import 'dart:convert';

import 'package:drift/drift.dart' show Value;
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../domain/models/channel/channel.dart';
import '../../domain/models/server_info/server_info.dart';
import '../../domain/repositories/channel_repository.dart';
import '../local/database/app_database.dart';
import '../local/database/daos/channels_dao.dart';

part 'channel_repository_impl.g.dart';

class ChannelRepositoryImpl implements ChannelRepository {
  ChannelRepositoryImpl(this._dao);

  final ChannelsDao _dao;

  @override
  Stream<List<Channel>> watchChannels() {
    return _dao.watchAllChannels().map(
      (rows) => rows.map(_rowToChannel).toList(),
    );
  }

  @override
  Future<void> insertChannel(Channel channel) async {
    await _dao.insertOrUpdate(
      ChannelsCompanion.insert(
        id: channel.id,
        name: channel.name,
        lastMessageAt: Value(channel.lastMessageAt?.millisecondsSinceEpoch),
        serverId: Value(channel.serverId),
        characterId: Value(channel.characterId),
        characterName: Value(channel.characterName),
        capabilitiesJson: Value(
          channel.capabilities != null
              ? jsonEncode(channel.capabilities!.toJson())
              : null,
        ),
      ),
    );
  }

  @override
  Future<void> syncFromServer(List<Map<String, dynamic>> serverChannels) async {
    final localIds = <String>{};
    for (final sc in serverChannels) {
      final serverId = _asInt(sc['id']);
      final name = sc['name'] as String? ?? 'Channel $serverId';
      final character = sc['character'] is Map
          ? Map<String, dynamic>.from(sc['character'] as Map)
          : const <String, dynamic>{};
      final capabilities = sc['capabilities'] is Map
          ? Map<String, dynamic>.from(sc['capabilities'] as Map)
          : null;
      // Use server id as part of the local id for stable identity
      final localId = 'server-$serverId';
      localIds.add(localId);
      await _dao.insertOrUpdate(
        ChannelsCompanion.insert(
          id: localId,
          name: name,
          lastMessageAt: Value(_parseServerTimestamp(sc['last_message_at'])),
          serverId: Value(serverId),
          characterId: Value(
            character['id'] as String? ?? sc['character_id']?.toString(),
          ),
          characterName: Value(character['name'] as String?),
          capabilitiesJson: Value(
            capabilities != null ? jsonEncode(capabilities) : null,
          ),
        ),
      );
    }
    await _dao.deleteMissing(localIds);
  }

  Channel _rowToChannel(ChannelRecord row) {
    return Channel(
      id: row.id,
      name: row.name,
      lastMessageAt: row.lastMessageAt != null
          ? DateTime.fromMillisecondsSinceEpoch(row.lastMessageAt!, isUtc: true)
          : null,
      serverId: row.serverId,
      characterId: row.characterId,
      characterName: row.characterName,
      capabilities: _parseCapabilities(row.capabilitiesJson),
    );
  }

  static int _asInt(Object? value) {
    if (value is int) return value;
    if (value is num) return value.toInt();
    if (value is String) return int.parse(value);
    throw FormatException(
      'Channel id must be an int, got ${value.runtimeType}',
    );
  }

  static int? _parseServerTimestamp(Object? value) {
    if (value == null) return null;
    final parsed = DateTime.tryParse(value.toString());
    return parsed?.toUtc().millisecondsSinceEpoch;
  }

  static MediaCapabilities? _parseCapabilities(String? raw) {
    if (raw == null || raw.isEmpty) return null;
    try {
      return MediaCapabilities.fromJson(
        Map<String, dynamic>.from(jsonDecode(raw) as Map),
      );
    } catch (_) {
      return null;
    }
  }
}

@Riverpod(keepAlive: true)
ChannelRepository channelRepository(Ref ref) {
  final db = ref.watch(appDatabaseProvider);
  return ChannelRepositoryImpl(db.channelsDao);
}
