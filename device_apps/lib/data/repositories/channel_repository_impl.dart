import 'package:drift/drift.dart' show Value;
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../core/constants/app_constants.dart';
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
      ),
    );
  }

  @override
  Future<void> ensureDefaultChannel() async {
    final total = await _dao.count();
    if (total == 0) {
      await _dao.insertOrUpdate(
        ChannelsCompanion.insert(
          id: AppConstants.defaultChannelId,
          name: AppConstants.defaultChannelName,
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
    );
  }
}

@Riverpod(keepAlive: true)
ChannelRepository channelRepository(Ref ref) {
  final db = ref.watch(appDatabaseProvider);
  return ChannelRepositoryImpl(db.channelsDao);
}
