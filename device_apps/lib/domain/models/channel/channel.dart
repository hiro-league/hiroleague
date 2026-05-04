import 'package:freezed_annotation/freezed_annotation.dart';

import '../server_info/server_info.dart';

part 'channel.freezed.dart';

@freezed
abstract class Channel with _$Channel {
  const factory Channel({
    required String id,
    required String name,
    DateTime? lastMessageAt,
    int? serverId,
    String? characterId,
    String? characterName,
    MediaCapabilities? capabilities,
  }) = _Channel;
}
