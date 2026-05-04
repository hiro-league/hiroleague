import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/utils/logger.dart';
import '../../data/repositories/channel_repository_impl.dart';
import '../../data/remote/gateway/gateway_request_client.dart';
import '../../domain/models/server_info/server_info.dart';
import '../policy/policy_notifier.dart';
import 'resource_sync_registry.dart';
import 'resource_sync_version_store.dart';

final _log = Logger.get('ResourceSync');

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
    ..register('policy', () => refreshPolicy(ref, getClient()));
}

Future<void> refreshPolicy(
  Ref ref,
  GatewayRequestClient? client,
) async {
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
    await ref.read(resourceSyncVersionStoreProvider.notifier).markPullSucceeded('policy');
  } catch (e) {
    _log.warning(
      'Failed to refresh policy',
      fields: {'error': e.toString()},
    );
  }
}

Future<void> refreshChannels(
  Ref ref,
  GatewayRequestClient? client,
) async {
  if (client == null) return;
  try {
    final response = await client.request('channels.list');
    final data = response['data'];
    if (data is! Map) return;
    final payload = Map<String, dynamic>.from(data);
    final syncVer = readResourceSyncVersion(payload);
    final channels = payload['channels'];
    if (channels is! List) return;
    await ref.read(channelRepositoryProvider).syncFromServer(
          channels
              .whereType<Map>()
              .map((channel) => Map<String, dynamic>.from(channel))
              .toList(),
        );
    if (syncVer != null) {
      await ref
          .read(resourceSyncVersionStoreProvider.notifier)
          .recordAuthoritative('channels', syncVer);
    }
    await ref.read(resourceSyncVersionStoreProvider.notifier).markPullSucceeded('channels');
    _log.info(
      'Refreshed channel list',
      fields: {'channels': channels.length},
    );
  } catch (e) {
    _log.warning(
      'Failed to refresh channel list',
      fields: {'error': e.toString()},
    );
  }
}

Future<bool> _applyPolicyPayload(
  Ref ref,
  Map<String, dynamic> payload,
) async {
  try {
    final forParse = Map<String, dynamic>.from(payload)
      ..remove('resource_sync_version');
    final snapshot = PolicySnapshot.fromJson(forParse);
    await ref.read(policyProvider.notifier).applySnapshot(snapshot);
    _log.info(
      'Applied policy snapshot',
      fields: {'version': snapshot.version},
    );
    return true;
  } catch (e) {
    _log.warning(
      'Failed to apply policy snapshot',
      fields: {'error': e.toString()},
    );
    return false;
  }
}
