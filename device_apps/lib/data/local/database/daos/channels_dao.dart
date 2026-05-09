import 'package:drift/drift.dart';

import '../app_database.dart';
import '../tables/channels_table.dart';

part 'channels_dao.g.dart';

@DriftAccessor(tables: [Channels])
class ChannelsDao extends DatabaseAccessor<AppDatabase>
    with _$ChannelsDaoMixin {
  ChannelsDao(super.db);

  Stream<List<ChannelRecord>> watchAllChannels() {
    return (select(channels)..orderBy([
          (c) => OrderingTerm(
            expression: c.lastMessageAt,
            mode: OrderingMode.desc,
          ),
        ]))
        .watch();
  }

  Future<ChannelRecord?> getById(String channelId) {
    return (select(
      channels,
    )..where((c) => c.id.equals(channelId))).getSingleOrNull();
  }

  Future<List<ChannelRecord>> listServerBacked() {
    return (select(channels)..where((c) => c.serverId.isNotNull())).get();
  }

  Future<int> count() async {
    final result = await (selectOnly(
      channels,
    )..addColumns([channels.id.count()])).getSingle();
    return result.read(channels.id.count()) ?? 0;
  }

  Future<void> insertOrUpdate(ChannelsCompanion companion) async {
    await into(channels).insertOnConflictUpdate(companion);
  }

  Future<void> updateLastHistorySyncedAt(
    String channelId,
    int syncedAtMs,
  ) async {
    await (update(channels)..where((c) => c.id.equals(channelId))).write(
      ChannelsCompanion(lastHistorySyncedAt: Value(syncedAtMs)),
    );
  }

  /// Persist the compound history cursor — pass the newest ``created_at``
  /// (ms) together with the ``external_id`` of the row at that timestamp
  /// so the next page request can resume past collisions.
  Future<void> updateLastHistorySyncedCursor(
    String channelId, {
    required int syncedAtMs,
    required String? externalId,
  }) async {
    await (update(channels)..where((c) => c.id.equals(channelId))).write(
      ChannelsCompanion(
        lastHistorySyncedAt: Value(syncedAtMs),
        lastHistorySyncedExternalId: Value(externalId),
      ),
    );
  }

  Future<void> deleteMissing(Set<String> channelIds) async {
    if (channelIds.isEmpty) {
      await delete(channels).go();
      return;
    }
    await (delete(channels)..where((c) => c.id.isNotIn(channelIds))).go();
  }

  Future<ChannelRecord?> getFirst() {
    return (select(channels)..limit(1)).getSingleOrNull();
  }

  /// After server bulk-clear: drop history watermark and persist reconciled epoch.
  Future<void> clearHistoryWatermarkAndSetAppliedServerLastDeleted(
    String channelId, {
    required int appliedServerLastDeleted,
  }) async {
    await (update(channels)..where((c) => c.id.equals(channelId))).write(
      ChannelsCompanion(
        lastHistorySyncedAt: const Value(null),
        lastHistorySyncedExternalId: const Value(null),
        appliedServerLastDeleted: Value(appliedServerLastDeleted),
      ),
    );
  }
}
