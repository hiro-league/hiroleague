import 'dart:developer' as dev;

/// Structured logger wrapping dart:developer.
/// Usage:
///   final _log = Logger.get('GatewayClient');
///   _log.info('Connected', fields: {'url': url});
class Logger {
  const Logger._(this._tag);

  final String _tag;

  static Logger get(String tag) => Logger._(tag);

  void info(String message, {Map<String, Object?> fields = const {}}) =>
      _emit('INFO', message, fields: fields);

  void warning(String message, {Map<String, Object?> fields = const {}}) =>
      _emit('WARN', message, fields: fields);

  void error(
    String message, {
    Object? error,
    StackTrace? stackTrace,
    Map<String, Object?> fields = const {},
  }) =>
      _emit('ERROR', message, fields: fields, error: error, stackTrace: stackTrace);

  void debug(String message, {Map<String, Object?> fields = const {}}) {
    assert(() {
      _emit('DEBUG', message, fields: fields);
      return true;
    }());
  }

  void _emit(
    String level,
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
    dev.log(buf.toString(), name: level, error: error, stackTrace: stackTrace);
  }
}
