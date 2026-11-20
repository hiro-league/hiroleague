import 'dart:async';
import 'dart:convert';

import 'package:uuid/uuid.dart';

import 'problem_store.dart';

/// The phone's problems, sent to the core's log: the logging plan's phase 8 (the device app joins as a source).
///
/// Only problems join: each warning or error the app logs ([Logger]) and every error nobody caught (Talker's
/// handler, main.dart). The app's full log stays on the phone (Later, in the plan).
///
/// Each problem waits in a small queue, kept in a file on the phone (not on the web), and goes to the core as a
/// `logs.report` request over the device's connection when it is up ([GatewayNotifier] says when). The core keeps a
/// problem it already has once, so one sent twice (the connection dropped before its answer) is no harm. Made while
/// offline, or before the app crashed: sent when the device connects again.
///
/// The story: a problem made while a chat message is being sent ([inStory]) carries the message's own id, which the
/// core turns into the story's id as it does for the message itself, so it shows under that message's story.
///
/// What leaves the phone: the area, the sentence, the error's type, message and stack, and the logger's fields with
/// secrets hidden and a person's words left out (a message's text, a transcript), each cut to size.
class DeviceProblems {
  DeviceProblems({ProblemStore? store, Duration delay = const Duration(seconds: 2)})
    : _store = store ?? ProblemStore(),
      _delay = delay;

  static const method = 'logs.report';
  static const batchMax = 20; // the core takes at most 20 at once
  static const waitingMax = 200; // older ones go first past this
  static const perMinute = 30;

  final ProblemStore _store;
  final Duration _delay;
  final List<Map<String, dynamic>> _waiting = [];
  static const _uuid = Uuid();

  Future<bool> Function(List<Map<String, dynamic>> lines)? _send;
  Timer? _timer;
  bool _sending = false;
  bool _loaded = false;
  DateTime _minuteStart = DateTime.fromMillisecondsSinceEpoch(0);
  int _minuteCount = 0;

  /// Problems waiting to be sent (a copy).
  List<Map<String, dynamic>> get waiting => List.unmodifiable(_waiting);

  /// Reads what an earlier run left unsent. Safe to call more than once.
  Future<void> load() async {
    if (_loaded) return;
    _loaded = true;
    try {
      final left = await _store.read();
      _waiting.insertAll(0, left);
      _trim();
    } catch (_) {
      // A file that can't be read loses only old problems; never a problem of its own (it would loop).
    }
    if (_waiting.isNotEmpty) _schedule();
  }

  /// The connection is up: [send] takes a batch and says whether the core took it.
  void connected(Future<bool> Function(List<Map<String, dynamic>> lines) send) {
    _send = send;
    _schedule(now: true);
  }

  /// The connection is down: problems wait.
  void disconnected() {
    _send = null;
    _timer?.cancel();
    _timer = null;
  }

  /// Notes one problem. Never throws.
  void record({
    required String level,
    required String area,
    required String message,
    Map<String, Object?> fields = const {},
    Object? error,
    StackTrace? stackTrace,
  }) {
    try {
      final now = DateTime.now().toUtc();
      if (now.difference(_minuteStart) >= const Duration(minutes: 1)) {
        _minuteStart = now;
        _minuteCount = 0;
      }
      if (_minuteCount >= perMinute) return;
      _minuteCount++;
      final story = currentStoryRef();
      _waiting.add({
        'id': _uuid.v4(),
        'at': now.toIso8601String(),
        'level': level,
        'area': cut(area, 100),
        'message': cut(message, 500),
        if (fields.isNotEmpty) 'fields': safeFields(fields),
        if (error != null) 'error_type': cut(error.runtimeType.toString(), 200),
        if (error != null) 'error_message': cut(error.toString(), 2000),
        if (stackTrace != null) 'stack': cut(stackTrace.toString(), 8000),
        'story': ?story,
      });
      _trim();
      _save();
      _schedule();
    } catch (_) {
      // A report must never become the app's problem of its own.
    }
  }

  /// Sends what waits now (tests; the timer otherwise).
  Future<void> flush() async {
    _timer = null;
    final send = _send;
    if (send == null || _sending || _waiting.isEmpty) return;
    final batch = _waiting.take(batchMax).toList();
    _sending = true;
    var taken = false;
    try {
      taken = await send(batch);
    } catch (_) {
      // No answer (the connection dropped, a timeout): they wait for the next try.
    } finally {
      _sending = false;
    }
    if (taken) {
      final ids = batch.map((p) => p['id']).toSet();
      _waiting.removeWhere((p) => ids.contains(p['id']));
      _save();
    }
    if (_waiting.isNotEmpty && _send != null) _schedule(again: !taken);
  }

  void _schedule({bool now = false, bool again = false}) {
    if (_send == null || _timer != null) return;
    // A batch the core didn't take is tried again a little later, not in a tight loop.
    final wait = now ? Duration.zero : (again ? _delay * 15 : _delay);
    _timer = Timer(wait, () => unawaited(flush()));
  }

  void _trim() {
    if (_waiting.length > waitingMax) _waiting.removeRange(0, _waiting.length - waitingMax);
  }

  void _save() {
    unawaited(_store.write(List.of(_waiting)).catchError((Object _) {}));
  }

  // --- the story ----------------------------------------------------------------------------------------------------

  static const _storyKey = #hiroStoryRef;

  /// Runs [body] as part of the story of [ref] (a chat message's own id): every problem it makes carries it.
  static R inStory<R>(String ref, R Function() body) =>
      runZoned(body, zoneValues: {_storyKey: ref});

  /// The story's ref now (a chat message's id), or null outside one.
  static String? currentStoryRef() => Zone.current[_storyKey] as String?;

  // --- what may leave the phone ---------------------------------------------------------------------------------------

  static const _secretNames = {
    'password', 'passwd', 'token', 'secret', 'api_key', 'apikey', 'authorization', 'cookie', 'access_token',
    'refresh_token', 'session_token', 'private_key', 'signature', 'nonce_signature', 'attestation',
  };
  static const _secretEnds = ['_password', '_token', '_secret', '_key', '_cookie', '_signature'];
  // A person's words: never in a problem (the core's own lines keep only a short preview, on purpose).
  static const _wordNames = {'text', 'body', 'content', 'transcript', 'prompt', 'caption', 'message_text'};
  static const hidden = '[hidden]';

  static bool isSecret(String name) {
    final low = name.toLowerCase();
    return _secretNames.contains(low) || _secretEnds.any(low.endsWith);
  }

  static Map<String, Object?> safeFields(Map<String, Object?> fields) {
    final out = <String, Object?>{};
    for (final MapEntry(:key, :value) in fields.entries.take(20)) {
      final low = key.toLowerCase();
      if (isSecret(low) || _wordNames.contains(low)) {
        out[key] = hidden;
      } else if (value == null || value is num || value is bool) {
        out[key] = value;
      } else {
        out[key] = cut(value is String ? value : jsonEncodeOrString(value), 200);
      }
    }
    return out;
  }

  static String jsonEncodeOrString(Object value) {
    try {
      return jsonEncode(value);
    } catch (_) {
      return value.toString();
    }
  }

  static String cut(String text, int size) =>
      text.length <= size ? text : '${text.substring(0, size - 1)}…';
}

/// The app's one queue of problems.
final deviceProblems = DeviceProblems();
