/// A decoded inbound message from the gateway relay.
///
/// The gateway injects [senderDeviceId] into every relayed message.
/// [payload] is the application-level content — interpreted by MessageRepository.
class GatewayInboundFrame {
  const GatewayInboundFrame({
    required this.senderDeviceId,
    required this.payload,
  });

  final String senderDeviceId;
  final Map<String, dynamic> payload;
}
