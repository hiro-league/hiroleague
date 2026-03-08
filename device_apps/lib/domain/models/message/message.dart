import 'package:freezed_annotation/freezed_annotation.dart';

import 'message_content.dart';
import 'message_status.dart';

part 'message.freezed.dart';

@freezed
class Message with _$Message {
  const factory Message({
    required String id,
    required String channelId,
    required String senderId,
    required MessageContent content,
    required DateTime timestamp,
    @Default(MessageStatus.sent) MessageStatus status,
    @Default(false) bool isOutbound,
  }) = _Message;
}
