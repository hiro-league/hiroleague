import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:drift/drift.dart' show Value;
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../core/utils/blob_id.dart';
import '../../core/utils/logger.dart';
import '../../core/utils/message_ownership.dart';
import '../../application/gateway/gateway_notifier.dart';
import '../../data/remote/gateway/gateway_inbound_frame.dart';
import '../../data/remote/gateway/gateway_contract.dart';
import '../../data/remote/gateway/unified_message.dart';
import '../../domain/models/message/audio_attachment.dart';
import '../../domain/models/message/message.dart';
import '../../domain/models/message/message_content.dart';
import '../../domain/models/message/message_status.dart';
import '../../domain/repositories/message_repository.dart';
import '../../platform/storage/audio_storage_service.dart';
import '../local/database/app_database.dart';
import '../local/database/daos/channels_dao.dart';
import '../local/database/daos/message_attachments_dao.dart';
import '../local/database/daos/messages_dao.dart';

part 'message_repository_impl.g.dart';

final _log = Logger.get('MessageRepository');

/// Server-set ``metadata.source`` values on attachment rows. Only the
/// ``character_tts`` source qualifies an audio attachment as a "voice reply"
/// to a text message bubble — without this gate, any audio row glued to a
/// text message would be rendered as a TTS reply.
const String _attachmentSourceCharacterTts = 'character_tts';
const String _attachmentSourceUserAudio = 'user_audio';

class MessageRepositoryImpl implements MessageRepository {
  MessageRepositoryImpl({
    required MessagesDao messagesDao,
    required ChannelsDao channelsDao,
    required MessageAttachmentsDao attachmentsDao,
    required Stream<GatewayInboundFrame> frameStream,
    required AudioStorageService audioStorage,
  }) : _messagesDao = messagesDao,
       _channelsDao = channelsDao,
       _attachmentsDao = attachmentsDao,
       _audioStorage = audioStorage {
    _sub = frameStream.listen(_onInboundFrame);
  }

  final MessagesDao _messagesDao;
  final ChannelsDao _channelsDao;
  final MessageAttachmentsDao _attachmentsDao;
  final AudioStorageService _audioStorage;
  StreamSubscription<GatewayInboundFrame>? _sub;

  @override
  Stream<List<Message>> watchMessages(String channelId) {
    final controller = StreamController<List<Message>>();
    StreamSubscription<List<MessageRecord>>? messagesSub;
    StreamSubscription<List<MessageAttachmentRecord>>? attachmentsSub;
    List<MessageRecord>? latestMessages;
    List<MessageAttachmentRecord> latestAttachments = const [];

    void emit() {
      final rows = latestMessages;
      if (rows == null || controller.isClosed) return;
      final byMessage = <String, List<MessageAttachmentRecord>>{};
      for (final attachment in latestAttachments) {
        byMessage.putIfAbsent(attachment.messageId, () => []).add(attachment);
      }
      controller.add(
        rows
            .map((row) => _rowToMessage(row, byMessage[row.id] ?? const []))
            .toList(),
      );
    }

    controller.onListen = () {
      messagesSub = _messagesDao.watchChannelMessages(channelId).listen((rows) {
        latestMessages = rows;
        emit();
      }, onError: controller.addError);
      attachmentsSub = _attachmentsDao.watchForChannel(channelId).listen((
        rows,
      ) {
        latestAttachments = rows;
        emit();
      }, onError: controller.addError);
    };
    controller.onCancel = () async {
      await messagesSub?.cancel();
      await attachmentsSub?.cancel();
    };

    return controller.stream;
  }

  @override
  Future<void> insertOutbound({
    required String id,
    required String channelId,
    required String senderId,
    required String contentType,
    required String body,
    required DateTime timestamp,
    String? metadata,
  }) async {
    await _messagesDao.insertMessage(
      MessagesCompanion.insert(
        id: id,
        channelId: channelId,
        senderId: senderId,
        contentType: contentType,
        body: body,
        timestampMs: timestamp.millisecondsSinceEpoch,
        status: MessageStatus.sending.name,
        isOutbound: Value(true),
        metadata: Value(metadata),
      ),
    );
  }

