import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../application/channels/channels_notifier.dart';
import '../../application/gateway/gateway_notifier.dart';
import '../../application/gateway/gateway_state.dart';
import '../../core/constants/app_strings.dart';
import '../../domain/models/channel/channel.dart';

class ChannelListScreen extends ConsumerStatefulWidget {
  const ChannelListScreen({super.key});

  @override
  ConsumerState<ChannelListScreen> createState() => _ChannelListScreenState();
}

class _ChannelListScreenState extends ConsumerState<ChannelListScreen> {
  @override
  void initState() {
    super.initState();
    // Stale-while-revalidate: reopening this shell after sleep may miss hints;
    // timed pulls complement `resource.changed` + connect-time syncAll.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(gatewayProvider.notifier).revalidateResourcesIfStale(
            const ['channels', 'policy'],
          );
    });
  }

  @override
  Widget build(BuildContext context) {
    final gateway = ref.watch(gatewayProvider);
    final channelsAsync = ref.watch(channelsProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text(AppStrings.navChannels),
        actions: [_GatewayStatusChip(gateway: gateway)],
      ),
      body: channelsAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(
          child: Text(
            'Failed to load channels',
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
        ),
        data: (channels) {
          if (channels.isEmpty) {
            return const Center(child: CircularProgressIndicator());
          }
          if (channels.length == 1) {
            WidgetsBinding.instance.addPostFrameCallback((_) {
              context.go('/app/channels/${channels.first.id}');
            });
            return const Center(child: CircularProgressIndicator());
          }
          return ListView.separated(
            itemCount: channels.length,
            separatorBuilder: (_, _) => const Divider(height: 1),
            itemBuilder: (context, index) =>
                _ChannelTile(channel: channels[index]),
          );
        },
      ),
    );
  }
}

class _ChannelTile extends StatelessWidget {
  const _ChannelTile({required this.channel});

  final Channel channel;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    return ListTile(
      leading: CircleAvatar(
        backgroundColor: cs.primaryContainer,
        foregroundColor: cs.onPrimaryContainer,
        child: Text(
          channel.name.isNotEmpty ? channel.name[0].toUpperCase() : '#',
        ),
      ),
      title: Text(channel.name),
      trailing: const Icon(Icons.chevron_right_rounded),
      onTap: () => context.push('/app/channels/${channel.id}'),
    );
  }
}

class _GatewayStatusChip extends StatelessWidget {
  const _GatewayStatusChip({required this.gateway});

  final GatewayState gateway;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final label = gateway.map(
      disconnected: (_) => 'Offline',
      connecting: (_) => 'Connecting…',
      connected: (c) => 'Online · ${c.deviceId}',
      error: (e) => 'Error · ${e.message}',
    );

    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: Chip(
        label: Text(label, style: const TextStyle(fontSize: 11)),
        visualDensity: VisualDensity.compact,
        backgroundColor: colorScheme.surfaceContainerHighest,
      ),
    );
  }
}
