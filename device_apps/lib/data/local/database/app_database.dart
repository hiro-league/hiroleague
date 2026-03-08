import 'package:drift/drift.dart';
import 'package:drift_flutter/drift_flutter.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import 'daos/channels_dao.dart';
import 'daos/messages_dao.dart';
import 'tables/channels_table.dart';
import 'tables/messages_table.dart';

part 'app_database.g.dart';

@DriftDatabase(
  tables: [Channels, Messages],
  daos: [ChannelsDao, MessagesDao],
)
class AppDatabase extends _$AppDatabase {
  AppDatabase() : super(_openExecutor());


  @override
  int get schemaVersion => 1;
}

/// Picks the correct QueryExecutor for the current platform.
/// On web, DriftWebOptions are required by drift_flutter; sqlite3.wasm and
/// drift_worker.dart.js must be served from the same origin as the app.
QueryExecutor _openExecutor() {
  if (kIsWeb) {
    return driftDatabase(
      name: 'device_apps',
      web: DriftWebOptions(
        sqlite3Wasm: Uri.parse('sqlite3.wasm'),
        driftWorker: Uri.parse('drift_worker.dart.js'),
      ),
    );
  }
  return driftDatabase(name: 'device_apps');
}

@Riverpod(keepAlive: true)
AppDatabase appDatabase(Ref ref) {
  final db = AppDatabase();
  ref.onDispose(db.close);
  return db;
}
