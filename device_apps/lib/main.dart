import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app.dart';
import 'core/logging/app_talker.dart';

void main() {
  // Binding + runApp must run in the same zone as each other (not async main + inner runZonedGuarded).
  runZonedGuarded(
    () {
      WidgetsFlutterBinding.ensureInitialized();

      ensureAppTalkerInitialized().then((_) {
        FlutterError.onError = (FlutterErrorDetails details) {
          appTalker.handle(
            details.exception,
            details.stack,
            'Flutter framework error',
          );
          if (kDebugMode) {
            FlutterError.presentError(details);
          }
        };

        PlatformDispatcher.instance.onError = (Object error, StackTrace stack) {
          appTalker.handle(error, stack, 'Unhandled async/platform error');
          return true;
        };

        runApp(
          const ProviderScope(
            child: HiroApp(),
          ),
        );
      });
    },
    (Object error, StackTrace stack) {
      try {
        appTalker.handle(error, stack, 'Uncaught zone error');
      } catch (_) {
        // Zone may run before Talker is ready.
        debugPrint('Uncaught zone error (talker unavailable): $error\n$stack');
      }
    },
  );
}
