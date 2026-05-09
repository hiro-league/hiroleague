import 'dart:convert';

import 'package:riverpod_annotation/riverpod_annotation.dart';
import 'package:uuid/uuid.dart';

import '../../application/auth/auth_notifier.dart';
import '../../application/auth/auth_state.dart';
import '../../application/gateway/gateway_notifier.dart';
import '../../application/policy/policy_notifier.dart';
import '../../core/constants/app_constants.dart';
import '../../core/errors/app_exception.dart';
import '../../core/utils/blob_id.dart';
import '../../core/utils/logger.dart';
import '../../data/remote/gateway/gateway_contract.dart';
import '../../data/remote/gateway/unified_message.dart';
import '../../data/repositories/message_repository_impl.dart';
import '../../domain/models/message/message_status.dart';
import '../../domain/services/audio_recording_service.dart';
import '../../platform/storage/audio_storage_service.dart';

part 'message_send_notifier.g.dart';

// keepAlive: action service with no reactive state — must not be auto-disposed
// mid-send since sendText() crosses async gaps and uses ref after awaits.
@Riverpod(keepAlive: true)
class MessageSendNotifier extends _$MessageSendNotifier {
  static const _uuid = Uuid();
  static final _log = Logger.get('MessageSendNotifier');

  @override
  void build() {}

  /// Sends a text message to [channelId].
  ///
  /// Writes optimistically to the DB with [MessageStatus.sending], broadcasts
  /// via the gateway, then updates the status to [MessageStatus.sent].
  /// Throws [AppException] on failure so the caller (UI) can surface the error.
  Future<void> sendText({
    required String channelId,
    required String text,
  }) async {
    final authState = ref.read(authProvider).value;
    if (authState is! AuthAuthenticated) return;

    final identity = authState.identity;
    final messageId = _uuid.v4();
    final now = DateTime.now().toUtc();

    // Capture all refs before the first await — ref must not be read after an
    // async gap in case the provider is rebuilt between awaits (Riverpod v3).
    final repo = ref.read(messageRepositoryProvider);
    final gateway = ref.read(gatewayProvider.notifier);
    final requestVoiceReply = ref.read(
      channelVoiceReplyEnabledProvider(channelId),
    );

    try {
      await repo.insertOutbound(
        id: messageId,
        channelId: channelId,
        senderId: identity.deviceId,
        contentType: ContentWire.text,
        body: text,
        timestamp: now,
      );

      // Build the outbound UnifiedMessage using the typed model so that
      // toJson() is the single authoritative serialization path. If the schema
      // changes, only UnifiedMessage.toJson() needs updating — this call site
      // will fail at compile time if required fields are removed or renamed.
      gateway.send(
        UnifiedMessage(
          routing: MessageRouting(
            id: messageId,
            channel: AppConstants.gatewayChannelName,
            direction: UnifiedMessageWire.directionOutbound,
            senderId: identity.deviceId,
            timestamp: now.toIso8601String(),
            metadata: {
              MetadataWire.channelId: channelId,
              if (requestVoiceReply) MetadataWire.requestVoiceReply: true,
            },
          ),
          content: [ContentItem(contentType: ContentWire.text, body: text)],
        ).toJson(),
      );

      // Optimistic — we don't wait for a server delivery receipt.
      await repo.updateMessageStatus(messageId, MessageStatus.sent);
    } on AppException {
      _log.error('Failed to send message — DB or storage error');
      rethrow;
    } catch (e) {
      _log.error('Failed to send message (unexpected)', error: e);
      throw UnknownException(e.toString());
    }
  }

