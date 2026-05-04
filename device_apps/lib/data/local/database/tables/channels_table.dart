import 'package:drift/drift.dart';

@DataClassName('ChannelRecord')
class Channels extends Table {
  TextColumn get id => text()();
  TextColumn get name => text()();
  IntColumn get lastMessageAt => integer().nullable()();
  IntColumn get serverId => integer().nullable()();
  TextColumn get characterId => text().nullable()();
  TextColumn get characterName => text().nullable()();
  TextColumn get capabilitiesJson => text().nullable()();

  @override
  Set<Column> get primaryKey => {id};
}
