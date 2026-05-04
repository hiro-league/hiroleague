import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../data/repositories/channel_repository_impl.dart';
import '../../domain/models/channel/channel.dart';

part 'channels_notifier.g.dart';

/// Emits the live list of channels from the local DB.
/// Channel rows sync from ``channels.list`` via [GatewayNotifier]
/// (`resource.changed` hints + connect-time pull).
@riverpod
// ignore: deprecated_member_use_from_same_package
Stream<List<Channel>> channels(Ref ref) async* {
  final repo = ref.watch(channelRepositoryProvider);
  yield* repo.watchChannels();
}
