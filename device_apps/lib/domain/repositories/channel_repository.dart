import '../models/channel/channel.dart';

abstract class ChannelRepository {
  Stream<List<Channel>> watchChannels();

  Future<void> insertChannel(Channel channel);

  /// Creates the default "General" channel if no channels exist yet.
  Future<void> ensureDefaultChannel();
}