  @override
  Future<void> upsertLocalAudioAttachment({
    required String messageId,
    required String localPath,
    required String blobId,
    required String mimeType,
    required int size,
    required int durationMs,
    int slotIndex = 0,
    int? chunkSize,
    int? chunkCount,
  }) async {
    final resolvedChunkSize = chunkSize ?? defaultBlobChunkSize;
    final resolvedChunkCount =
        chunkCount ?? blobChunkCountForSize(size, resolvedChunkSize);
    final attachmentMetadata = jsonEncode({
      'source': _attachmentSourceUserAudio,
      'duration_ms': durationMs,
      'mime_type': mimeType,
    });

    await _attachmentsDao.insertOrUpdate(
      MessageAttachmentsCompanion.insert(
        messageId: messageId,
        slotIndex: slotIndex,
        contentType: ContentWire.audio,
        blobId: blobId,
        mediaType: mimeType,
        size: size,
        durationMs: Value(durationMs),
        chunkSize: resolvedChunkSize,
        chunkCount: resolvedChunkCount,
        remoteRef: messageAttachmentRef(messageId, slotIndex),
        localPath: Value(localPath),
        fetchStatus: AttachmentFetchStatus.ready.name,
        metadata: Value(attachmentMetadata),
        createdAtMs: DateTime.now().toUtc().millisecondsSinceEpoch,
      ),
    );
  }

  @override
  Future<void> updateMessageStatus(
    String messageId,
    MessageStatus status,
  ) async {
    await _messagesDao.updateStatus(messageId, status.name);
  }

  @override
  void dispose() => _sub?.cancel();

  Future<void> _onInboundFrame(GatewayInboundFrame frame) async {
    final version = frame.payload['version']?.toString();
    if (version != UnifiedMessageWire.version) {
      _log.warning(
        'Dropping frame — unsupported UnifiedMessage version',
        fields: {'version': version, 'expected': UnifiedMessageWire.version},
      );
      return;
    }

    late UnifiedMessage msg;
    try {
      msg = UnifiedMessage.fromJson(frame.payload);
    } on FormatException catch (e) {
      _log.warning(
        'Dropping malformed frame — schema mismatch',
        fields: {'error': e.message},
      );
      return;
    }

    // Response frames are routed in GatewayNotifier before broadcast — skip here
    if (msg.messageType == UnifiedMessageWire.typeResponse) return;

    // Handle event frames (delivery acks, transcription results).
    if (msg.messageType == UnifiedMessageWire.typeEvent && msg.event != null) {
      await _handleEvent(msg);
      return;
    }

    if (msg.messageType != UnifiedMessageWire.typeMessage) {
      _log.debug(
        'Ignoring non-message frame',
        fields: {'message_type': msg.messageType, 'id': msg.routing.id},
      );
      return;
    }

    final audioIndex = msg.content.indexWhere(
      (c) => c.contentType == ContentWire.audio,
    );
    final audioItem = audioIndex >= 0 ? msg.content[audioIndex] : null;
    final textItem = msg.content
        .where((c) => c.contentType == ContentWire.text)
        .firstOrNull;

    if (audioItem != null) {
      await _handleInboundAudio(msg, audioItem, audioIndex);
    } else if (textItem != null && textItem.body.isNotEmpty) {
      await _handleInboundText(msg, textItem);
    } else {
      _log.warning(
        'Dropping frame — no usable content item',
        fields: {
          'message_id': msg.routing.id,
          'content_types': msg.content.map((c) => c.contentType).toList(),
        },
      );
    }
  }

  // ---------------------------------------------------------------------------
  // Event handling
  // ---------------------------------------------------------------------------

