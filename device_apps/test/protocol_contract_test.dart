import 'dart:convert';
import 'dart:io';

import 'package:device_apps/data/remote/gateway/gateway_contract.dart';
import 'package:device_apps/data/remote/gateway/gateway_protocol.dart';
import 'package:device_apps/data/remote/gateway/unified_message.dart';
import 'package:flutter_test/flutter_test.dart';

final _fixturesDir = Directory('../protocol/fixtures');

const _validFixtures = [
  'valid-text-message.json',
  'valid-audio-message.json',
  'valid-message-received-event.json',
  'valid-message-transcribed-event.json',
  'valid-message-voiced-event.json',
  'valid-request.json',
  'valid-response-ok.json',
  'valid-response-error.json',
];

const _invalidFixtures = [
  'invalid-event-with-content.json',
  'invalid-message-without-content.json',
  'invalid-unsupported-version.json',
];

Map<String, dynamic> _loadFixture(String name) {
  final file = File('${_fixturesDir.path}/$name');
  return (jsonDecode(file.readAsStringSync()) as Map).cast<String, dynamic>();
}

void main() {
  group('UnifiedMessage protocol fixtures', () {
    for (final fixture in _validFixtures) {
      test('parses $fixture', () {
        final payload = _loadFixture(fixture);

        final message = UnifiedMessage.fromJson(payload);

        expect(message.version, UnifiedMessageWire.version);
      });
    }

    for (final fixture in _invalidFixtures) {
      test('rejects $fixture', () {
        final payload = _loadFixture(fixture);

        expect(() => UnifiedMessage.fromJson(payload), throwsFormatException);
      });
    }
  });

  test('serializes outbound text message using the agreed wire shape', () {
    final message = UnifiedMessage(
      routing: const MessageRouting(
        id: 'msg-text-1',
        channel: 'devices',
        direction: UnifiedMessageWire.directionOutbound,
        senderId: 'device-1',
        timestamp: '2026-04-28T18:00:00Z',
        metadata: {MetadataWire.channelId: '1'},
      ),
      content: const [
        ContentItem(contentType: ContentWire.text, body: 'Hello Hiro'),
      ],
    );

    final json = message.toJson();

    expect(json['version'], UnifiedMessageWire.version);
    expect(json['message_type'], UnifiedMessageWire.typeMessage);
    expect(json['routing'], isA<Map<String, dynamic>>());
    expect(json['content'], isA<List<dynamic>>());
    expect((json['content'] as List).first['content_type'], ContentWire.text);
  });

  test('decodes gateway inbound envelope fixture', () {
    final payload = _loadFixture('valid-gateway-inbound-envelope.json');
    final frame = const GatewayProtocol().decode(jsonEncode(payload));

    expect(frame, isNotNull);
    expect(frame!.senderDeviceId, 'device-1');
    expect(frame.payload['version'], UnifiedMessageWire.version);
  });

  test('encodes gateway outbound envelope', () {
    final encoded = const GatewayProtocol().encode(
      payload: _loadFixture('valid-text-message.json'),
      targetDeviceId: 'device-1',
    );
    final envelope = (jsonDecode(encoded) as Map).cast<String, dynamic>();

    expect(envelope[GatewayEnvelopeWire.targetDeviceId], 'device-1');
    expect(envelope[GatewayEnvelopeWire.payload], isA<Map<String, dynamic>>());
  });
}
