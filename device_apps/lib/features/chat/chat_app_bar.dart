import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../application/providers.dart';
import '../../application/sync/character_photo_notifier.dart';
import '../../core/constants/app_strings.dart';
import '../../core/constants/route_names.dart';

class ChatAppBar extends ConsumerWidget implements PreferredSizeWidget {
  const ChatAppBar({super.key, required this.channelId});

  final String channelId;

  /// Taller bar so channel title + character row fit beside the avatar.
  static const double _toolbarHeight = 72;

  @override
  Size get preferredSize => const Size.fromHeight(_toolbarHeight);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final channelsAsync = ref.watch(channelsProvider);
    final gatewayState = ref.watch(gatewayProvider);

    final channel = channelsAsync.whenOrNull(
      data: (list) => list.firstWhere(
        (c) => c.id == channelId,
        orElse: () => list.first,
      ),
    );
    final channelName = channel?.name ?? 'Chat';
    final characterLabel = (channel?.characterName?.trim().isNotEmpty ?? false)
        ? channel!.characterName!.trim()
        : AppStrings.chatCharacterFallback;
    final photoMap = ref.watch(characterPhotoMapProvider);
    final cid = channel?.characterId;
    final photoBytes = cid != null ? photoMap[cid] : null;

    final voiceReplyEnabled = ref.watch(
      channelVoiceReplyEnabledProvider(channelId),
    );
    final channelCapabilities =
        ref.watch(channelCapabilitiesProvider(channelId));
    final voiceRepliesAvailable =
        channelCapabilities?.output.voice ?? true;

    final cs = Theme.of(context).colorScheme;
    final (dotColor, connectionTooltip) = _connectionIndicator(gatewayState);

    return AppBar(
      toolbarHeight: _toolbarHeight,
      title: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Expanded(
            child: Material(
              color: Colors.transparent,
              child: InkWell(
                // Tap opens channel summary; Material gives a proper ink splash on the title.
                borderRadius: BorderRadius.circular(12),
                onTap: () =>
                    context.push(RouteNames.chatChannelInfo(channelId)),
                child: Padding(
                  padding:
                      const EdgeInsets.only(top: 4, bottom: 4, right: 8),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.center,
                    children: [
                      CircleAvatar(
                        radius: 18,
                        backgroundColor: cs.primaryContainer,
                        foregroundColor: cs.onPrimaryContainer,
                        backgroundImage: photoBytes != null
                            ? MemoryImage(photoBytes)
                            : null,
                        child: photoBytes == null
                            ? Text(
                                channelName.isNotEmpty
                                    ? channelName[0].toUpperCase()
                                    : '#',
                                style: Theme.of(context)
                                    .textTheme
                                    .titleMedium
                                    ?.copyWith(
                                      color: cs.onPrimaryContainer,
                                    ),
                              )
                            : null,
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Text(
                              channelName,
                              style: Theme.of(context).textTheme.titleMedium,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                            const SizedBox(height: 2),
                            LayoutBuilder(
                              builder: (context, constraints) {
                                const gap = 8.0;
                                const dotSize = 10.0;
                                const replyIconSize = 16.0;
                                const replyLeadingGap = 4.0;
                                final replyIconSlot =
                                    replyIconSize + replyLeadingGap;
                                final maxLabelWidth =
                                    (constraints.maxWidth -
                                            gap -
                                            dotSize -
                                            replyIconSlot)
                                        .clamp(0.0, double.infinity);
                                final showVoiceHint =
                                    voiceRepliesAvailable && voiceReplyEnabled;
                                final replyIconColor = !voiceRepliesAvailable
                                    ? cs.onSurface.withValues(alpha: 0.45)
                                    : (voiceReplyEnabled
                                          ? cs.primary
                                          : cs.onSurfaceVariant);
                                final replyTooltip =
                                    !voiceRepliesAvailable
                                        ? AppStrings.voiceRepliesUnavailable
                                        : (showVoiceHint
                                              ? AppStrings.voiceRepliesTitle
                                              : AppStrings
                                                  .textRepliesModeTooltip);

                                return Row(
                                  mainAxisSize: MainAxisSize.min,
                                  crossAxisAlignment: CrossAxisAlignment.center,
                                  children: [
                                    Tooltip(
                                      message: replyTooltip,
                                      child: Icon(
                                        showVoiceHint
                                            ? Icons
                                                  .record_voice_over_rounded
                                            : Icons.text_fields_rounded,
                                        size: replyIconSize,
                                        color: replyIconColor,
                                      ),
                                    ),
                                    SizedBox(width: replyLeadingGap),
                                    ConstrainedBox(
                                      constraints: BoxConstraints(
                                        maxWidth: maxLabelWidth,
                                      ),
                                      child: Text(
                                        characterLabel,
                                        style: Theme.of(context)
                                            .textTheme
                                            .labelMedium
                                            ?.copyWith(
                                              color: cs.onSurfaceVariant,
                                            ),
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis,
                                      ),
                                    ),
                                    const SizedBox(width: gap),
                                    Tooltip(
                                      message: connectionTooltip,
                                      child: Container(
                                        width: dotSize,
                                        height: dotSize,
                                        decoration: BoxDecoration(
                                          color: dotColor,
                                          shape: BoxShape.circle,
                                        ),
                                      ),
                                    ),
                                  ],
                                );
                              },
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
      actions: [
        IconButton(
          tooltip: AppStrings.chatChannelSettingsTitle,
          onPressed: () => context.push(
            RouteNames.chatChannelSettings(channelId),
          ),
          icon: const Icon(Icons.settings_rounded),
        ),
      ],
    );
  }
}

/// Maps gateway lifecycle to header dot color (green / blue / red) and tooltip.
(Color, String) _connectionIndicator(GatewayState state) {
  return state.when(
    disconnected: () => (
      Colors.red,
      AppStrings.gatewayDisconnected,
    ),
    connecting: () => (
      Colors.blue,
      AppStrings.gatewayConnecting,
    ),
    connected: (_) => (
      Colors.green,
      AppStrings.gatewayConnected,
    ),
    error: (msg) => (
      Colors.red,
      msg,
    ),
  );
}
