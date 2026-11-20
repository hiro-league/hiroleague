import 'dart:async';
import 'dart:developer' show log;

import 'package:flutter/foundation.dart';
import 'package:talker/talker.dart';

import 'device_problems.dart';
import 'log_file_sink.dart';

Talker? _appTalker;

/// Global Talker instance; valid after [ensureAppTalkerInitialized] completes.
Talker get appTalker {
  final t = _appTalker;
  if (t == null) {
    throw StateError('ensureAppTalkerInitialized() must run before using appTalker');
  }
  return t;
}

/// Idempotent: safe to call once from bootstrap.
Future<void> ensureAppTalkerInitialized() async {
  if (_appTalker != null) return;

  if (!kIsWeb) {
    try {
      await initLogFileSink();
    } catch (e, st) {
      // File sink is best-effort; console + in-memory history still work.
      debugPrint('⚠️ Log file init failed — $e\n$st');
    }
  }

  void combinedOutput(String message) {
    if (kIsWeb) {
      // ignore: avoid_print
      print(message);
    } else {
      switch (defaultTargetPlatform) {
        case TargetPlatform.iOS:
        case TargetPlatform.macOS:
          log(message, name: 'Talker');
          break;
        default:
          debugPrint(message);
      }
    }
    if (!kIsWeb) {
      appendLogLineToFile(message);
    }
  }

  // Problems an earlier run left unsent (device_problems.dart): they go with the next connection.
  unawaited(deviceProblems.load());

  // Single formatted stream: disable ANSI so file lines stay plain text.
  _appTalker = Talker(
    observer: const _ProblemObserver(),
    logger: TalkerLogger(
      settings: TalkerLoggerSettings(enableColors: false),
      output: combinedOutput,
    ),
    settings: TalkerSettings(maxHistoryItems: 2000),
  );
}

/// Errors nobody caught (main.dart hands them to Talker): each is a problem for the core's log. The app's own
/// warnings and errors come through [Logger], which reports them itself.
class _ProblemObserver extends TalkerObserver {
  const _ProblemObserver();

  @override
  void onError(TalkerError err) => _report(err, err.error);

  @override
  void onException(TalkerException err) => _report(err, err.exception);

  void _report(TalkerData data, Object? error) => deviceProblems.record(
    level: 'ERROR',
    area: 'app',
    message: data.message ?? 'Uncaught error',
    error: error,
    stackTrace: data.stackTrace,
  );
}
