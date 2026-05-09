import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/providers.dart';
import '../../application/sync/resource_sync_bootstrap.dart';
import '../../core/constants/app_strings.dart';

/// Per-channel options moved out of the chat app bar (gear menu).
class ChatChannelSettingsScreen extends ConsumerStatefulWidget {
  const ChatChannelSettingsScreen({super.key, required this.channelId});

  final String channelId;

  @override
  ConsumerState<ChatChannelSettingsScreen> createState() =>
      _ChatChannelSettingsScreenState();
}

class _ChatChannelSettingsScreenState
    extends ConsumerState<ChatChannelSettingsScreen> {
  bool _clearBusy = false;

  Future<void> _confirmAndClearMessages() async {
    if (_clearBusy) return;

    final gatewayState = ref.read(gatewayProvider);
    if (gatewayState is! GatewayConnected) {
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(
        const SnackBar(content: Text(AppStrings.clearChannelMessagesDisconnected)),
      );
      return;
    }

    final client = ref.read(gatewayProvider.notifier).requestClient;
    if (client == null) {
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(
        const SnackBar(content: Text(AppStrings.clearChannelMessagesDisconnected)),
      );
      return;
    }

    final channel = ref.read(channelsProvider).whenOrNull(
      data: (list) {
        for (final c in list) {
          if (c.id == widget.channelId) return c;
        }
        return null;
      },
    );
    final serverId = channel?.serverId;
    if (serverId == null) {
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(
        const SnackBar(content: Text(AppStrings.clearChannelMessagesNoServerId)),
      );
      return;
    }

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text(AppStrings.clearChannelMessagesConfirmTitle),
        content: const Text(AppStrings.clearChannelMessagesConfirmBody),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text(AppStrings.cancel),
          ),
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            style: TextButton.styleFrom(foregroundColor: Theme.of(ctx).colorScheme.error),
            child: const Text(AppStrings.clearChannelMessagesConfirmAction),
          ),
        ],
      ),
    );
    if (!context.mounted || confirmed != true) return;

    setState(() => _clearBusy = true);
    try {
      final raw = await client.request(
        'channels.clear_messages',
        params: {'channel_id': serverId},
        timeout: const Duration(seconds: 30),
        idempotent: false,
      );
      final status = raw['status'];
      if (status != 'ok') {
        final err = raw['error'];
        final msg = err is Map
            ? (err['message']?.toString() ?? err.toString())
            : err?.toString();
        throw FormatException(msg ?? 'channels.clear_messages failed');
      }
      await refreshChannelsWidgetRef(ref, client);
      await ref
          .read(gatewayProvider.notifier)
          .revalidateMessageHistoryForChannel(widget.channelId, force: true);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text(AppStrings.clearChannelMessagesSuccess)),
      );
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('${AppStrings.clearChannelMessagesFailed}: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _clearBusy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final voiceReplyEnabled = ref.watch(
      channelVoiceReplyEnabledProvider(widget.channelId),
    );
    final channelCapabilities = ref.watch(
      channelCapabilitiesProvider(widget.channelId),
    );
    final voiceRepliesAvailable = channelCapabilities?.output.voice ?? true;

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
                        .setVoiceReplyEnabled(widget.channelId, next);
                  }
                : null,
          ),
          const Divider(height: 1),
          ListTile(
            enabled:
                !_clearBusy &&
                ref.watch(gatewayProvider) is GatewayConnected,
            leading: _clearBusy
                ? SizedBox(
                    width: 24,
                    height: 24,
                    child: CircularProgressIndicator.adaptive(strokeWidth: 2),
                  )
                : const Icon(Icons.delete_sweep_rounded),
            title: const Text(AppStrings.clearChannelMessagesTitle),
            subtitle: const Text(AppStrings.clearChannelMessagesSubtitle),
            onTap: _confirmAndClearMessages,
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
