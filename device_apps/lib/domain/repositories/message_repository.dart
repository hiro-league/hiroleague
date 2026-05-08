import '../models/message/message.dart';
import '../models/message/message_status.dart';

abstract class MessageRepository {
  /// Live stream of messages for [channelId], ordered oldest→newest.
  Stream<List<Message>> watchMessages(String channelId);

  Future<void> insertOutbound({
    required String id,
    required String channelId,
    required String senderId,
    required String contentType,
    required String body,
    required DateTime timestamp,
    String? metadata,
  });

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
  });

  Future<void> updateMessageStatus(String messageId, MessageStatus status);

  void dispose();
}
