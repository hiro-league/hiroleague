import 'audio_attachment.dart';
import 'message_type.dart';

/// Sealed hierarchy of message content variants.
/// Extend with new subclasses when new media types are added (no backward compat required).
sealed class MessageContent {
  const MessageContent();

  MessageType get type;
}

final class TextContent extends MessageContent {
  const TextContent(this.text, {this.voiceReply});

  final String text;

  /// Voice reply attached after receiving a message.voiced event from the server.
  final AudioAttachment? voiceReply;

  bool get hasVoice => voiceReply != null;

  @override
  MessageType get type => MessageType.text;
}

final class AudioContent extends MessageContent {
  const AudioContent({
    required this.audio,
    this.transcript,
  });

  /// Audio data (duration, local path, MIME type).
  final AudioAttachment audio;

  /// Transcript set after receiving a message.transcribed event from the server.
  final String? transcript;

  @override
  MessageType get type => MessageType.voice;
}

/// Placeholder for unsupported content received from older/different clients.
final class UnsupportedContent extends MessageContent {
  const UnsupportedContent(this.rawType);

  final String rawType;

  @override
  MessageType get type => MessageType.text;
}
