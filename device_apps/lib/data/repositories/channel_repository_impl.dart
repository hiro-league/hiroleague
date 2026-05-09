import 'dart:convert';

import 'package:drift/drift.dart' show Value;
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../core/utils/logger.dart';
import '../../domain/models/channel/channel.dart';
import '../../domain/models/server_info/server_info.dart';
import '../../domain/repositories/channel_repository.dart';
import '../local/database/app_database.dart';
import '../local/database/daos/channels_dao.dart';
import '../../platform/storage/audio_storage_service.dart';

part 'channel_repository_impl.g.dart';

final _log = Logger.get('ChannelRepository');

class ChannelRepositoryImpl implements ChannelRepository {
  ChannelRepositoryImpl(
    this._db,
    this._audio,
  );

  final AppDatabase _db;
  final AudioStorageService _audio;

  ChannelsDao get _channelsDao => _db.channelsDao;

  @override
  Stream<List<Channel>> watchChannels() {
    return _channelsDao.watchAllChannels().map(
      (rows) => rows.map(_rowToChannel).toList(),
    );
  }

  @override
  Future<void> insertChannel(
    Channel channel, {
    int? appliedServerLastDeleted,
  }) async {
    final sid = channel.serverId;
    final epoch = appliedServerLastDeleted;
    if (sid != null && epoch == null) {
      throw ArgumentError(
        'insertChannel: server-backed channels must pass appliedServerLastDeleted '
        '(channels.list last_deleted for this channel).',
      );
    }
    final applied = epoch ?? 0;
    await _channelsDao.insertOrUpdate(
      ChannelsCompanion.insert(
        id: channel.id,
        name: channel.name,
        lastMessageAt: Value(channel.lastMessageAt?.millisecondsSinceEpoch),
        serverId: Value(channel.serverId),
        characterId: Value(channel.characterId),
        characterName: Value(channel.characterName),
        description: Value(channel.description),
        thumbnailMtimeNs: Value(channel.thumbnailMtimeNs),
        capabilitiesJson: Value(
          channel.capabilities != null
              ? jsonEncode(channel.capabilities!.toJson())
              : null,
        ),
        appliedServerLastDeleted: Value(applied),
      ),
    );
  }

  @override
  Future<bool> syncFromServer(List<Map<String, dynamic>> serverChannels) async {
    var didResetAnyMirror = false;
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

      final localId = 'server-$serverId';
      localIds.add(localId);
      final thumbnailMtime = _asThumbnailMtimeNs(sc['thumbnail_mtime_ns']);
      final serverLastDeleted = _asServerLastDeleted(sc['last_deleted']);

      final existing = await _channelsDao.getById(localId);
      var appliedEpoch = existing?.appliedServerLastDeleted ?? 0;

      if (serverLastDeleted > appliedEpoch) {
        // Channel messages bulk-cleared on server — mirror design in `docs/channel-messages-clear-design.md` §4.
        await _resetLocalMirrorForBulkClear(
          channelLocalId: localId,
          newAppliedEpoch: serverLastDeleted,
        );
        appliedEpoch = serverLastDeleted;
        didResetAnyMirror = true;
      }

      await _channelsDao.insertOrUpdate(
        ChannelsCompanion.insert(
          id: localId,
          name: name,
          lastMessageAt: Value(_parseServerTimestamp(sc['last_message_at'])),
          serverId: Value(serverId),
          characterId: Value(
            character['id'] as String? ?? sc['character_id']?.toString(),
          ),
          characterName: Value(character['name'] as String?),
          description: Value(sc['description'] as String?),
          thumbnailMtimeNs: Value(thumbnailMtime),
          capabilitiesJson: Value(
            capabilities != null ? jsonEncode(capabilities) : null,
          ),
          appliedServerLastDeleted: Value(appliedEpoch),
        ),
      );
    }
    await _channelsDao.deleteMissing(localIds);
    return didResetAnyMirror;
  }

  Future<void> _resetLocalMirrorForBulkClear({
    required String channelLocalId,
    required int newAppliedEpoch,
  }) async {
    _log.info(
      '⬇️ Channel mirror reset — bulk-clear epoch ($channelLocalId)',
      fields: {'new_applied_epoch': newAppliedEpoch},
    );

    // Each attachment row owns its own bytes (no cross-row blob sharing —
    // see `docs/channel-messages-clear-design.md`), so we unlink each row's
    // ``localPath`` unconditionally.
    final rows = await _db.messageAttachmentsDao.listAttachmentRowsForChannel(
      channelLocalId,
    );
    for (final a in rows) {
      final p = a.localPath;
      if (p == null || p.isEmpty) continue;
      try {
        await _audio.delete(p);
      } catch (e) {
        _log.warning(
          'Failed to delete local attachment file',
          fields: {
            'message_id': a.messageId,
            'slot_index': a.slotIndex,
            'error': e.toString(),
          },
        );
      }
    }

    await _db.messagesDao.deleteForChannel(channelLocalId);
    await _channelsDao.clearHistoryWatermarkAndSetAppliedServerLastDeleted(
      channelLocalId,
      appliedServerLastDeleted: newAppliedEpoch,
    );
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
      description: row.description,
      thumbnailMtimeNs: row.thumbnailMtimeNs,
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

  static int _asServerLastDeleted(Object? value) {
    if (value == null) return 0;
    if (value is int) return value;
    if (value is num) return value.toInt();
    return int.tryParse(value.toString()) ?? 0;
  }

  static int? _parseServerTimestamp(Object? value) {
    if (value == null) return null;
    final parsed = DateTime.tryParse(value.toString());
    return parsed?.toUtc().millisecondsSinceEpoch;
  }

  static int? _asThumbnailMtimeNs(Object? value) {
    if (value == null) return null;
    if (value is int) return value;
    if (value is num) return value.toInt();
    return int.tryParse(value.toString());
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
  final audio = ref.watch(audioStorageProvider);
  return ChannelRepositoryImpl(db, audio);
}
