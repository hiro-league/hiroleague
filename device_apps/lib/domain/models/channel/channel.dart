import 'package:freezed_annotation/freezed_annotation.dart';

part 'channel.freezed.dart';

@freezed
abstract class Channel with _$Channel {
  const factory Channel({
    required String id,
    required String name,
    DateTime? lastMessageAt,
  }) = _Channel;
}
