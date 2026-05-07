import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/providers.dart';
import '../../core/constants/app_strings.dart';

/// Per-channel options moved out of the chat app bar (gear menu).
class ChatChannelSettingsScreen extends ConsumerWidget {
  const ChatChannelSettingsScreen({super.key, required this.channelId});

  final String channelId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final voiceReplyEnabled = ref.watch(
      channelVoiceReplyEnabledProvider(channelId),
    );
    final channelCapabilities =
        ref.watch(channelCapabilitiesProvider(channelId));
    final voiceRepliesAvailable =
        channelCapabilities?.output.voice ?? true;

    return Scaffold(
      appBar: AppBar(title: const Text(AppStrings.chatChannelSettingsTitle)),
      body: ListView(
        children: [
          SwitchListTile(
            secondary: Icon(
              voiceReplyEnabled
                  ? Icons.record_voice_over_rounded
                  : Icons.text_fields_rounded,
              color: voiceRepliesAvailable
                  ? null
                  : Theme.of(context).colorScheme.onSurface.withValues(
                        alpha: 0.45,
                      ),
            ),
            title: const Text(AppStrings.voiceRepliesTitle),
            subtitle: const Text(AppStrings.voiceRepliesSubtitle),
            value: voiceReplyEnabled,
            // No SnackBars: toggling replies must not cover the chat composer area.
            onChanged: voiceRepliesAvailable
                ? (next) async {
                    await ref
                        .read(voiceReplyPreferenceProvider.notifier)
                        .setVoiceReplyEnabled(channelId, next);
                  }
                : null,
          ),
          const Divider(height: 1),
          // Reload conversations — hook up when sync/reload flow exists (no-op for now).
          ListTile(
            enabled: false,
            leading: const Icon(Icons.refresh_rounded),
            title: const Text(AppStrings.reloadConversationsTitle),
          ),
        ],
      ),
    );
  }
}
