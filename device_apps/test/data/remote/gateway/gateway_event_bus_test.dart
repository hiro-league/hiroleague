import 'package:device_apps/core/utils/logger.dart';
import 'package:device_apps/data/remote/gateway/gateway_contract.dart';
import 'package:device_apps/data/remote/gateway/gateway_event_bus.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('dispatch routes by event.type to handler', () async {
    Map<String, dynamic>? seen;
    final bus = GatewayEventBus(logger: Logger.get('test'));
    bus.register(EventWire.resourceChanged, (data) async {
      seen = data;
    });

    await bus.dispatch({
      'message_type': UnifiedMessageWire.typeEvent,
      'event': {
        'type': EventWire.resourceChanged,
        'data': {'resource': 'channels', 'resource_sync_version': 3},
      },
    });

    expect(seen!['resource'], 'channels');
    expect(seen!['resource_sync_version'], 3);
  });

  test('dispatch no-ops when message_type is not event', () async {
    var called = false;
    final bus = GatewayEventBus(logger: Logger.get('test'));
    bus.register(EventWire.resourceChanged, (_) async {
      called = true;
    });
    await bus.dispatch({'message_type': UnifiedMessageWire.typeResponse});
    expect(called, false);
  });
}
