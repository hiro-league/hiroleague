import 'package:drift/drift.dart';

import 'messages_table.dart';

@TableIndex(name: 'idx_message_attachments_blob_id', columns: {#blobId})
@TableIndex(
  name: 'idx_message_attachments_fetch_status',
  columns: {#fetchStatus},
)
@DataClassName('MessageAttachmentRecord')
class MessageAttachments extends Table {
  TextColumn get messageId =>
      text().references(Messages, #id, onDelete: KeyAction.cascade)();
  IntColumn get slotIndex => integer()();
  TextColumn get contentType => text()();
  TextColumn get blobId => text()();
  TextColumn get mediaType => text()();
  IntColumn get size => integer()();
  IntColumn get durationMs => integer().nullable()();
  IntColumn get chunkSize => integer()();
  IntColumn get chunkCount => integer()();
  TextColumn get remoteRef => text()();
  TextColumn get localPath => text().nullable()();
  TextColumn get fetchStatus => text()();
  IntColumn get lastFetchAttemptMs => integer().nullable()();
  TextColumn get metadata => text().nullable()();
  IntColumn get createdAtMs => integer()();

  @override
  Set<Column> get primaryKey => {messageId, slotIndex};
}
