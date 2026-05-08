import 'package:device_apps/core/utils/message_ownership.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('server sender renders on agent side', () {
    expect(isUserSideSenderId('server'), isFalse);
    expect(
      isUserSideHistoryMessage(senderType: 'agent', senderId: 'server'),
      isFalse,
    );
  });

  test('any paired device sender renders on user side', () {
    expect(isUserSideSenderId('device-a'), isTrue);
    expect(isUserSideSenderId('device-b'), isTrue);
    expect(
      isUserSideHistoryMessage(senderType: 'user', senderId: 'device-b'),
      isTrue,
    );
  });

  test('history falls back to sender id only when sender type is absent', () {
    expect(
      isUserSideHistoryMessage(senderType: null, senderId: 'device-a'),
      isTrue,
    );
    expect(
      isUserSideHistoryMessage(senderType: null, senderId: 'server'),
      isFalse,
    );
  });
}
