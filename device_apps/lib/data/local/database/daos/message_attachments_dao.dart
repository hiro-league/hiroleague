import 'package:drift/drift.dart';

import '../app_database.dart';
import '../tables/message_attachments_table.dart';
import '../tables/messages_table.dart';

part 'message_attachments_dao.g.dart';

@DriftAccessor(tables: [MessageAttachments, Messages])
class MessageAttachmentsDao extends DatabaseAccessor<AppDatabase>
    with _$MessageAttachmentsDaoMixin {
  MessageAttachmentsDao(super.db);

  Stream<List<MessageAttachmentRecord>> watchForMessage(String messageId) {
    return (select(messageAttachments)
          ..where((a) => a.messageId.equals(messageId))
          ..orderBy([
            (a) =>
                OrderingTerm(expression: a.slotIndex, mode: OrderingMode.asc),
          ]))
        .watch();
  }

  Stream<List<MessageAttachmentRecord>> watchForChannel(String channelId) {
    final query =
        select(messageAttachments).join([
            innerJoin(
              messages,
              messages.id.equalsExp(messageAttachments.messageId),
            ),
          ])
          ..where(messages.channelId.equals(channelId))
          ..orderBy([
            OrderingTerm.asc(messageAttachments.messageId),
            OrderingTerm.asc(messageAttachments.slotIndex),
          ]);
    return query.watch().map(
      (rows) => rows.map((row) => row.readTable(messageAttachments)).toList(),
    );
  }

  Future<void> insertOrIgnore(MessageAttachmentsCompanion companion) async {
    await into(
      messageAttachments,
    ).insert(companion, mode: InsertMode.insertOrIgnore);
  }

  Future<void> insertOrUpdate(MessageAttachmentsCompanion companion) async {
    await into(messageAttachments).insertOnConflictUpdate(companion);
  }

  Future<List<MessageAttachmentRecord>> getMissingBlobIds() {
    return (select(messageAttachments)
          ..where((a) => a.fetchStatus.equals('pending'))
          ..orderBy([
            (a) =>
                OrderingTerm(expression: a.createdAtMs, mode: OrderingMode.asc),
          ]))
        .get();
  }

  Future<List<MessageAttachmentRecord>> getFetchCandidates({
    required int nowMs,
    Duration failedRetryDelay = const Duration(seconds: 30),
    Duration fetchingTimeout = const Duration(minutes: 2),
  }) async {
    final failedReadyBefore = nowMs - failedRetryDelay.inMilliseconds;
    final fetchingStaleBefore = nowMs - fetchingTimeout.inMilliseconds;
    final rows =
        await (select(messageAttachments)
              ..where(
                (a) => a.fetchStatus.isIn(['pending', 'failed', 'fetching']),
              )
              ..orderBy([
                (a) => OrderingTerm(
                  expression: a.createdAtMs,
                  mode: OrderingMode.asc,
                ),
              ]))
            .get();
    return rows.where((row) {
      final attemptedAt = row.lastFetchAttemptMs;
      return switch (row.fetchStatus) {
        'pending' => true,
        'failed' => attemptedAt == null || attemptedAt <= failedReadyBefore,
        'fetching' => attemptedAt == null || attemptedAt <= fetchingStaleBefore,
        _ => false,
      };
    }).toList();
  }

  Future<MessageAttachmentRecord?> findByBlobId(String blobId) {
    return (select(messageAttachments)
          ..where((a) => a.blobId.equals(blobId))
          ..limit(1))
        .getSingleOrNull();
  }

  Future<MessageAttachmentRecord?> findReadyByBlobId(String blobId) {
    return (select(messageAttachments)
          ..where(
            (a) => a.blobId.equals(blobId) & a.fetchStatus.equals('ready'),
          )
          ..limit(1))
        .getSingleOrNull();
  }

  Future<List<MessageAttachmentRecord>> listByBlobId(String blobId) {
    return (select(
      messageAttachments,
    )..where((a) => a.blobId.equals(blobId))).get();
  }

  Future<void> markFetching(String blobId, int attemptedAtMs) async {
    await (update(
      messageAttachments,
    )..where((a) => a.blobId.equals(blobId))).write(
      MessageAttachmentsCompanion(
        fetchStatus: const Value('fetching'),
        lastFetchAttemptMs: Value(attemptedAtMs),
      ),
    );
  }

  Future<void> markReady(String blobId, String localPath) async {
    await (update(
      messageAttachments,
    )..where((a) => a.blobId.equals(blobId))).write(
      MessageAttachmentsCompanion(
        fetchStatus: const Value('ready'),
        localPath: Value(localPath),
      ),
    );
  }

  Future<void> markFailed(String blobId, int attemptedAtMs) async {
    await (update(
      messageAttachments,
    )..where((a) => a.blobId.equals(blobId))).write(
      MessageAttachmentsCompanion(
        fetchStatus: const Value('failed'),
        lastFetchAttemptMs: Value(attemptedAtMs),
      ),
    );
  }

  /// Attachment rows tied to messages in [channelLocalId].
  Future<List<MessageAttachmentRecord>> listAttachmentRowsForChannel(
    String channelLocalId,
  ) async {
    final rows =
        await (select(
              messageAttachments,
            ).join([
              innerJoin(
                messages,
                messages.id.equalsExp(messageAttachments.messageId),
              ),
            ])..where(
              messages.channelId.equals(channelLocalId),
            ))
            .get();
    return rows
        .map((row) => row.readTable(messageAttachments))
        .toList(growable: false);
  }

  /// Rows with [blobId] attached to messages in any channel except [excludeChannelId].
  Future<int> countBlobReferencesOutsideChannel(
    String blobId,
    String excludeChannelLocalId,
  ) async {
    final countExp = messageAttachments.blobId.count();
    final joined =
        selectOnly(messageAttachments, distinct: false)
          ..addColumns([countExp])
          ..join([
            innerJoin(
              messages,
              messages.id.equalsExp(messageAttachments.messageId),
            ),
          ])
          ..where(
            messageAttachments.blobId.equals(blobId) &
                messages.channelId.equals(excludeChannelLocalId).not(),
          );
    final row = await joined.getSingle();
    return row.read(countExp) ?? 0;
  }
}
