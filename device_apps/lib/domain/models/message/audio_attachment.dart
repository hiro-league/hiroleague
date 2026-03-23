import 'package:freezed_annotation/freezed_annotation.dart';

part 'audio_attachment.freezed.dart';

/// Shared value object for audio data attached to any message type.
///
/// Used by [AudioContent] for user voice recordings and by [TextContent]
/// for bot voice replies (message.voiced enrichment). One definition,
/// zero duplication across the two content types.
@freezed
abstract class AudioAttachment with _$AudioAttachment {
  const AudioAttachment._();

  const factory AudioAttachment({
    required int durationMs,
    String? localPath,
    @Default('audio/m4a') String mimeType,
  }) = _AudioAttachment;

  bool get isPlayable => localPath != null && localPath!.isNotEmpty;
}
