import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:device_apps/core/logging/device_problems.dart';
import 'package:device_apps/core/logging/problem_store.dart';

// The phone's problems go to the core's log (device_problems.dart): they wait while offline (in a file, so a crash
// loses none), go in batches once connected, carry their chat message's story, and leave a person's words behind.
void main() {
  late Directory folder;
  late DeviceProblems problems;

  setUp(() {
    folder = Directory.systemTemp.createTempSync('hiro-problems-');
    problems = DeviceProblems(
      store: ProblemStore(folder: () async => folder),
      delay: const Duration(milliseconds: 1),
    );
  });

  tearDown(() async {
    problems.disconnected();
    await Future<void>.delayed(const Duration(milliseconds: 100)); // the queue's file writes end
    folder.deleteSync(recursive: true);
  });

  test('a problem made offline waits, and is sent once connected', () async {
    problems.record(level: 'ERROR', area: 'Gateway', message: 'Connection lost');
    expect(problems.waiting, hasLength(1));

    final sent = <List<Map<String, dynamic>>>[];
    problems.connected((lines) async {
      sent.add(lines);
      return true;
    });
    await problems.flush();
    expect(sent, hasLength(1));
    expect(sent.single.single, containsPair('message', 'Connection lost'));
    expect(sent.single.single['id'], isA<String>());
    expect(problems.waiting, isEmpty);
  });

  test('a batch the core did not take waits for the next try', () async {
    problems.record(level: 'WARNING', area: 'Gateway', message: 'Slow');
    problems.connected((lines) async => throw StateError('dropped'));
    await problems.flush();
    expect(problems.waiting, hasLength(1));
    problems.disconnected();
  });

  test("a problem while a message is sent carries the message's id", () async {
    await DeviceProblems.inStory('9b2c4c9e-1f7a-4d43-8a0e-0f7c3c1d2e11', () async {
      await Future<void>.delayed(Duration.zero); // across an await too
      problems.record(level: 'ERROR', area: 'MessageSendNotifier', message: 'Failed to send message');
    });
    expect(problems.waiting.single['story'], '9b2c4c9e-1f7a-4d43-8a0e-0f7c3c1d2e11');
  });

  test("secrets and a person's words stay on the phone", () {
    final safe = DeviceProblems.safeFields({
      'token': 'abc',
      'device_key': 'k',
      'text': 'hello Hiro',
      'url': 'ws://gateway',
      'count': 3,
    });
    expect(safe, {
      'token': '[hidden]',
      'device_key': '[hidden]',
      'text': '[hidden]',
      'url': 'ws://gateway',
      'count': 3,
    });
  });

  test('what was never sent is still there after a restart', () async {
    problems.record(level: 'ERROR', area: 'app', message: 'Crashed');
    await Future<void>.delayed(const Duration(milliseconds: 50));
    final next = DeviceProblems(store: ProblemStore(folder: () async => folder));
    await next.load();
    expect(next.waiting.single['message'], 'Crashed');
  });
}
