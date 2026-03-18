import 'dart:js_interop';
import 'dart:typed_data';

import 'package:web/web.dart' as web;

/// Fetches bytes from a blob URL (or any URL) on web using fetch API.
Future<Uint8List?> fetchAudioBytes(String url) async {
  try {
    final response = await web.window.fetch(url.toJS).toDart;
    final buffer = await response.arrayBuffer().toDart;
    return Uint8List.view(buffer.toDart);
  } catch (_) {
    return null;
  }
}
