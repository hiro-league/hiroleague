import '../models/channel/channel.dart';

abstract class ChannelRepository {
  Stream<List<Channel>> watchChannels();

  /// Insert a channel row. Local-only channels ([Channel.serverId] null) default
  /// [appliedServerLastDeleted] to ``0``. Server-backed channels **must** pass
  /// the current server ``last_deleted`` so a later [syncFromServer] does not
  /// treat the row as needing a bulk-clear wipe.
  Future<void> insertChannel(
    Channel channel, {
    int? appliedServerLastDeleted,
  });

  /// Sync local channel DB from server-provided channel list.
  ///
  /// When [serverChannels] reports a higher ``last_deleted`` than the local
  /// reconciled epoch for a channel, drops that channel's local message mirror
  /// and history watermark (Phase 2 bulk clear).
  ///
  /// Returns ``true`` when at least one channel had a mirror reset (caller may
  /// want to rerun message history sync).
  Future<bool> syncFromServer(List<Map<String, dynamic>> serverChannels);
}
