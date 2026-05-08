import 'dart:convert';

import 'package:drift/drift.dart' show Value;

import '../../core/utils/blob_id.dart';
import '../../core/utils/logger.dart';
import '../../core/utils/message_ownership.dart';
import '../../data/local/database/app_database.dart';
import '../../data/local/database/daos/channels_dao.dart';
import '../../data/local/database/daos/message_attachments_dao.dart';
import '../../data/local/database/daos/messages_dao.dart';
import '../../data/remote/gateway/gateway_contract.dart';
import '../../domain/models/message/audio_attachment.dart';
import '../../domain/models/message/message_status.dart';

final _log = Logger.get('MessageHistorySync');

typedef MessageHistoryRequester =
    Future<Map<String, dynamic>> Function(Map<String, dynamic> params);

final class MessageHistorySyncResult {
  const MessageHistorySyncResult({
    required this.messages,
    required this.attachments,
    required this.pages,
  });

  final int messages;
  final int attachments;
  final int pages;
}

final class MessageHistorySync {
  MessageHistorySync({
    required ChannelsDao channelsDao,
    required MessagesDao messagesDao,
    required MessageAttachmentsDao attachmentsDao,
    required MessageHistoryRequester requestHistory,
    this.pageLimit = 50,
  }) : _channelsDao = channelsDao,
       _messagesDao = messagesDao,
       _attachmentsDao = attachmentsDao,
       _requestHistory = requestHistory;

  final ChannelsDao _channelsDao;
  final MessagesDao _messagesDao;
  final MessageAttachmentsDao _attachmentsDao;
  final MessageHistoryRequester _requestHistory;
  final int pageLimit;

  Future<int> syncAllServerBackedChannels() async {
    final channels = await _channelsDao.listServerBacked();
    for (final channel in channels) {
      await syncChannel(channel);
    }
    return channels.length;
  }

  Future<MessageHistorySyncResult> syncChannel(ChannelRecord channel) async {
    final serverId = channel.serverId;
    if (serverId == null) {
      return const MessageHistorySyncResult(
        messages: 0,
        attachments: 0,
        pages: 0,
      );
    }

    final started = DateTime.now();
    var afterIso = channel.lastHistorySyncedAt != null
        ? _serverIsoFromMs(channel.lastHistorySyncedAt!)
        : null;
    var afterId = channel.lastHistorySyncedExternalId;
    var maxCreatedAtMs = channel.lastHistorySyncedAt;
    var maxCreatedAtId = channel.lastHistorySyncedExternalId;
    var messagesCount = 0;
    var attachmentsCount = 0;
    var pages = 0;

    while (true) {
      _log.info(
        '⬇️ History sync — ${channel.id} · pull_after',
        fields: {
          'after': afterIso,
          'after_id': afterId,
          'page_limit': pageLimit,
        },
      );
      final params = <String, dynamic>{
        'channel_id': serverId,
        'limit': pageLimit,
        'after': ?afterIso,
        'after_id': ?afterId,
      };
      final response = await _requestHistory(params);
      final data = response['data'];
      if (data is! Map) break;
      final rawMessages = data['messages'];
      if (rawMessages is! List) break;

      final messages = rawMessages
          .whereType<Map>()
          .map((row) => Map<String, dynamic>.from(row))
          .toList();
      if (messages.isEmpty) break;
      pages += 1;

      String? lastIdInPage;
      String? lastIsoInPage;
      for (final message in messages) {
        final applied = await _applyMessage(channel, message);
        messagesCount += 1;
        attachmentsCount += applied.attachments;
        final messageId = message['id']?.toString();
        final createdAtIso = message['created_at']?.toString();
        final createdAtMs = _parseCreatedAtMs(createdAtIso);
        if (createdAtMs != null &&
            (maxCreatedAtMs == null || createdAtMs >= maxCreatedAtMs)) {
          maxCreatedAtMs = createdAtMs;
          maxCreatedAtId = messageId ?? maxCreatedAtId;
        }
        if (messageId != null) lastIdInPage = messageId;
        if (createdAtIso != null) lastIsoInPage = createdAtIso;
      }

      if (messages.length < pageLimit ||
          lastIsoInPage == null ||
          lastIdInPage == null) {
        break;
      }
      afterIso = lastIsoInPage;
      afterId = lastIdInPage;
    }

    if (maxCreatedAtMs != null) {
      await _channelsDao.updateLastHistorySyncedCursor(
        channel.id,
        syncedAtMs: maxCreatedAtMs,
        externalId: maxCreatedAtId,
      );
    }

    _log.info(
      '✅ History sync — ${channel.id} · $messagesCount new, $attachmentsCount attachments',
      fields: {
        'pages': pages,
        'elapsed_ms': DateTime.now().difference(started).inMilliseconds,
      },
    );
    return MessageHistorySyncResult(
      messages: messagesCount,
      attachments: attachmentsCount,
      pages: pages,
    );
  }

