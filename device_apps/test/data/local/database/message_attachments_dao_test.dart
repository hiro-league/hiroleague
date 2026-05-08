import 'package:device_apps/data/local/database/app_database.dart';
import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late AppDatabase db;

  setUp(() {
    db = AppDatabase(NativeDatabase.memory());
  });

  tearDown(() async {
    await db.close();
  });

  test('message attachment rows can move through fetch states', () async {
    await db.messagesDao.insertMessage(
      MessagesCompanion.insert(
        id: 'msg-1',
        channelId: 'channel-1',
        senderId: 'server',
        contentType: 'text',
        body: 'hello',
        timestampMs: 1000,
        status: 'sent',
      ),
    );

    await db.messageAttachmentsDao.insertOrIgnore(
      MessageAttachmentsCompanion.insert(
        messageId: 'msg-1',
        slotIndex: 0,
        contentType: 'audio',
        blobId: 'sha256:abc',
        mediaType: 'audio/mpeg',
        size: 123,
        chunkSize: 49152,
        chunkCount: 1,
        remoteRef: 'message_attachment:msg-1:0',
        fetchStatus: 'pending',
        createdAtMs: 1000,
        durationMs: const Value(500),
      ),
    );

    expect(await db.messageAttachmentsDao.getMissingBlobIds(), hasLength(1));

    await db.messageAttachmentsDao.markFetching('sha256:abc', 1200);
    final fetching = await db.messageAttachmentsDao.findByBlobId('sha256:abc');
    expect(fetching?.fetchStatus, 'fetching');
    expect(fetching?.lastFetchAttemptMs, 1200);

    await db.messageAttachmentsDao.markReady('sha256:abc', '/audio/abc.mp3');
    final ready = await db.messageAttachmentsDao.findReadyByBlobId(
      'sha256:abc',
    );
    expect(ready?.localPath, '/audio/abc.mp3');

    await db.messageAttachmentsDao.markFailed('sha256:abc', 1400);
    final failed = await db.messageAttachmentsDao.findByBlobId('sha256:abc');
    expect(failed?.fetchStatus, 'failed');
    expect(failed?.lastFetchAttemptMs, 1400);
  });
}
