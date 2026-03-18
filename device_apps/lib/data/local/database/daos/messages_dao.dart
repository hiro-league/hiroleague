import 'package:drift/drift.dart';

import '../app_database.dart';
import '../tables/messages_table.dart';

part 'messages_dao.g.dart';

@DriftAccessor(tables: [Messages])
class MessagesDao extends DatabaseAccessor<AppDatabase>
    with _$MessagesDaoMixin {
  MessagesDao(super.db);

  Stream<List<MessageRecord>> watchChannelMessages(String channelId) {
    return (select(messages)
          ..where((m) => m.channelId.equals(channelId))
          ..orderBy([
            (m) => OrderingTerm(
                  expression: m.timestampMs,
                  mode: OrderingMode.asc,
                ),
          ]))
        .watch();
  }

  Future<void> insertMessage(MessagesCompanion companion) async {
    await into(messages).insertOnConflictUpdate(companion);
  }

  Future<void> updateStatus(String messageId, String status) async {
    await (update(messages)..where((m) => m.id.equals(messageId)))
        .write(MessagesCompanion(status: Value(status)));
  }

  Future<void> updateMetadata(String messageId, String metadata) async {
    await (update(messages)..where((m) => m.id.equals(messageId)))
        .write(MessagesCompanion(metadata: Value(metadata)));
  }

  Future<MessageRecord?> getById(String messageId) async {
    return (select(messages)..where((m) => m.id.equals(messageId)))
        .getSingleOrNull();
  }
}
