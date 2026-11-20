import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

/// The problems not yet sent, in a file beside the app's log (device_problems.dart): what the app saw before it
/// crashed, or while offline, still reaches the core on the next connection.
class ProblemStore {
  ProblemStore({Future<Directory> Function()? folder}) : _folder = folder ?? getApplicationSupportDirectory;

  static const fileName = 'hiro_problems.json';
  final Future<Directory> Function() _folder;
  Future<void> _last = Future.value();

  Future<File> _file() async => File('${(await _folder()).path}/$fileName');

  Future<List<Map<String, dynamic>>> read() async {
    final file = await _file();
    if (!await file.exists()) return const [];
    final raw = jsonDecode(await file.readAsString());
    if (raw is! List) return const [];
    return [for (final p in raw) if (p is Map) Map<String, dynamic>.from(p)];
  }

  /// Writes are done one after another, so the last one wins.
  Future<void> write(List<Map<String, dynamic>> problems) {
    _last = _last.then((_) async {
      final file = await _file();
      final tmp = File('${file.path}.tmp');
      await tmp.writeAsString(jsonEncode(problems), flush: true);
      await tmp.rename(file.path);
    }).catchError((Object _) {});
    return _last;
  }
}
