import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../data/repositories/channel_repository_impl.dart';
import '../../domain/models/channel/channel.dart';

part 'channels_notifier.g.dart';

/// Emits the live list of channels from the local DB.
/// On first build, seeds the default "General" channel if the DB is empty.
@riverpod
// ignore: deprecated_member_use_from_same_package
Stream<List<Channel>> channels(Ref ref) async* {
  final repo = ref.watch(channelRepositoryProvider);
  await repo.ensureDefaultChannel();
  yield* repo.watchChannels();
}
