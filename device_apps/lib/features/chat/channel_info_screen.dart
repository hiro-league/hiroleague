import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/providers.dart';
import '../../application/sync/character_photo_notifier.dart';
import '../../core/constants/app_strings.dart';
import '../../domain/models/channel/channel.dart';
import '../../domain/models/server_info/server_info.dart';

/// Summary for a channel: photos, names, description, capabilities, and IDs.
class ChannelInfoScreen extends ConsumerWidget {
  const ChannelInfoScreen({super.key, required this.channelId});

  final String channelId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final channelsAsync = ref.watch(channelsProvider);
    final photoMap = ref.watch(characterPhotoMapProvider);

    return Scaffold(
      appBar: AppBar(title: const Text(AppStrings.channelInfoTitle)),
      body: channelsAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (_, _) => Center(
          child: Text(
            AppStrings.errorGeneric,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
        ),
        data: (channels) {
          Channel? channel;
          for (final c in channels) {
            if (c.id == channelId) {
              channel = c;
              break;
            }
          }
          if (channel == null) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Text(
                  AppStrings.channelNotFoundBody,
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.bodyLarge,
                ),
              ),
            );
          }

          final cid = channel.characterId;
          final characterBytes = cid != null ? photoMap[cid] : null;
          final characterTitle =
              (channel.characterName?.trim().isNotEmpty ?? false)
                  ? channel.characterName!.trim()
                  : AppStrings.chatCharacterFallback;
          final caps = channel.capabilities ?? const MediaCapabilities.defaults();

          return SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: _PhotoCaptionCard(
                        caption: AppStrings.channelPhotoCaption,
                        avatar: _channelPlaceholderAvatar(
                          context,
                          channel.name,
                        ),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: _PhotoCaptionCard(
                        caption: AppStrings.characterPhotoCaption,
                        avatar: _characterAvatar(
                          context,
                          characterTitle,
                          characterBytes,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 24),
                Text(
                  channel.name,
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 4),
                Text(
                  characterTitle,
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                ),
                const SizedBox(height: 20),
                Text(
                  AppStrings.descriptionHeading,
                  style: Theme.of(context).textTheme.titleSmall,
                ),
                const SizedBox(height: 8),
                Text(
                  channel.description?.trim().isNotEmpty ?? false
                      ? channel.description!.trim()
                      : AppStrings.noDescriptionBody,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: channel.description?.trim().isNotEmpty ?? false
                            ? null
                            : Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                ),
                const SizedBox(height: 24),
                Text(
                  AppStrings.capabilitiesSectionTitle,
                  style: Theme.of(context).textTheme.titleSmall,
                ),
                const SizedBox(height: 8),
                _InfoLine(
                  label: AppStrings.capabilitiesYouSend,
                  value: _modalityList(caps.input),
                ),
                _InfoLine(
                  label: AppStrings.capabilitiesAssistantSends,
                  value: _modalityList(caps.output),
                ),
                const SizedBox(height: 24),
                Text(
                  AppStrings.detailsSectionTitle,
                  style: Theme.of(context).textTheme.titleSmall,
                ),
                const SizedBox(height: 8),
                _InfoLine(label: AppStrings.labelChannelId, value: channel.id),
                if (cid != null && cid.isNotEmpty)
                  _InfoLine(label: AppStrings.labelCharacterId, value: cid),
                if (channel.serverId != null)
                  _InfoLine(
                    label: AppStrings.labelServerId,
                    value: '${channel.serverId}',
                  ),
                _InfoLine(
                  label: AppStrings.labelLastMessageAt,
                  value: _formatUtc(channel.lastMessageAt),
                ),
                _InfoLine(
                  label: AppStrings.labelThumbnailMtime,
                  value: channel.thumbnailMtimeNs != null
                      ? '${channel.thumbnailMtimeNs}'
                      : '—',
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

Widget _channelPlaceholderAvatar(BuildContext context, String channelName) {
  final cs = Theme.of(context).colorScheme;
  final letter = channelName.isNotEmpty ? channelName[0].toUpperCase() : '#';
  return CircleAvatar(
    radius: 40,
    backgroundColor: cs.secondaryContainer,
    foregroundColor: cs.onSecondaryContainer,
    child: Text(
      letter,
      style: Theme.of(context).textTheme.headlineSmall?.copyWith(
            color: cs.onSecondaryContainer,
          ),
    ),
  );
}

Widget _characterAvatar(
  BuildContext context,
  String characterTitle,
  Uint8List? bytes,
) {
  final cs = Theme.of(context).colorScheme;
  final initial =
      characterTitle.isNotEmpty ? characterTitle[0].toUpperCase() : '?';
  return CircleAvatar(
    radius: 40,
    backgroundColor: cs.primaryContainer,
    foregroundColor: cs.onPrimaryContainer,
    backgroundImage: bytes != null ? MemoryImage(bytes) : null,
    child: bytes == null
        ? Text(initial, style: Theme.of(context).textTheme.headlineSmall)
        : null,
  );
}

class _PhotoCaptionCard extends StatelessWidget {
  const _PhotoCaptionCard({
    required this.caption,
    required this.avatar,
  });

  final String caption;
  final Widget avatar;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Card(
      elevation: 0,
      color: cs.surfaceContainerHighest.withValues(alpha: 0.55),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          children: [
            Text(
              caption,
              style: Theme.of(context).textTheme.labelLarge,
            ),
            const SizedBox(height: 12),
            avatar,
            if (caption == AppStrings.channelPhotoCaption) ...[
              const SizedBox(height: 8),
              Text(
                AppStrings.noChannelImageYet,
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _InfoLine extends StatelessWidget {
  const _InfoLine({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final muted = Theme.of(context).colorScheme.onSurfaceVariant;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 132,
            child: Text(
              label,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: muted,
                  ),
            ),
          ),
          Expanded(
            child: SelectableText(
              value,
              style: Theme.of(context).textTheme.bodyMedium,
            ),
          ),
        ],
      ),
    );
  }
}

String _modalityList(ModalityFlags flags) {
  final parts = <String>[];
  if (flags.voice) parts.add('Voice');
  if (flags.image) parts.add('Images');
  if (flags.video) parts.add('Video');
  if (flags.file) parts.add('Files');
  return parts.isEmpty ? AppStrings.modalitiesNoneListed : parts.join(', ');
}

String _formatUtc(DateTime? utc) {
  if (utc == null) return '—';
  final local = utc.toLocal();
  final y = local.year.toString().padLeft(4, '0');
  final mo = local.month.toString().padLeft(2, '0');
  final d = local.day.toString().padLeft(2, '0');
  final h = local.hour.toString().padLeft(2, '0');
  final mi = local.minute.toString().padLeft(2, '0');
  return '$y-$mo-$d $h:$mi';
}
