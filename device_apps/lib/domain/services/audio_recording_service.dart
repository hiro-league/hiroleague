import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

/// Result returned from [AudioRecordingService.stopRecording].
class AudioRecordingResult {
  const AudioRecordingResult({
    required this.bytes,
    required this.durationMs,
    required this.tempPath,
  });

  final Uint8List bytes;
  final int durationMs;

  /// Temporary file path (mobile) or empty string (web — bytes are in memory).
  final String tempPath;
}

/// Wraps the [record] package for cross-platform audio recording.
///
/// Records in AAC/m4a format (~128 kbps), accepted by both OpenAI and Gemini
/// STT APIs. Enforces a 60-second maximum and auto-stops when reached.
///
/// Platform behaviour:
/// - Mobile (iOS/Android): records to a temp file in the system temp dir.
/// - Web: records to in-memory bytes via MediaRecorder.
class AudioRecordingService {
  AudioRecordingService() : _recorder = AudioRecorder();

  final AudioRecorder _recorder;

  final ValueNotifier<bool> isRecording = ValueNotifier(false);

  DateTime? _startTime;
  Timer? _maxTimer;
  Completer<AudioRecordingResult?>? _autoStopCompleter;

  static const int _maxDurationMs = 60000;

  /// Starts recording. Resolves automatically after 60 s if not stopped sooner.
  ///
  /// On mobile, checks permission first and throws if denied.
  /// On web, skips the pre-check — the browser permission prompt fires when
  /// [AudioRecorder.start] is called. If the user denies in the browser dialog
  /// the start() call throws, which is caught and re-thrown as a readable error.
  Future<void> startRecording() async {
    if (!kIsWeb) {
      final hasPermission = await _recorder.hasPermission();
      if (!hasPermission) {
        throw Exception('Microphone permission denied');
      }
    }

    final config = const RecordConfig(
      encoder: AudioEncoder.aacLc,
      bitRate: 128000,
      sampleRate: 44100,
    );

    try {
      if (kIsWeb) {
        await _recorder.start(config, path: '');
      } else {
        final tmpDir = await getTemporaryDirectory();
        final path =
            '${tmpDir.path}/hiro_rec_${DateTime.now().millisecondsSinceEpoch}.m4a';
        await _recorder.start(config, path: path);
      }
    } catch (e) {
      // Normalise browser permission denial into a readable message.
      final msg = e.toString().toLowerCase();
      if (msg.contains('permission') ||
          msg.contains('notallowed') ||
          msg.contains('denied')) {
        throw Exception('Microphone permission denied');
      }
      rethrow;
    }

    _startTime = DateTime.now();
    isRecording.value = true;

    // Auto-stop after max duration.
    _autoStopCompleter = Completer<AudioRecordingResult?>();
    _maxTimer = Timer(const Duration(milliseconds: _maxDurationMs), () async {
      if (isRecording.value) {
        final result = await _doStop();
        if (!(_autoStopCompleter?.isCompleted ?? true)) {
          _autoStopCompleter?.complete(result);
        }
      }
    });
  }

  /// Returns elapsed milliseconds since [startRecording].
  int get elapsedMs =>
      _startTime != null
          ? DateTime.now().difference(_startTime!).inMilliseconds
          : 0;

  /// Stops recording and returns the result.
  ///
  /// Returns null if not currently recording.
  Future<AudioRecordingResult?> stopRecording() async {
    if (!isRecording.value) return null;
    _maxTimer?.cancel();
    _autoStopCompleter?.complete(null); // signal we handled it
    return _doStop();
  }

  /// Cancels the active recording and discards the data.
  Future<void> cancelRecording() async {
    if (!isRecording.value) return;
    _maxTimer?.cancel();
    _autoStopCompleter?.complete(null);

    final path = await _recorder.stop();
    isRecording.value = false;
    _startTime = null;

    if (path != null && path.isNotEmpty && !kIsWeb) {
      final file = File(path);
      if (await file.exists()) await file.delete();
    }
  }

  Future<AudioRecordingResult?> _doStop() async {
    final durationMs = elapsedMs;
    final path = await _recorder.stop();
    isRecording.value = false;
    _startTime = null;

    if (kIsWeb) {
      // On web, record_web returns a blob URL from stop().
      // tempPath holds the blob URL for playback; bytes are fetched by the caller.
      return AudioRecordingResult(
        bytes: Uint8List(0),
        durationMs: durationMs,
        tempPath: path ?? '',
      );
    }

    if (path == null || path.isEmpty) return null;
    final file = File(path);
    if (!await file.exists()) return null;
    final bytes = await file.readAsBytes();
    return AudioRecordingResult(
      bytes: bytes,
      durationMs: durationMs,
      tempPath: path,
    );
  }

  void dispose() {
    _maxTimer?.cancel();
    _recorder.dispose();
    isRecording.dispose();
  }
}
