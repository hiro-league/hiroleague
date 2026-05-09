import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/utils/logger.dart';
import '../../data/local/database/app_database.dart';
import '../../data/repositories/channel_repository_impl.dart';
import '../../data/remote/gateway/gateway_request_client.dart';
import '../../domain/repositories/channel_repository.dart';
import '../../domain/models/server_info/server_info.dart';
import '../policy/policy_notifier.dart';
import '../../platform/storage/audio_storage_service.dart';
import 'attachment_fetch_service.dart';
import 'character_photo_sync.dart';
import 'message_history_sync.dart';
import 'resource_sync_registry.dart';
import 'resource_sync_version_store.dart';

final _log = Logger.get('ResourceSync');

/// How long a chat-screen open will trust cached message history before
/// triggering a background re-pull. Per ``docs/message-audio-history-storage.md``
/// §15 — small enough to feel fresh, large enough to absorb rapid screen toggles.
const Duration kMessageHistoryStaleTtl = Duration(seconds: 60);

/// [Ref] (notifier / tests) and [WidgetRef] (consumer widgets) both expose ``.read``;
/// centralized so resource sync helpers work from gateway or screens.
dynamic _providersRead(Object? ref) => ref as dynamic;

/// Highest ``resource_sync_version`` from an inbound ``resource.changed`` event payload.
int? readResourceSyncVersion(Map<String, dynamic> data) {
  final v = data['resource_sync_version'];
  if (v is int) return v;
  if (v is num) return v.toInt();
  return null;
}

/// Registers all device-side resource pull handlers — extension point for new resources.
/// Keeps [GatewayNotifier] free of resource names and fetch logic.
void wireResourceSync({
  required Ref ref,
  required ResourceSyncRegistry registry,
  required GatewayRequestClient? Function() getClient,
}) {
  registry
    ..clear()
    ..register('channels', () => refreshChannels(ref, getClient()))
    ..register('characters', () => refreshCharacterPhotos(ref, getClient()))
    ..register('messages', () => refreshMessageHistory(ref, getClient()))
    ..register('policy', () => refreshPolicy(ref, getClient()));
}

Future<void> refreshPolicy(Ref ref, GatewayRequestClient? client) async {
  if (client == null) return;
  try {
    final response = await client.request('policy.get');
    final data = response['data'];
    if (data is! Map) return;
    final payload = Map<String, dynamic>.from(data);
    final syncVer = readResourceSyncVersion(payload);
    final applied = await _applyPolicyPayload(ref, payload);
    if (!applied) return;
    if (syncVer != null) {
      await ref
          .read(resourceSyncVersionStoreProvider.notifier)
          .recordAuthoritative('policy', syncVer);
    }
    await ref
        .read(resourceSyncVersionStoreProvider.notifier)
        .markPullSucceeded('policy');
  } catch (e) {
    _log.warning('Failed to refresh policy', fields: {'error': e.toString()});
  }
}

/// Pull [channels.list] and merge locally (runs from gateway [Ref]).
Future<void> refreshChannels(Ref ref, GatewayRequestClient? client) async =>
    _refreshChannelsMirror(ref, client);

/// Same as [refreshChannels] but callable from consumer widgets ([WidgetRef]).
Future<void> refreshChannelsWidgetRef(
  WidgetRef ref,
  GatewayRequestClient? client,
) async =>
    _refreshChannelsMirror(ref, client);

Future<void> _refreshChannelsMirror(
  Object? ref,
  GatewayRequestClient? client,
) async {
  if (client == null) return;
  final r = _providersRead(ref);
  try {
    final response = await client.request('channels.list');
    final data = response['data'];
    if (data is! Map) return;
    final payload = Map<String, dynamic>.from(data);
    final syncVer = readResourceSyncVersion(payload);
    final channels = payload['channels'];
    if (channels is! List) return;
    final repo =
        r.read(channelRepositoryProvider) as ChannelRepository;
    final clearedMirror = await repo.syncFromServer(
      channels
          .whereType<Map>()
          .map((channel) => Map<String, dynamic>.from(channel))
          .toList(),
    );
    if (clearedMirror) {
      final sync = _buildSync(ref, client);
      await sync.syncAllServerBackedChannels();
      await refreshPendingMessageAttachments(ref, client);
      await r
          .read(resourceSyncVersionStoreProvider.notifier)
          .markPullSucceeded('messages');
    }
    if (syncVer != null) {
      await (r.read(resourceSyncVersionStoreProvider.notifier))
          .recordAuthoritative('channels', syncVer);
    }
    await (r.read(resourceSyncVersionStoreProvider.notifier)).markPullSucceeded('channels');
    _log.info('Refreshed channel list', fields: {'channels': channels.length});
  } catch (e) {
    _log.warning(
      'Failed to refresh channel list',
      fields: {'error': e.toString()},
    );
  }
}

