import 'dart:async';

/// Maps logical resource names (server ``resource.changed`` hints) to fetch/sync lambdas.
///
/// Populated at gateway connect so closures capture the live [GatewayRequestClient].
/// Lives under [application/sync] with [ResourceSyncVersionStore] — not transport-layer.
final class ResourceSyncRegistry {
  final Map<String, Future<void> Function()> _handlers = {};

  void register(String resource, Future<void> Function() syncer) {
    _handlers[resource] = syncer;
  }

  void clear() => _handlers.clear();

  Future<void> sync(String resource) async {
    final fn = _handlers[resource];
    if (fn != null) await fn();
  }

  /// Runs every registered fetcher concurrently (connect-time reconcile).
  Future<void> syncAll() async {
    await Future.wait(_handlers.values.map((fn) => fn()));
  }
}
