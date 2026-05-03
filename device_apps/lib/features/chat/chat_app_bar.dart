import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/providers.dart';
import '../../core/constants/app_strings.dart';

class ChatAppBar extends ConsumerWidget implements PreferredSizeWidget {
  const ChatAppBar({super.key, required this.channelId});

  final String channelId;

  @override
  Size get preferredSize => const Size.fromHeight(kToolbarHeight);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final channelsAsync = ref.watch(channelsProvider);
    final gatewayState = ref.watch(gatewayProvider);
    final channelCapabilities = ref.watch(channelCapabilitiesProvider(channelId));
    final voiceReplyEnabled = ref.watch(
      channelVoiceReplyEnabledProvider(channelId),
    );

    final channelName = channelsAsync.whenOrNull(
          data: (list) =>
              list.firstWhere(
                (c) => c.id == channelId,
                orElse: () => list.first,
              ).name,
        ) ??
        'Chat';
    final voiceRepliesAvailable = channelCapabilities?.output.voice ?? true;
    final iconColor = voiceRepliesAvailable
        ? (voiceReplyEnabled
              ? Theme.of(context).colorScheme.primary
              : Theme.of(context).colorScheme.onSurfaceVariant)
        : Theme.of(context).colorScheme.onSurface.withValues(alpha: 0.45);

    return AppBar(
      title: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(channelName),
          _ConnectionSubtitle(state: gatewayState),
        ],
      ),
      actions: [
        IconButton(
          tooltip: AppStrings.voiceRepliesTitle,
          onPressed: () async {
            if (!voiceRepliesAvailable) {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text(AppStrings.voiceRepliesUnavailable),
                  behavior: SnackBarBehavior.floating,
                ),
              );
              return;
            }
            final next = !voiceReplyEnabled;
            await ref
                .read(voiceReplyPreferenceProvider.notifier)
                .setVoiceReplyEnabled(channelId, next);
            if (!context.mounted) return;
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text(
                  next
                      ? AppStrings.voiceRepliesEnabledForChannel
                      : AppStrings.voiceRepliesDisabledForChannel,
                ),
                behavior: SnackBarBehavior.floating,
              ),
            );
          },
          icon: Icon(
            voiceReplyEnabled
                ? Icons.record_voice_over_rounded
                : Icons.text_fields_rounded,
            color: iconColor,
          ),
        ),
      ],
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
