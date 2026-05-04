import 'dart:async';

import 'package:device_apps/application/sync/resource_sync_registry.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('syncAll invokes every registered handler', () async {
    final registry = ResourceSyncRegistry();
    var count = 0;
    registry
      ..register('a', () async {
        count++;
      })
      ..register('b', () async {
        count++;
      });
    await registry.syncAll();
    expect(count, 2);
  });

  test('syncAll runs handlers concurrently', () async {
    final registry = ResourceSyncRegistry();
    final c1 = Completer<void>();
    final c2 = Completer<void>();
    var started = 0;
    registry
      ..register('a', () async {
        started++;
        await c1.future;
      })
      ..register('b', () async {
        started++;
        await c2.future;
      });
    final done = registry.syncAll();
    await Future<void>.delayed(Duration.zero);
    expect(started, 2);
    c1.complete();
    c2.complete();
    await done;
  });
}
