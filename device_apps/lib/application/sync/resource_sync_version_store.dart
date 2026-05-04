import 'dart:async';
import 'dart:convert';

import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../platform/storage/secure_storage_service.dart';

part 'resource_sync_version_store.g.dart';

const _storageKey = 'resource_sync_versions.v1';

/// Last-seen ``resource_sync_version`` per logical resource (Tier 2), plus
/// pull timestamps for stale-while-revalidate (resource-sync doc §5).
///
/// Persisted so duplicate-hint guards and staleness checks survive restarts.
@Riverpod(keepAlive: true)
class ResourceSyncVersionStore extends _$ResourceSyncVersionStore {
  /// Epoch ms of last successful pull per resource — not part of [state]
  /// (UI only watches version counters).
  final Map<String, int> _lastPullEpochMs = {};

  @override
  Map<String, int> build() {
    unawaited(_hydrate());
    return const {};
  }

  Future<void> _hydrate() async {
    final raw = await ref.read(secureStorageServiceProvider).read(_storageKey);
    if (raw == null || raw.isEmpty) return;
    try {
      final decoded = jsonDecode(raw) as Map<String, dynamic>;
      if (decoded.containsKey('versions')) {
        final versionsRaw = decoded['versions'];
        final pullsRaw = decoded['last_pull_ms'];
        if (versionsRaw is Map && pullsRaw is Map) {
          state = versionsRaw.map((k, v) => MapEntry(k.toString(), _asInt(v)));
          _lastPullEpochMs
            ..clear()
            ..addEntries(
              pullsRaw.entries.map(
                (e) => MapEntry(e.key.toString(), _asInt(e.value)),
              ),
            );
          return;
        }
      }
      // Legacy Tier-2 blob: flat resource → version map only.
      state = decoded.map((k, v) => MapEntry(k.toString(), _asInt(v)));
      _lastPullEpochMs.clear();
    } catch (_) {
      // Corrupt storage — ignore; fresh sync will repopulate versions.
    }
  }

  static int _asInt(Object? v) {
    if (v is int) return v;
    if (v is num) return v.toInt();
    return int.parse(v.toString());
  }

  Future<void> _persist() async {
    await ref.read(secureStorageServiceProvider).write(
          _storageKey,
          jsonEncode({
            'versions': state,
            'last_pull_ms': _lastPullEpochMs,
          }),
        );
  }

  /// Highest version applied locally for [resource], or null if unknown.
  int? lastSeen(String resource) => state[resource];

  /// True when we never pulled [resource], or the last successful pull is older than [maxStale].
  bool shouldRevalidate(String resource, Duration maxStale) {
    final ms = _lastPullEpochMs[resource];
    if (ms == null) return true;
    final elapsed = DateTime.now().difference(DateTime.fromMillisecondsSinceEpoch(ms));
    return elapsed > maxStale;
  }

  /// Record a completed authoritative pull (updates staleness clock even when the version is unchanged).
  Future<void> markPullSucceeded(String resource) async {
    _lastPullEpochMs[resource] = DateTime.now().millisecondsSinceEpoch;
    await _persist();
  }

  /// Persist [version] from a successful pull — authoritative over whatever we had locally.
  ///
  /// A lower number means the server restarted its counters; we still adopt it so stale
  /// ``resource.changed`` guards stay aligned with the host.
  Future<void> recordAuthoritative(String resource, int version) async {
    if (state[resource] == version) return;
    state = {...state, resource: version};
    await _persist();
  }

  Future<void> clear() async {
    state = const {};
    _lastPullEpochMs.clear();
    await ref.read(secureStorageServiceProvider).delete(_storageKey);
  }
}
