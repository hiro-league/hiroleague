import '../models/channel/channel.dart';

abstract class ChannelRepository {
  Stream<List<Channel>> watchChannels();

  Future<void> insertChannel(Channel channel);

  /// Sync local channel DB from server-provided channel list.
  Future<void> syncFromServer(List<Map<String, dynamic>> serverChannels);
}
