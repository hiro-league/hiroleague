import 'dart:io';

import 'package:path_provider/path_provider.dart';

/// Max active log file size before rotate to [fileName].1 (user-approved ~8 MiB cap).
const int _kMaxLogBytes = 8 * 1024 * 1024;

const String _fileName = 'hiro_app.log';

IOSink? _sink;

Future<void> initLogFileSink() async {
  final dir = await getApplicationSupportDirectory();
  final path = '${dir.path}/$_fileName';
  final file = File(path);
  if (await file.exists()) {
    final len = await file.length();
    if (len > _kMaxLogBytes) {
      final backup = File('$path.1');
      if (await backup.exists()) {
        await backup.delete();
      }
      await file.rename(backup.path);
    }
  }
  _sink = File(path).openWrite(mode: FileMode.append);
}

void appendLogLineToFile(String line) {
  _sink?.writeln(line);
}
