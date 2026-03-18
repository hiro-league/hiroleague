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

final class AudioContent extends MessageContent {
  const AudioContent({
    required this.durationMs,
    this.localPath,
    this.transcript,
    this.mimeType = 'audio/m4a',
  });

  /// Duration of the audio recording in milliseconds.
  final int durationMs;

  /// Platform-specific playback source: file path on mobile, blob URL on web.
  /// Null for inbound messages still being saved.
  final String? localPath;

  /// Transcript set after receiving a message.transcribed event from the server.
  final String? transcript;

  final String mimeType;

  AudioContent copyWithTranscript(String transcript) => AudioContent(
        durationMs: durationMs,
        localPath: localPath,
        transcript: transcript,
        mimeType: mimeType,
      );

  AudioContent copyWithLocalPath(String localPath) => AudioContent(
        durationMs: durationMs,
        localPath: localPath,
        transcript: transcript,
        mimeType: mimeType,
      );

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