Future<void> refreshMessageHistory(
  Ref ref,
  GatewayRequestClient? client,
) async {
  if (client == null) return;
  try {
    final db = ref.read(appDatabaseProvider);
    // If the channels table is empty, pull it from the server first so
    // ``listServerBacked`` actually has something to walk. The history sync
    // itself stays uncoupled from channel refresh — this fan-out belongs in
    // the bootstrap, not in MessageHistorySync.
    if (await db.channelsDao.count() == 0) {
      await refreshChannels(ref, client);
    }
    final sync = _buildSync(ref, client);
    final syncedChannels = await sync.syncAllServerBackedChannels();
    if (syncedChannels == 0) return;

    await refreshPendingMessageAttachments(ref, client);
    await ref
        .read(resourceSyncVersionStoreProvider.notifier)
        .markPullSucceeded('messages');
  } catch (e) {
    _log.warning(
      'Failed to refresh message history',
      fields: {'error': e.toString()},
    );
  }
}

Future<void> refreshMessageHistoryForChannel(
  Ref ref,
  GatewayRequestClient? client,
  String channelId, {
  Duration maxStale = kMessageHistoryStaleTtl,
  bool force = false,
}) async {
  if (client == null) return;
  try {
    final db = ref.read(appDatabaseProvider);
    var channel = await db.channelsDao.getById(channelId);
    if (channel == null) {
      await refreshChannels(ref, client);
      channel = await db.channelsDao.getById(channelId);
    }
    if (channel == null || channel.serverId == null) return;

    final lastSynced = channel.lastHistorySyncedAt;
    final nowMs = DateTime.now().millisecondsSinceEpoch;
    if (!force &&
        lastSynced != null &&
        nowMs - lastSynced < maxStale.inMilliseconds) {
      await refreshPendingMessageAttachments(ref, client);
      return;
    }

    final sync = _buildSync(ref, client);
    await sync.syncChannel(channel);
    await refreshPendingMessageAttachments(ref, client);
    await ref
        .read(resourceSyncVersionStoreProvider.notifier)
        .markPullSucceeded('messages');
  } catch (e) {
    _log.warning(
      'Failed to refresh channel message history',
      fields: {'channel_id': channelId, 'error': e.toString()},
    );
  }
}

MessageHistorySync _buildSync(Object? ref, GatewayRequestClient client) {
  final db = _providersRead(ref).read(appDatabaseProvider) as AppDatabase;
  return MessageHistorySync(
    channelsDao: db.channelsDao,
    messagesDao: db.messagesDao,
    attachmentsDao: db.messageAttachmentsDao,
    requestHistory: (params) =>
        client.request('messages.history', params: params),
  );
}

Future<void> refreshPendingMessageAttachments(
  Object? ref,
  GatewayRequestClient? client,
) async {
  if (client == null) return;
  final r = _providersRead(ref);
  final db = r.read(appDatabaseProvider) as AppDatabase;
  final fetcher = AttachmentFetchService(
    attachmentsDao: db.messageAttachmentsDao,
    fetchBytes: client.filesGet,
    saveBytes: r.read(audioStorageProvider).saveBytes,
  );
  await fetcher.tick();
}

Future<bool> _applyPolicyPayload(Ref ref, Map<String, dynamic> payload) async {
  try {
    final forParse = Map<String, dynamic>.from(payload)
      ..remove('resource_sync_version');
    final snapshot = PolicySnapshot.fromJson(forParse);
    await ref.read(policyProvider.notifier).applySnapshot(snapshot);
    _log.info('Applied policy snapshot', fields: {'version': snapshot.version});
    return true;
  } catch (e) {
    _log.warning(
      'Failed to apply policy snapshot',
      fields: {'error': e.toString()},
    );
    return false;
  }
}