  Future<void> _handleEvent(UnifiedMessage msg) async {
    final event = msg.event!;
    final refId = event.refId;
    if (refId == null || refId.isEmpty) return;

    switch (event.type) {
      case EventWire.messageReceived:
        await _messagesDao.updateStatus(refId, MessageStatus.delivered.name);
        _log.debug('Message marked delivered', fields: {'ref_id': refId});

      case EventWire.messageTranscribed:
        await _messagesDao.updateStatus(refId, MessageStatus.read.name);
        final transcript = event.data['transcript'] as String?;
        if (transcript != null && transcript.isNotEmpty) {
          await _messagesDao.updateTranscript(refId, transcript);
        }
        _log.debug('Message transcribed', fields: {'ref_id': refId});

      case EventWire.messageVoiced:
        await _handleMessageVoiced(refId, event.data);

      case EventWire.resourceChanged:
        _log.debug('Resource changed hint received');

      default:
        _log.debug(
          'Ignoring unknown event type',
          fields: {'event_type': event.type},
        );
    }
  }

  Future<void> _handleMessageVoiced(
    String refId,
    Map<String, dynamic> data,
  ) async {
    final audioB64 = data['audio'] as String?;
    if (audioB64 == null || audioB64.isEmpty) {
      _log.debug(
        'Voice reply event without audio body',
        fields: {'ref_id': refId},
      );
      return;
    }

    final mimeType = data['mime_type'] as String? ?? 'audio/mpeg';
    final durationMs = (data['duration_ms'] as num?)?.toInt() ?? 0;
    final Uint8List bytes;
    try {
      bytes = Uint8List.fromList(base64Decode(audioB64));
    } catch (e) {
      _log.warning(
        'Failed to decode voice reply audio',
        fields: {'ref_id': refId, 'error': e.toString()},
      );
      return;
    }

    // Trust the server's blob_id when it sends one, but verify it matches
    // the bytes we received — drift between the two is a real bug, not a
    // gracefully-handle-in-the-background problem.
    final serverBlobId = data['blob_id'] as String?;
    final localBlobId = blobIdForBytes(bytes);
    if (serverBlobId != null &&
        serverBlobId.isNotEmpty &&
        serverBlobId != localBlobId) {
      _log.warning(
        'Voice reply blob_id mismatch — using local digest',
        fields: {
          'ref_id': refId,
          'server_blob_id': serverBlobId,
          'local_blob_id': localBlobId,
        },
      );
    }
    final blobId = serverBlobId ?? localBlobId;

    final row = await _messagesDao.getById(refId);
    if (row == null) {
      _log.debug(
        'Voice reply for unknown message — skipped attachment row',
        fields: {'ref_id': refId},
      );
      return;
    }

    final remoteRef = data['ref'] as String? ?? messageAttachmentRef(refId, 0);
    final slotIndex = slotIndexFromAttachmentRef(remoteRef) ?? 0;

    final String localPath;
    try {
      localPath = await _audioStorage.saveBytes(
        messageId: attachmentStorageId(refId, slotIndex),
        bytes: bytes,
        mimeType: mimeType,
      );
    } catch (e) {
      _log.warning(
        'Failed to save voice reply audio',
        fields: {'ref_id': refId, 'error': e.toString()},
      );
      return;
    }
    final size = (data['size'] as num?)?.toInt() ?? bytes.length;
    final chunkSize =
        (data['chunk_size'] as num?)?.toInt() ?? defaultBlobChunkSize;
    final chunkCount =
        (data['chunk_count'] as num?)?.toInt() ??
        blobChunkCountForSize(size, chunkSize);

    // ``source`` lets _parseTextContent gate the "this is a TTS voice reply
    // for the bubble's text" rendering. Without it, any audio attached to a
    // text row would be rendered as if it were a TTS reply.
    final attachmentMetadata = jsonEncode({
      'source': _attachmentSourceCharacterTts,
      'duration_ms': durationMs,
      'mime_type': mimeType,
    });

    await _attachmentsDao.insertOrUpdate(
      MessageAttachmentsCompanion.insert(
        messageId: refId,
        slotIndex: slotIndex,
        contentType: ContentWire.audio,
        blobId: blobId,
        mediaType: mimeType,
        size: size,
        durationMs: Value(durationMs),
        chunkSize: chunkSize,
        chunkCount: chunkCount,
        remoteRef: remoteRef,
        localPath: Value(localPath),
        fetchStatus: AttachmentFetchStatus.ready.name,
        metadata: Value(attachmentMetadata),
        createdAtMs: DateTime.now().toUtc().millisecondsSinceEpoch,
      ),
    );
    _log.info(
      '⬇️ Voice reply — ${row.channelId} · live cached',
      fields: {'ref_id': refId, 'bytes': size, 'blob_id': blobId},
    );
  }

