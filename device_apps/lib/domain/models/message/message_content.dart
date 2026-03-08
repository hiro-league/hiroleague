import 'message_type.dart';

/// Sealed hierarchy of message content variants.
/// Extend with new subclasses when new media types are added (no backward compat required).
sealed class MessageContent {
  const MessageContent();

  MessageType get type;
}

final class TextContent extends MessageContent {
  const TextContent(this.text);

  final String text;

  @override
  MessageType get type => MessageType.text;
}

/// Placeholder for unsupported content received from older/different clients.
final class UnsupportedContent extends MessageContent {
  const UnsupportedContent(this.rawType);

  final String rawType;

  @override
  MessageType get type => MessageType.text;
}
