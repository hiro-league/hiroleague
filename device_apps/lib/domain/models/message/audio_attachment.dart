import 'package:freezed_annotation/freezed_annotation.dart';

part 'audio_attachment.freezed.dart';

enum AttachmentFetchStatus {
  pending,
  fetching,
  ready,
  failed;

  /// Resolve a stored fetch-status string. Defaults to ``failed`` for unknown
  /// values so a corrupted or future-versioned row never silently appears
  /// playable in the UI — better to render the retry affordance than to
  /// pretend the bytes are on disk.
  static AttachmentFetchStatus fromName(String? name) {
    for (final value in values) {
      if (value.name == name) return value;
    }
    return failed;
  }
}

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
    String? blobId,
    String? remoteRef,
    int? size,
    int? chunkSize,
    int? chunkCount,
    @Default(AttachmentFetchStatus.ready) AttachmentFetchStatus fetchStatus,
  }) = _AudioAttachment;

  bool get isPlayable =>
      fetchStatus == AttachmentFetchStatus.ready &&
      localPath != null &&
      localPath!.isNotEmpty;
}