  // ---------------------------------------------------------------------------
  // Inbound audio message
  // ---------------------------------------------------------------------------

  Future<void> _handleInboundAudio(
    UnifiedMessage msg,
    ContentItem audioItem,
    int slotIndex,
  ) async {
    final id = msg.routing.id;
    final senderId = msg.routing.senderId;
    final channelId =
        msg.routing.metadata[MetadataWire.chatChannelId]?.toString() ??
        await _resolveDefaultChannelId();
    final timestamp = DateTime.now().toUtc();
    final isOutbound = isUserSideSenderId(senderId);
    final transcript = audioItem.metadata['description'] as String?;

    // The message row is independent of whether the bytes saved — if decode
    // fails we still want the bubble (with transcript / "tap to retry"
    // affordance) to appear in the list.
    await _messagesDao.insertMessage(
      MessagesCompanion.insert(
        id: id,
        channelId: channelId,
        senderId: senderId,
        contentType: ContentWire.audio,
        body: '',
        timestampMs: timestamp.millisecondsSinceEpoch,
        status: MessageStatus.delivered.name,
        isOutbound: Value(isOutbound),
        transcript: Value(transcript),
      ),
    );

    if (audioItem.body.isEmpty) {
      _log.debug(
        'Inbound audio without inline bytes — fetch via files.get',
        fields: {'msg_id': id},
      );
      await _touchChannelTimestamp(channelId, timestamp);
      return;
    }

    Uint8List? bytes;
    try {
      bytes = Uint8List.fromList(base64Decode(audioItem.body));
    } catch (e) {
      _log.warning(
        'Failed to decode inbound audio',
        fields: {'msg_id': id, 'error': e.toString()},
      );
    }

    if (bytes == null) {
      // No bytes on disk → leave attachment to be created by the next
      // history sync, where it will be marked ``pending`` and the fetch
      // service will pull from the server. Inserting a ``failed`` row here
      // would block that retry behind ``failedRetryDelay``.
      await _touchChannelTimestamp(channelId, timestamp);
      return;
    }

    final mimeType = audioItem.metadata['mime_type'] as String? ?? 'audio/m4a';
    final serverBlobId = audioItem.metadata['blob_id'] as String?;
    final localBlobId = blobIdForBytes(bytes);
    if (serverBlobId != null &&
        serverBlobId.isNotEmpty &&
        serverBlobId != localBlobId) {
      _log.warning(
        'Inbound audio blob_id mismatch — using local digest',
        fields: {
          'msg_id': id,
          'server_blob_id': serverBlobId,
          'local_blob_id': localBlobId,
        },
      );
    }
    final blobId = serverBlobId ?? localBlobId;

    String? localPath;
    try {
      localPath = await _audioStorage.saveBytes(
        messageId: attachmentStorageId(id, slotIndex),
        bytes: bytes,
        mimeType: mimeType,
      );
    } catch (e) {
      _log.warning(
        'Failed to save inbound audio bytes to storage',
        fields: {'msg_id': id, 'error': e.toString()},
      );
    }

    if (localPath == null) {
      // Same rationale as the bytes==null branch above: leave the row to a
      // future history-sync pull rather than persisting a ``failed`` row.
      await _touchChannelTimestamp(channelId, timestamp);
      return;
    }

    final size = (audioItem.metadata['size'] as num?)?.toInt() ?? bytes.length;
    final chunkSize =
        (audioItem.metadata['chunk_size'] as num?)?.toInt() ??
        defaultBlobChunkSize;
    final chunkCount =
        (audioItem.metadata['chunk_count'] as num?)?.toInt() ??
        blobChunkCountForSize(size, chunkSize);
    final durationMs =
        (audioItem.metadata['duration_ms'] as num?)?.toInt() ?? 0;

    final attachmentMetadata = jsonEncode({
      'source': _attachmentSourceUserAudio,
      'duration_ms': durationMs,
      'mime_type': mimeType,
    });

    await _attachmentsDao.insertOrUpdate(
      MessageAttachmentsCompanion.insert(
        messageId: id,
        slotIndex: slotIndex,
        contentType: ContentWire.audio,
        blobId: blobId,
        mediaType: mimeType,
        size: size,
        durationMs: Value(durationMs),
        chunkSize: chunkSize,
        chunkCount: chunkCount,
        remoteRef: messageAttachmentRef(id, slotIndex),
        localPath: Value(localPath),
        fetchStatus: AttachmentFetchStatus.ready.name,
        metadata: Value(attachmentMetadata),
        createdAtMs: timestamp.millisecondsSinceEpoch,
      ),
    );
    _log.info(
      '⬇️ Audio message — $channelId · live cached',
      fields: {'bytes': size, 'blob_id': blobId, 'msg_id': id},
    );

    await _touchChannelTimestamp(channelId, timestamp);
  }

