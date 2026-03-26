import 'dart:developer' show log;

import 'package:flutter/foundation.dart';
import 'package:talker/talker.dart';

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

  // Single formatted stream: disable ANSI so file lines stay plain text.
  _appTalker = Talker(
    logger: TalkerLogger(
      settings: TalkerLoggerSettings(enableColors: false),
      output: combinedOutput,
    ),
    settings: TalkerSettings(maxHistoryItems: 2000),
  );
}
