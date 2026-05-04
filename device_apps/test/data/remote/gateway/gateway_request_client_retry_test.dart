import 'package:device_apps/data/remote/gateway/gateway_request_client.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('takeFrozenIdempotentPending replays with new request_id and completes original future', () async {
    final payloads = <Map<String, dynamic>>[];
    final c1 = GatewayRequestClient(sendFn: (m) => payloads.add(Map<String, dynamic>.from(m)));
    final fut = c1.request('channels.list');
    expect(payloads.length, 1);
    final rid1 = payloads.first['request_id'] as String;

    final frozen = c1.takeFrozenIdempotentPending();
    expect(frozen.length, 1);

    final c2 = GatewayRequestClient(sendFn: (m) => payloads.add(Map<String, dynamic>.from(m)));
    c2.replayFrozen(frozen);
    expect(payloads.length, 2);
    final rid2 = payloads.last['request_id'] as String;
    expect(rid1, isNot(rid2));

    const body =
        '{"status":"ok","data":{"channels":[],"resource_sync_version":0}}';
    expect(c2.completeRequest(rid2, body), true);

    final result = await fut;
    expect(result['status'], 'ok');
  });

  test('non-idempotent pending is completedError on takeFrozenIdempotentPending', () async {
    final c = GatewayRequestClient(sendFn: (_) {});
    final fut = c.request('messages.history', idempotent: false);
    final frozen = c.takeFrozenIdempotentPending();
    expect(frozen, isEmpty);
    await expectLater(fut, throwsA(isA<StateError>()));
  });
}
