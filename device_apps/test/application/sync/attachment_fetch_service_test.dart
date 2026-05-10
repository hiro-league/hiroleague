import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:device_apps/application/sync/attachment_fetch_service.dart';
import 'package:device_apps/core/logging/app_talker.dart';
import 'package:device_apps/data/local/database/app_database.dart';
import 'package:device_apps/data/repositories/message_repository_impl.dart';
import 'package:device_apps/data/remote/gateway/gateway_inbound_frame.dart';
import 'package:device_apps/data/remote/gateway/gateway_contract.dart';
import 'package:device_apps/domain/models/message/message.dart';
import 'package:device_apps/domain/models/message/message_content.dart';
import 'package:device_apps/platform/storage/audio_storage_service.dart';
import 'package:crypto/crypto.dart';
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';

final _testBytes = Uint8List.fromList([1, 2, 3]);
final _testBlobId = 'sha256:${sha256.convert(_testBytes)}';
final _secondBytes = Uint8List.fromList([4, 5, 6]);
final _secondBlobId = 'sha256:${sha256.convert(_secondBytes)}';

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

  Future<void> insertMessage(String id) async {
    await db.messagesDao.insertMessage(
      MessagesCompanion.insert(
        id: id,
        channelId: 'server-42',
        senderId: 'server',
        contentType: 'audio',
        body: '',
        timestampMs: 1000,
        status: 'sent',
      ),
    );
  }

  Future<void> insertPendingAttachment(
    String messageId, {
    String? blobId,
  }) async {
    await db.messageAttachmentsDao.insertOrIgnore(
      MessageAttachmentsCompanion.insert(
        messageId: messageId,
        slotIndex: 0,
        contentType: 'audio',
        blobId: blobId ?? _testBlobId,
        mediaType: 'audio/mpeg',
        size: 3,
        chunkSize: 49152,
        chunkCount: 1,
        remoteRef: 'message_attachment:$messageId:0',
        fetchStatus: 'pending',
        createdAtMs: 1000,
      ),
    );
  }

  test(
    'tick fetches each row independently (no cross-row blob sharing)',
    () async {
      await insertMessage('msg-1');
      await insertMessage('msg-2');
      await insertPendingAttachment('msg-1');
      await insertPendingAttachment('msg-2');

      var fetches = 0;
      final saveCalls = <String>[];
      final service = AttachmentFetchService(
        attachmentsDao: db.messageAttachmentsDao,
        fetchBytes: (blobId) async {
          fetches += 1;
          return _testBytes;
        },
        saveBytes:
            ({required messageId, required bytes, required mimeType}) async {
              saveCalls.add(messageId);
              expect(mimeType, 'audio/mpeg');
              return '/audio/$messageId.mp3';
            },
      );

      final readyCount = await service.tick();

      expect(readyCount, 2);
      expect(fetches, 2);
      expect(saveCalls.toSet(), {'msg-1_0', 'msg-2_0'});
      final rows = await (db.select(db.messageAttachments)).get();
      expect(rows, hasLength(2));
      expect(rows.map((row) => row.fetchStatus).toSet(), {'ready'});
      expect(rows.map((row) => row.localPath).toSet(), {
        '/audio/msg-1_0.mp3',
        '/audio/msg-2_0.mp3',
      });
    },
  );

  test('tick fetches two unique blobs concurrently', () async {
    await insertMessage('msg-1');
    await insertMessage('msg-2');
    await insertPendingAttachment('msg-1');
    await insertPendingAttachment('msg-2', blobId: _secondBlobId);

    var inFlight = 0;
    var maxInFlight = 0;
    final service = AttachmentFetchService(
      attachmentsDao: db.messageAttachmentsDao,
      fetchBytes: (blobId) async {
        inFlight += 1;
        if (inFlight > maxInFlight) maxInFlight = inFlight;
        await Future<void>.delayed(const Duration(milliseconds: 20));
        inFlight -= 1;
        return blobId == _secondBlobId ? _secondBytes : _testBytes;
      },
      saveBytes:
          ({required messageId, required bytes, required mimeType}) async =>
              '/audio/$messageId.mp3',
    );

    final readyCount = await service.tick();

    expect(readyCount, 2);
    expect(maxInFlight, 2);
  });

  test('tick marks blob failed when files.get fails', () async {
    await insertMessage('msg-1');
    await insertPendingAttachment('msg-1');

    final service = AttachmentFetchService(
      attachmentsDao: db.messageAttachmentsDao,
      fetchBytes: (_) async => throw StateError('network down'),
      saveBytes:
          ({required messageId, required bytes, required mimeType}) async {
            fail('saveBytes should not run after fetch failure');
          },
    );

    final readyCount = await service.tick();

    expect(readyCount, 0);
    final row = await db.messageAttachmentsDao.findByBlobId(_testBlobId);
    expect(row?.fetchStatus, 'failed');
    expect(row?.lastFetchAttemptMs, isNotNull);
  });

  test('tick rejects bytes when sha does not match blob id', () async {
    await insertMessage('msg-1');
    await insertPendingAttachment('msg-1');

    final service = AttachmentFetchService(
      attachmentsDao: db.messageAttachmentsDao,
      fetchBytes: (_) async => Uint8List.fromList([9, 9, 9]),
      saveBytes:
          ({required messageId, required bytes, required mimeType}) async {
            fail('saveBytes should not run after sha mismatch');
          },
    );

    final readyCount = await service.tick();

    expect(readyCount, 0);
    final row = await db.messageAttachmentsDao.findByBlobId(_testBlobId);
    expect(row?.fetchStatus, 'failed');
    expect(row?.localPath, isNull);
  });

  test('tick retries failed rows after retry delay', () async {
    await insertMessage('msg-1');
    await insertPendingAttachment('msg-1');
    await db.messageAttachmentsDao.markFailed('msg-1', 0, 1000);

    var fetches = 0;
    final service = AttachmentFetchService(
      attachmentsDao: db.messageAttachmentsDao,
      nowMs: () => 31000,
      fetchBytes: (_) async {
        fetches += 1;
        return _testBytes;
      },
      saveBytes:
          ({required messageId, required bytes, required mimeType}) async =>
              '/audio/$messageId.mp3',
    );

    final readyCount = await service.tick();

    expect(readyCount, 1);
    expect(fetches, 1);
    final row = await db.messageAttachmentsDao.findByBlobId(_testBlobId);
    expect(row?.fetchStatus, 'ready');
  });

  test('tick retries stale fetching rows', () async {
    await insertMessage('msg-1');
    await insertPendingAttachment('msg-1');
    await db.messageAttachmentsDao.markFetching('msg-1', 0, 1000);

    final service = AttachmentFetchService(
      attachmentsDao: db.messageAttachmentsDao,
      nowMs: () => 121000,
      fetchBytes: (_) async => _testBytes,
      saveBytes:
          ({required messageId, required bytes, required mimeType}) async =>
              '/audio/$messageId.mp3',
    );

    final readyCount = await service.tick();

    expect(readyCount, 1);
    final row = await db.messageAttachmentsDao.findByBlobId(_testBlobId);
    expect(row?.fetchStatus, 'ready');
  });

  test(
    'watchMessages emits a playable audio bubble once the attachment row flips to ready',
    () async {
      final frames = StreamController<GatewayInboundFrame>.broadcast();
      final repo = MessageRepositoryImpl(
        messagesDao: db.messagesDao,
        channelsDao: db.channelsDao,
        attachmentsDao: db.messageAttachmentsDao,
        frameStream: frames.stream,
        audioStorage: _FakeAudioStorage(),
      );
      addTearDown(() async {
        repo.dispose();
        await frames.close();
      });

      await insertMessage('msg-1');
      await insertPendingAttachment('msg-1');

      final values = <List<Message>>[];
      final sub = repo.watchMessages('server-42').listen(values.add);
      addTearDown(sub.cancel);

      await _waitFor(() {
        final content = values.isEmpty ? null : values.last.single.content;
        return content is AudioContent && !content.audio.isPlayable;
      });

      await db.messageAttachmentsDao.markReady(
        'msg-1',
        0,
        '/audio/msg-1_0.mp3',
      );

      await _waitFor(() {
        final content = values.isEmpty ? null : values.last.single.content;
        return content is AudioContent &&
            content.audio.isPlayable &&
            content.audio.localPath == '/audio/msg-1_0.mp3';
      });
    },
  );

  test(
    'local outbound audio attachment is playable before history refresh',
    () async {
      final frames = StreamController<GatewayInboundFrame>.broadcast();
      final repo = MessageRepositoryImpl(
        messagesDao: db.messagesDao,
        channelsDao: db.channelsDao,
        attachmentsDao: db.messageAttachmentsDao,
        frameStream: frames.stream,
        audioStorage: _FakeAudioStorage(),
      );
      addTearDown(() async {
        repo.dispose();
        await frames.close();
      });

      await repo.insertOutbound(
        id: 'local-audio-1',
        channelId: 'server-42',
        senderId: 'device-1',
        contentType: ContentWire.audio,
        body: '',
        timestamp: DateTime.fromMillisecondsSinceEpoch(1000, isUtc: true),
      );
      await repo.upsertLocalAudioAttachment(
        messageId: 'local-audio-1',
        localPath: '/audio/local-audio-1_0',
        blobId: _testBlobId,
        mimeType: 'audio/mpeg',
        size: _testBytes.length,
        durationMs: 700,
      );

      final values = <List<Message>>[];
      final sub = repo.watchMessages('server-42').listen(values.add);
      addTearDown(sub.cancel);

      await _waitFor(() {
        final content = values.isEmpty ? null : values.last.single.content;
        return content is AudioContent &&
            content.audio.isPlayable &&
            content.audio.localPath == '/audio/local-audio-1_0';
      });
    },
  );

  test('message.voiced event upserts a ready attachment row', () async {
    final frames = StreamController<GatewayInboundFrame>.broadcast();
    final repo = MessageRepositoryImpl(
      messagesDao: db.messagesDao,
      channelsDao: db.channelsDao,
      attachmentsDao: db.messageAttachmentsDao,
      frameStream: frames.stream,
      audioStorage: _FakeAudioStorage(),
    );
    addTearDown(() async {
      repo.dispose();
      await frames.close();
    });

    await db.messagesDao.insertMessage(
      MessagesCompanion.insert(
        id: 'reply-1',
        channelId: 'server-42',
        senderId: 'server',
        contentType: 'text',
        body: 'hello',
        timestampMs: 1000,
        status: 'sent',
      ),
    );

    frames.add(
      GatewayInboundFrame(
        senderDeviceId: 'server',
        payload: {
          'version': UnifiedMessageWire.version,
          'message_type': UnifiedMessageWire.typeEvent,
          'routing': {
            'id': 'evt-1',
            'channel': 'devices',
            'direction': UnifiedMessageWire.directionOutbound,
            'sender_id': 'server',
          },
          'content': <Map<String, dynamic>>[],
          'event': {
            'type': EventWire.messageVoiced,
            'ref_id': 'reply-1',
            'data': {
              'audio': 'AQID',
              'mime_type': 'audio/mpeg',
              'duration_ms': 900,
              'blob_id': 'sha256:voice',
              'ref': 'message_attachment:reply-1:0',
              'size': 3,
              'chunk_size': 49152,
              'chunk_count': 1,
            },
          },
        },
      ),
    );

    await _waitFor(() async {
      final row = await db.messageAttachmentsDao.findByBlobId('sha256:voice');
      return row?.fetchStatus == 'ready' &&
          row?.localPath == '/audio/reply-1_0' &&
          row?.remoteRef == 'message_attachment:reply-1:0';
    });
  });

  test('live text from another paired device renders on user side', () async {
    final frames = StreamController<GatewayInboundFrame>.broadcast();
    final repo = MessageRepositoryImpl(
      messagesDao: db.messagesDao,
      channelsDao: db.channelsDao,
      attachmentsDao: db.messageAttachmentsDao,
      frameStream: frames.stream,
      audioStorage: _FakeAudioStorage(),
    );
    addTearDown(() async {
      repo.dispose();
      await frames.close();
    });

    frames.add(
      GatewayInboundFrame(
        senderDeviceId: 'server',
        payload: {
          'version': UnifiedMessageWire.version,
          'message_type': UnifiedMessageWire.typeMessage,
          'routing': {
            'id': 'live-text-1',
            'channel': 'devices',
            'direction': UnifiedMessageWire.directionOutbound,
            'sender_id': 'device-2',
            'metadata': {MetadataWire.chatChannelId: 'server-42'},
          },
          'content': [
            {'content_type': ContentWire.text, 'body': 'hello from phone'},
          ],
        },
      ),
    );

    await _waitFor(() async {
      final row = await db.messagesDao.getById('live-text-1');
      return row?.isOutbound == true && row?.senderId == 'device-2';
    });
  });

  test(
    'live inbound audio upserts a ready attachment row by blob id',
    () async {
      final frames = StreamController<GatewayInboundFrame>.broadcast();
      final repo = MessageRepositoryImpl(
        messagesDao: db.messagesDao,
        channelsDao: db.channelsDao,
        attachmentsDao: db.messageAttachmentsDao,
        frameStream: frames.stream,
        audioStorage: _FakeAudioStorage(),
      );
      addTearDown(() async {
        repo.dispose();
        await frames.close();
      });

      frames.add(
        GatewayInboundFrame(
          senderDeviceId: 'server',
          payload: {
            'version': UnifiedMessageWire.version,
            'message_type': UnifiedMessageWire.typeMessage,
            'routing': {
              'id': 'live-audio-1',
              'channel': 'devices',
              'direction': UnifiedMessageWire.directionOutbound,
              'sender_id': 'device-2',
              'metadata': {MetadataWire.chatChannelId: 'server-42'},
            },
            'content': [
              {
                'content_type': ContentWire.audio,
                'body': base64Encode(_testBytes),
                'metadata': {
                  'mime_type': 'audio/mpeg',
                  'duration_ms': 700,
                  'description': 'hello transcript',
                },
              },
            ],
          },
        ),
      );

      await _waitFor(() async {
        final row = await db.messageAttachmentsDao.findByBlobId(_testBlobId);
        final message = await db.messagesDao.getById('live-audio-1');
        return message?.isOutbound == true &&
            row?.messageId == 'live-audio-1' &&
            row?.fetchStatus == 'ready' &&
            row?.localPath == '/audio/live-audio-1_0' &&
            row?.remoteRef == 'message_attachment:live-audio-1:0';
      });
    },
  );
}

Future<void> _waitFor(FutureOr<bool> Function() condition) async {
  for (var i = 0; i < 50; i++) {
    if (await condition()) return;
    await Future<void>.delayed(const Duration(milliseconds: 20));
  }
  fail('condition was not met');
}

class _FakeAudioStorage implements AudioStorageService {
  @override
  Future<void> delete(String localPath) async {}

  @override
  Future<Uint8List?> loadBytes(String localPath) async => null;

  @override
  Future<String> save({
    required String messageId,
    required Uint8List bytes,
    required String tempPath,
    String blobUrl = '',
  }) async => blobUrl;

  @override
  Future<String> saveBytes({
    required String messageId,
    required Uint8List bytes,
    String mimeType = 'audio/m4a',
  }) async => '/audio/$messageId';
}