  Future<_AppliedMessage> _applyMessage(
    ChannelRecord channel,
    Map<String, dynamic> message,
  ) async {
    final messageId = message['id']?.toString();
    if (messageId == null || messageId.isEmpty) {
      return const _AppliedMessage(attachments: 0);
    }

    final content = _contentItems(message['content']);
    final textItem = content.cast<Map<String, dynamic>?>().firstWhere(
      (item) => item?['content_type'] == ContentWire.text,
      orElse: () => null,
    );
    final audioItems = content
        .where((item) => item['content_type'] == ContentWire.audio)
        .toList();
    final senderType = message['sender_type']?.toString();
    final senderId = message['sender_id']?.toString() ?? '';
    final textBody = textItem?['body']?.toString() ?? '';
    final createdAtMs =
        _parseCreatedAtMs(message['created_at']) ??
        DateTime.now().toUtc().millisecondsSinceEpoch;
    final isOutbound = isUserSideHistoryMessage(
      senderType: senderType,
      senderId: senderId,
    );

    // Two cases produce an "audio bubble" (contentType=audio):
    //   1. user voice message (server sender_type=user) — the audio IS the message,
    //      and any text item carries the transcript.
    //   2. agent has audio but no text — degenerate, treat as an audio bubble.
    // Otherwise we keep the message as text and let the audio attachment surface
    // as a TTS voice reply via the `source == character_tts` gate.
    final firstAudio = audioItems.isNotEmpty ? audioItems.first : null;
    final isAudioBubble =
        firstAudio != null &&
        (senderType == userSenderType || textBody.isEmpty);
    final messageContentType = isAudioBubble
        ? ContentWire.audio
        : ContentWire.text;
    final messageBody = isAudioBubble ? '' : textBody;
    final transcript = isAudioBubble && textBody.isNotEmpty ? textBody : null;

    await _messagesDao.insertMessageOrIgnore(
      MessagesCompanion.insert(
        id: messageId,
        channelId: channel.id,
        senderId: senderId,
        contentType: messageContentType,
        body: messageBody,
        timestampMs: createdAtMs,
        status: MessageStatus.delivered.name,
        isOutbound: Value(isOutbound),
        transcript: Value(transcript),
        metadata: const Value(null),
      ),
    );

    var attachmentCount = 0;
    for (final audioItem in audioItems) {
      final inserted = await _insertAttachment(
        messageId,
        createdAtMs,
        audioItem,
      );
      if (inserted) attachmentCount += 1;
    }

    return _AppliedMessage(attachments: attachmentCount);
  }

  Future<bool> _insertAttachment(
    String messageId,
    int createdAtMs,
    Map<String, dynamic> audioItem,
  ) async {
    final metadata = _metadata(audioItem);
    final blobId = metadata['blob_id']?.toString();
    final remoteRef = audioItem['body']?.toString();
    if (blobId == null ||
        blobId.isEmpty ||
        remoteRef == null ||
        remoteRef.isEmpty) {
      return false;
    }

    final ready = await _attachmentsDao.findReadyByBlobId(blobId);
    final readyPath = ready?.localPath;
    final slotIndex = slotIndexFromAttachmentRef(remoteRef) ?? 0;

    await _attachmentsDao.insertOrIgnore(
      MessageAttachmentsCompanion.insert(
        messageId: messageId,
        slotIndex: slotIndex,
        contentType: audioItem['content_type']?.toString() ?? ContentWire.audio,
        blobId: blobId,
        mediaType: metadata['media_type']?.toString() ?? 'audio/m4a',
        size: _asInt(metadata['size']) ?? 0,
        durationMs: Value(_asInt(metadata['duration_ms'])),
        chunkSize: _asInt(metadata['chunk_size']) ?? 0,
        chunkCount: _asInt(metadata['chunk_count']) ?? 0,
        remoteRef: remoteRef,
        localPath: Value(readyPath),
        fetchStatus: readyPath != null && readyPath.isNotEmpty
            ? AttachmentFetchStatus.ready.name
            : AttachmentFetchStatus.pending.name,
        metadata: Value(_metadataJson(metadata)),
        createdAtMs: createdAtMs,
      ),
    );
    return true;
  }

  static List<Map<String, dynamic>> _contentItems(Object? raw) {
    if (raw is! List) return const [];
    return raw
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
  }

  static Map<String, dynamic> _metadata(Map<String, dynamic> item) {
    final raw = item['metadata'];
    if (raw is Map) return Map<String, dynamic>.from(raw);
    return const {};
  }

  static String _metadataJson(Map<String, dynamic> metadata) =>
      jsonEncode(metadata);

  static int? _parseCreatedAtMs(Object? raw) {
    if (raw == null) return null;
    return DateTime.tryParse(raw.toString())?.toUtc().millisecondsSinceEpoch;
  }

  static String _serverIsoFromMs(int ms) {
    final iso = DateTime.fromMillisecondsSinceEpoch(
      ms,
      isUtc: true,
    ).toIso8601String();
    return iso.endsWith('.000Z') ? '${iso.substring(0, iso.length - 5)}Z' : iso;
  }

  static int? _asInt(Object? value) {
    if (value == null) return null;
    if (value is int) return value;
    if (value is num) return value.toInt();
    return int.tryParse(value.toString());
  }
}

final class _AppliedMessage {
  const _AppliedMessage({required this.attachments});

  final int attachments;
}
