import 'package:device_apps/application/sync/message_history_sync.dart';
import 'package:device_apps/core/logging/app_talker.dart';
import 'package:device_apps/data/local/database/app_database.dart';
import 'package:device_apps/domain/models/message/audio_attachment.dart';
import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late AppDatabase db;

  setUpAll(() async {
    await ensureAppTalkerInitialized();
  });

  setUp(() {
    db = AppDatabase(NativeDatabase.memory());
  });

  tearDown(() async {
    await db.close();
  });

  Future<ChannelRecord> insertChannel() async {
    await db
        .into(db.channels)
        .insert(
          ChannelsCompanion.insert(
            id: 'server-42',
            name: 'Hiro',
            serverId: const Value(42),
          ),
        );
    return (db.select(
      db.channels,
    )..where((c) => c.id.equals('server-42'))).getSingle();
  }

  test(
    'syncChannel upserts normalized messages and pending attachments',
    () async {
      final channel = await insertChannel();
      final seenParams = <Map<String, dynamic>>[];
      final sync = MessageHistorySync(
        channelsDao: db.channelsDao,
        messagesDao: db.messagesDao,
        attachmentsDao: db.messageAttachmentsDao,
        requestHistory: (params) async {
          seenParams.add(Map<String, dynamic>.from(params));
          if (params.containsKey('after')) {
            return {
              'status': 'ok',
              'data': {'messages': <Map<String, dynamic>>[]},
            };
          }
          return {
            'status': 'ok',
            'data': {
              'messages': [
                {
                  'id': 'agent-msg',
                  'sender_type': 'agent',
                  'sender_id': 'server',
                  'created_at': '2026-05-08T10:00:00Z',
                  'content': [
                    {'content_type': 'text', 'body': 'Sure.'},
                    {
                      'content_type': 'audio',
                      'body': 'message_attachment:agent-msg:0',
                      'metadata': {
                        'blob_id': 'sha256:agent',
                        'media_type': 'audio/mpeg',
                        'size': 12,
                        'chunk_size': 49152,
                        'chunk_count': 1,
                        'duration_ms': 500,
                      },
                    },
                  ],
                },
                {
                  'id': 'user-audio',
                  'sender_type': 'user',
                  'sender_id': 'other-user-device',
                  'created_at': '2026-05-08T10:00:01Z',
                  'content': [
                    {'content_type': 'text', 'body': 'hello transcript'},
                    {
                      'content_type': 'audio',
                      'body': 'message_attachment:user-audio:0',
                      'metadata': {
                        'blob_id': 'sha256:user',
                        'media_type': 'audio/m4a',
                        'size': 20,
                        'chunk_size': 49152,
                        'chunk_count': 1,
                        'duration_ms': 700,
                        'source': 'user_audio',
                      },
                    },
                  ],
                },
              ],
            },
          };
        },
      );

      final result = await sync.syncChannel(channel);

      expect(result.messages, 2);
      expect(result.attachments, 2);
      expect(seenParams.first, {'channel_id': 42, 'limit': 50});

      final rows = await (db.select(
        db.messages,
      )..orderBy([(m) => OrderingTerm(expression: m.timestampMs)])).get();
      expect(rows.map((r) => r.id), ['agent-msg', 'user-audio']);
      expect(rows.first.contentType, 'text');
      expect(rows.first.body, 'Sure.');
      expect(rows.first.metadata, equals(null));
      expect(rows.last.contentType, 'audio');
      expect(rows.last.transcript, 'hello transcript');
      expect(rows.last.isOutbound, isTrue);

      final attachments = await db.select(db.messageAttachments).get();
      expect(attachments, hasLength(2));
      expect(attachments.map((a) => a.fetchStatus).toSet(), {
        AttachmentFetchStatus.pending.name,
      });

      final refreshedChannel = await (db.select(
        db.channels,
      )..where((c) => c.id.equals('server-42'))).getSingle();
      expect(
        refreshedChannel.lastHistorySyncedAt,
        DateTime.parse('2026-05-08T10:00:01Z').millisecondsSinceEpoch,
      );
    },
  );

  test('syncChannel sends last server timestamp as after cursor', () async {
    await insertChannel();
    await db.channelsDao.updateLastHistorySyncedAt(
      'server-42',
      DateTime.parse('2026-05-08T10:00:01Z').millisecondsSinceEpoch,
    );
    final syncedChannel = await (db.select(
      db.channels,
    )..where((c) => c.id.equals('server-42'))).getSingle();
    final seenParams = <Map<String, dynamic>>[];

    final sync = MessageHistorySync(
      channelsDao: db.channelsDao,
      messagesDao: db.messagesDao,
      attachmentsDao: db.messageAttachmentsDao,
      requestHistory: (params) async {
        seenParams.add(Map<String, dynamic>.from(params));
        return {
          'status': 'ok',
          'data': {'messages': <Map<String, dynamic>>[]},
        };
      },
    );

    await sync.syncChannel(syncedChannel);

    expect(seenParams.single['after'], '2026-05-08T10:00:01Z');
  });

  test('syncAllServerBackedChannels returns processed channel count', () async {
    await insertChannel();
    final sync = MessageHistorySync(
      channelsDao: db.channelsDao,
      messagesDao: db.messagesDao,
      attachmentsDao: db.messageAttachmentsDao,
      requestHistory: (_) async => {
        'status': 'ok',
        'data': {'messages': <Map<String, dynamic>>[]},
      },
    );

    final count = await sync.syncAllServerBackedChannels();

    expect(count, 1);
  });

  test(
    'syncChannel inserts a fresh pending row even when another row already '
    'has the same blob (no cross-row sharing)',
    () async {
      final channel = await insertChannel();
      await db.messagesDao.insertMessage(
        MessagesCompanion.insert(
          id: 'cached-msg',
          channelId: 'server-42',
          senderId: 'server',
          contentType: 'text',
          body: 'cached',
          timestampMs: 1,
          status: 'sent',
        ),
      );
      await db.messageAttachmentsDao.insertOrIgnore(
        MessageAttachmentsCompanion.insert(
          messageId: 'cached-msg',
          slotIndex: 0,
          contentType: 'audio',
          blobId: 'sha256:same',
          mediaType: 'audio/mpeg',
          size: 10,
          chunkSize: 49152,
          chunkCount: 1,
          remoteRef: 'message_attachment:cached-msg:0',
          localPath: const Value('/audio/cached.mp3'),
          fetchStatus: AttachmentFetchStatus.ready.name,
          createdAtMs: 1,
        ),
      );

      final sync = MessageHistorySync(
        channelsDao: db.channelsDao,
        messagesDao: db.messagesDao,
        attachmentsDao: db.messageAttachmentsDao,
        requestHistory: (_) async => {
          'status': 'ok',
          'data': {
            'messages': [
              {
                'id': 'new-msg',
                'sender_type': 'agent',
                'sender_id': 'server',
                'created_at': '2026-05-08T10:00:00Z',
                'content': [
                  {'content_type': 'text', 'body': 'again'},
                  {
                    'content_type': 'audio',
                    'body': 'message_attachment:new-msg:0',
                    'metadata': {
                      'blob_id': 'sha256:same',
                      'media_type': 'audio/mpeg',
                      'size': 10,
                      'chunk_size': 49152,
                      'chunk_count': 1,
                    },
                  },
                ],
              },
            ],
          },
        },
      );

      await sync.syncChannel(channel);

      final row = await (db.select(
        db.messageAttachments,
      )..where((a) => a.messageId.equals('new-msg'))).getSingle();
      expect(row.fetchStatus, AttachmentFetchStatus.pending.name);
      expect(row.localPath, equals(null));

      final cached = await (db.select(
        db.messageAttachments,
      )..where((a) => a.messageId.equals('cached-msg'))).getSingle();
      expect(cached.fetchStatus, AttachmentFetchStatus.ready.name);
      expect(cached.localPath, '/audio/cached.mp3');
    },
  );
}
