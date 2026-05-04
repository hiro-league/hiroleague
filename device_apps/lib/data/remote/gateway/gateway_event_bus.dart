import '../../../core/utils/logger.dart';
import 'gateway_contract.dart';

typedef GatewayAppEventHandler =
    Future<void> Function(Map<String, dynamic> data);

/// Dispatches inbound application-level UnifiedMessage events by [event.type].
///
/// Keeps transport (`GatewayNotifier`) unaware of specific domain event payloads.
final class GatewayEventBus {
  GatewayEventBus({Logger? logger}) : _log = logger ?? Logger.get('GatewayEventBus');

  final Logger _log;
  final Map<String, GatewayAppEventHandler> _handlers = {};

  /// Registers or replaces the handler for [eventType].
  void register(String eventType, GatewayAppEventHandler handler) {
    _handlers[eventType] = handler;
  }

  /// Parses [payload] as an inbound event and dispatches when a handler exists.
  Future<void> dispatch(Map<String, dynamic> payload) async {
    if (payload['message_type'] != UnifiedMessageWire.typeEvent) return;

    final rawEvent = payload['event'];
    if (rawEvent is! Map) return;

    final eventMap = Map<String, dynamic>.from(rawEvent);
    final type = eventMap['type'] as String?;
    if (type == null) return;

    final handler = _handlers[type];
    if (handler == null) return;

    final dataRaw = eventMap['data'];
    final data = dataRaw is Map
        ? Map<String, dynamic>.from(dataRaw)
        : <String, dynamic>{};

    try {
      await handler(data);
    } catch (e) {
      _log.warning(
        'Gateway event handler failed',
        fields: {'event_type': type, 'error': e.toString()},
      );
    }
  }
}