  // ---------------------------------------------------------------------------
  // Inbound text message
  // ---------------------------------------------------------------------------

  Future<void> _handleInboundText(
    UnifiedMessage msg,
    ContentItem textItem,
  ) async {
    final id = msg.routing.id;
    final senderId = msg.routing.senderId;
    final channelId =
        msg.routing.metadata[MetadataWire.chatChannelId]?.toString() ??
        await _resolveDefaultChannelId();
    final timestamp = DateTime.now().toUtc();
    final isOutbound = isUserSideSenderId(senderId);

    await _messagesDao.insertMessage(
      MessagesCompanion.insert(
        id: id,
        channelId: channelId,
        senderId: senderId,
        contentType: textItem.contentType,
        body: textItem.body,
        timestampMs: timestamp.millisecondsSinceEpoch,
        status: MessageStatus.delivered.name,
        isOutbound: Value(isOutbound),
      ),
    );

    await _touchChannelTimestamp(channelId, timestamp);
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  /// Resolve the first available local channel id as a fallback when
  /// the server doesn't include chat_channel_id in routing metadata.
  Future<String> _resolveDefaultChannelId() async {
    final first = await _channelsDao.getFirst();
    return first?.id ?? 'unknown';
  }

  Future<void> _touchChannelTimestamp(
    String channelId,
    DateTime timestamp,
  ) async {
    final existingChannel = await _channelsDao.getById(channelId);
    if (existingChannel != null) {
      await _channelsDao.insertOrUpdate(
        existingChannel
            .toCompanion(true)
            .copyWith(lastMessageAt: Value(timestamp.millisecondsSinceEpoch)),
      );
    } else {
      _log.warning('Received message for unknown channel: $channelId');
    }
  }

  Message _rowToMessage(
    MessageRecord row, [
    List<MessageAttachmentRecord> attachments = const [],
  ]) {
    // Sort defensively: even though watchForChannel orders by slot_index, a
    // future caller might bypass it. Renderers should never rely on hash-map
    // iteration order to pick "the right" attachment.
    final ordered = [...attachments]
      ..sort((a, b) => a.slotIndex.compareTo(b.slotIndex));
    final MessageContent content = switch (row.contentType) {
      ContentWire.text => _parseTextContent(row, ordered),
      ContentWire.audio => _parseAudioContent(row, ordered),
      final other => UnsupportedContent(other),
    };
    return Message(
      id: row.id,
      channelId: row.channelId,
      senderId: row.senderId,
      content: content,
      timestamp: DateTime.fromMillisecondsSinceEpoch(
        row.timestampMs,
        isUtc: true,
      ),
      status: MessageStatus.fromName(row.status),
      isOutbound: row.isOutbound,
    );
  }

  static AudioAttachment _audioAttachmentFromRecord(
    MessageAttachmentRecord row,
  ) {
    return AudioAttachment(
      durationMs: row.durationMs ?? 0,
      localPath: row.localPath,
      mimeType: row.mediaType,
      blobId: row.blobId,
      remoteRef: row.remoteRef,
      size: row.size,
      chunkSize: row.chunkSize,
      chunkCount: row.chunkCount,
      fetchStatus: AttachmentFetchStatus.fromName(row.fetchStatus),
    );
  }

  static String? _attachmentSource(MessageAttachmentRecord row) {
    final raw = row.metadata;
    if (raw == null || raw.isEmpty) return null;
    try {
      final decoded = jsonDecode(raw);
      if (decoded is Map<String, dynamic>) {
        final source = decoded['source'];
        if (source is String && source.isNotEmpty) return source;
      }
    } on FormatException {
      // Malformed metadata is non-fatal — caller treats null as "unknown".
    }
    return null;
  }

  TextContent _parseTextContent(
    MessageRecord row,
    List<MessageAttachmentRecord> attachments,
  ) {
    // Only TTS attachments are rendered as the bubble's voice reply. A user
    // text message that happens to carry an audio attachment is treated as
    // text-only here; the audio surface (if any) is its own bubble.
    final voiceAttachment = attachments
        .where(
          (attachment) =>
              attachment.contentType == ContentWire.audio &&
              _attachmentSource(attachment) == _attachmentSourceCharacterTts,
        )
        .firstOrNull;
    return TextContent(
      row.body,
      voiceReply: voiceAttachment != null
          ? _audioAttachmentFromRecord(voiceAttachment)
          : null,
    );
  }

  AudioContent _parseAudioContent(
    MessageRecord row,
    List<MessageAttachmentRecord> attachments,
  ) {
    final audioAttachments = attachments
        .where((attachment) => attachment.contentType == ContentWire.audio)
        .toList();
    if (audioAttachments.length > 1) {
      // Multi-audio messages aren't produced today (§1.2) but the schema
      // supports them; surface a log so we don't silently drop slots when a
      // future producer starts emitting them.
      _log.warning(
        'Audio message has multiple attachments — only slot 0 is rendered',
        fields: {'msg_id': row.id, 'slot_count': audioAttachments.length},
      );
    }
    final audioAttachment = audioAttachments.firstOrNull;
    return AudioContent(
      audio: audioAttachment != null
          ? _audioAttachmentFromRecord(audioAttachment)
          : const AudioAttachment(durationMs: 0),
      transcript: row.transcript,
    );
  }
}

@Riverpod(keepAlive: true)
MessageRepository messageRepository(Ref ref) {
  final db = ref.watch(appDatabaseProvider);
  final gatewayNotifier = ref.read(gatewayProvider.notifier);
  final audioStorage = ref.read(audioStorageProvider);

  final repo = MessageRepositoryImpl(
    messagesDao: db.messagesDao,
    channelsDao: db.channelsDao,
    attachmentsDao: db.messageAttachmentsDao,
    frameStream: gatewayNotifier.frameStream,
    audioStorage: audioStorage,
  );

  ref.onDispose(repo.dispose);
  return repo;
}
