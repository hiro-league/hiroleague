import 'package:drift/drift.dart';

@DataClassName('ChannelRecord')
class Channels extends Table {
  TextColumn get id => text()();
  TextColumn get name => text()();
  IntColumn get lastMessageAt => integer().nullable()();
  IntColumn get serverId => integer().nullable()();
  TextColumn get characterId => text().nullable()();
  TextColumn get characterName => text().nullable()();
  TextColumn get description => text().nullable()();
  IntColumn get lastHistorySyncedAt => integer().nullable()();
  // Compound-cursor tiebreaker for ``messages.history`` pagination: when two
  // messages share the same ``created_at``, the server orders by external_id
  // — without this we'd lose rows at page boundaries.
  TextColumn get lastHistorySyncedExternalId => text().nullable()();
  /// Highest ``channels.list`` ``last_deleted`` we have reconciled (full local wipe applied).
  /// Server bump without client wipe would leave stale messages — see Phase 2 channel bulk clear design.
  IntColumn get appliedServerLastDeleted =>
      integer().withDefault(const Constant(0))();
  IntColumn get thumbnailMtimeNs => integer().nullable()();
  TextColumn get capabilitiesJson => text().nullable()();

  @override
  Set<Column> get primaryKey => {id};
}
