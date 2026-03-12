import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/providers.dart';

class ChatAppBar extends ConsumerWidget implements PreferredSizeWidget {
  const ChatAppBar({super.key, required this.channelId});

  final String channelId;

  @override
  Size get preferredSize => const Size.fromHeight(kToolbarHeight);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final channelsAsync = ref.watch(channelsProvider);
    final gatewayState = ref.watch(gatewayProvider);

    final channelName = channelsAsync.whenOrNull(
          data: (list) =>
              list.firstWhere(
                (c) => c.id == channelId,
                orElse: () => list.first,
              ).name,
        ) ??
        'Chat';

    return AppBar(
      title: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(channelName),
          _ConnectionSubtitle(state: gatewayState),
        ],
      ),
    );
  }
}

class _ConnectionSubtitle extends StatelessWidget {
  const _ConnectionSubtitle({required this.state});

  final GatewayState state;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    final label = state.when(
      disconnected: () => 'Disconnected',
      connecting: () => 'Connecting…',
      connected: (_) => 'Connected',
      error: (msg) => msg,
    );
    final color = state.when(
      disconnected: () => cs.error,
      connecting: () => cs.onSurfaceVariant,
      connected: (_) => Colors.green,
      error: (_) => cs.error,
    );

    return Text(
      label,
      style: Theme.of(context).textTheme.labelSmall?.copyWith(color: color),
    );
  }
}