  /// Records an audio message, persists locally, and sends to the server.
  ///
  /// Inserts an optimistic DB row with [MessageStatus.sending], broadcasts the
  /// audio as a base64-encoded [ContentItem] via the gateway, then updates the
  /// status to [MessageStatus.sent]. Throws [AppException] on failure.
  Future<void> sendAudio({
    required String channelId,
    required AudioRecordingResult recordingResult,
  }) async {
    final authState = ref.read(authProvider).value;
    if (authState is! AuthAuthenticated) return;

    final identity = authState.identity;
    final messageId = _uuid.v4();
    final now = DateTime.now().toUtc();

    final repo = ref.read(messageRepositoryProvider);
    final gateway = ref.read(gatewayProvider.notifier);
    // Captured before first await — ref must not be read across async gaps.
    final audioStorage = ref.read(audioStorageProvider);
    final voiceInputAllowed =
        ref.read(channelCapabilitiesProvider(channelId))?.input.voice ?? true;
    final requestVoiceReply = ref.read(
      channelVoiceReplyEnabledProvider(channelId),
    );

    try {
      if (!voiceInputAllowed) {
        throw const UnknownException(
          'Voice messages are unavailable for this chat.',
        );
      }
      // 1. Resolve the byte payload. On web the recorder may only give us a
      // blob URL, so save/load that source before publishing the blob cache row.
      var bytes = recordingResult.bytes;
      if (bytes.isEmpty) {
        final sourcePath = await audioStorage.save(
          messageId: messageId,
          bytes: bytes,
          tempPath: recordingResult.tempPath,
          blobUrl: recordingResult.tempPath,
        );
        bytes = (await audioStorage.loadBytes(sourcePath)) ?? bytes;
      }
      if (bytes.isEmpty) {
        throw const UnknownException('Recorded audio was empty.');
      }

      final blobId = blobIdForBytes(bytes);
      final chunkSize = defaultBlobChunkSize;
      final chunkCount = blobChunkCountForSize(bytes.length, chunkSize);
      const slotIndex = 0;
      final localPath = await audioStorage.saveBytes(
        messageId: attachmentStorageId(messageId, slotIndex),
        bytes: bytes,
        mimeType: recordingResult.mimeType,
      );
      final base64Body = base64Encode(bytes);

      // 2. Build metadata JSON stored in the DB. Playback comes from the
      // attachment row; metadata is retained only for non-playback details.
      final metadataJson = jsonEncode({
        'duration_ms': recordingResult.durationMs,
        'mime_type': recordingResult.mimeType,
      });

      // 3. Insert optimistic row and its ready local attachment.
      await repo.insertOutbound(
        id: messageId,
        channelId: channelId,
        senderId: identity.deviceId,
        contentType: ContentWire.audio,
        body: '',
        metadata: metadataJson,
        timestamp: now,
      );
      await repo.upsertLocalAudioAttachment(
        messageId: messageId,
        localPath: localPath,
        blobId: blobId,
        mimeType: recordingResult.mimeType,
        size: bytes.length,
        durationMs: recordingResult.durationMs,
        chunkSize: chunkSize,
        chunkCount: chunkCount,
      );

      // 4. Send over WebSocket.
      gateway.send(
        UnifiedMessage(
          routing: MessageRouting(
            id: messageId,
            channel: AppConstants.gatewayChannelName,
            direction: UnifiedMessageWire.directionOutbound,
            senderId: identity.deviceId,
            timestamp: now.toIso8601String(),
            metadata: {
              MetadataWire.channelId: channelId,
              if (requestVoiceReply) MetadataWire.requestVoiceReply: true,
            },
          ),
          content: [
            ContentItem(
              contentType: ContentWire.audio,
              body: base64Body,
              metadata: {
                'duration_ms': recordingResult.durationMs,
                'mime_type': recordingResult.mimeType,
                'blob_id': blobId,
                'size': bytes.length,
                'chunk_size': chunkSize,
                'chunk_count': chunkCount,
              },
            ),
          ],
        ).toJson(),
      );

      // 5. Mark as sent (single gray check).
      await repo.updateMessageStatus(messageId, MessageStatus.sent);
    } on AppException {
      _log.error('Failed to send audio — DB or storage error');
      rethrow;
    } catch (e) {
      _log.error('Failed to send audio (unexpected)', error: e);
      throw UnknownException(e.toString());
    }
  }
}
