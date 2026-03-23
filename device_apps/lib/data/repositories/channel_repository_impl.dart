import 'package:drift/drift.dart' show Value;
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../domain/models/channel/channel.dart';
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
        lastMessageAt: Value(
          channel.lastMessageAt?.millisecondsSinceEpoch,
        ),
        serverId: Value(channel.serverId),
      ),
    );
  }

  @override
  Future<void> syncFromServer(List<Map<String, dynamic>> serverChannels) async {
    for (final sc in serverChannels) {
      final serverId = sc['id'] as int;
      final name = sc['name'] as String? ?? 'Channel $serverId';
      // Use server id as part of the local id for stable identity
      final localId = 'server-$serverId';
      await _dao.insertOrUpdate(
        ChannelsCompanion.insert(
          id: localId,
          name: name,
          serverId: Value(serverId),
        ),
      );
    }
  }

  Channel _rowToChannel(ChannelRecord row) {
    return Channel(
      id: row.id,
      name: row.name,
      lastMessageAt: row.lastMessageAt != null
          ? DateTime.fromMillisecondsSinceEpoch(row.lastMessageAt!, isUtc: true)
          : null,
      serverId: row.serverId,
    );
  }
}

@Riverpod(keepAlive: true)
ChannelRepository channelRepository(Ref ref) {
  final db = ref.watch(appDatabaseProvider);
  return ChannelRepositoryImpl(db.channelsDao);
}
