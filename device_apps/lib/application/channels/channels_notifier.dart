import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../core/utils/logger.dart';
import '../../data/repositories/channel_repository_impl.dart';
import '../../domain/models/channel/channel.dart';
import '../gateway/gateway_notifier.dart';
import '../gateway/gateway_state.dart';

part 'channels_notifier.g.dart';

final _log = Logger.get('ChannelsNotifier');

/// Emits the live list of channels from the local DB.
/// On first connect, syncs channels from the server.
@riverpod
// ignore: deprecated_member_use_from_same_package
Stream<List<Channel>> channels(Ref ref) async* {
  final repo = ref.watch(channelRepositoryProvider);

  // Sync channels from server when gateway connects
  final gateway = ref.watch(gatewayProvider);
  if (gateway is GatewayConnected) {
    final client = ref.read(gatewayProvider.notifier).requestClient;
    if (client != null) {
      try {
        final response = await client.request('channels.list');
        final data = response['data'] as Map<String, dynamic>?;
        final channels = (data?['channels'] as List?)?.cast<Map<String, dynamic>>() ?? [];
        await repo.syncFromServer(channels);
        _log.info('Synced channels from server', fields: {'count': channels.length});
      } catch (e) {
        _log.warning('Failed to sync channels from server', fields: {'error': e.toString()});
      }
    }
  }

  yield* repo.watchChannels();
}
