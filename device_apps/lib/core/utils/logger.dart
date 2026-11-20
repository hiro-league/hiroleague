import 'package:talker/talker.dart';

import '../logging/app_talker.dart';
import '../logging/device_problems.dart';

/// Structured logger backed by [Talker] (console, in-app log UI, file on mobile/desktop); its warnings and errors
/// also go to the core's log ([DeviceProblems]).
/// Usage:
///   final _log = Logger.get('GatewayClient');
///   _log.info('Connected', fields: {'url': url});
class Logger {
  const Logger._(this._tag);

  final String _tag;

  static Logger get(String tag) => Logger._(tag);

  Talker get _t => appTalker;

  void info(String message, {Map<String, Object?> fields = const {}}) =>
      _emit(LogLevel.info, message, fields: fields);

  void warning(String message, {Map<String, Object?> fields = const {}}) =>
      _emit(LogLevel.warning, message, fields: fields);

  void error(
    String message, {
    Object? error,
    StackTrace? stackTrace,
    Map<String, Object?> fields = const {},
  }) =>
      _emit(LogLevel.error, message,
          fields: fields, error: error, stackTrace: stackTrace);

  void debug(String message, {Map<String, Object?> fields = const {}}) {
    assert(() {
      _emit(LogLevel.debug, message, fields: fields);
      return true;
    }());
  }

  void _emit(
    LogLevel level,
    String message, {
    Map<String, Object?> fields = const {},
    Object? error,
    StackTrace? stackTrace,
  }) {
    final buf = StringBuffer('[$_tag] $message');
    if (fields.isNotEmpty) {
      buf
        ..write(' {')
        ..write(fields.entries.map((e) => '${e.key}=${e.value}').join(', '))
        ..write('}');
    }
    _t.log(
      buf.toString(),
      logLevel: level,
      exception: error,
      stackTrace: stackTrace,
    );
    // Warnings and errors are problems: they go to the core's log too, fields made safe there (device_problems.dart).
    if (level == LogLevel.warning || level == LogLevel.error) {
      deviceProblems.record(
        level: level == LogLevel.error ? 'ERROR' : 'WARNING',
        area: _tag,
        message: message,
        fields: fields,
        error: error,
        stackTrace: stackTrace,
      );
    }
  }
}
